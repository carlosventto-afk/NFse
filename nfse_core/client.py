"""Cliente REST da SEFIN Nacional (Sistema Nacional NFS-e).

Autenticação: mTLS com o certificado A1 do prestador (ICP-Brasil).
Payload: XML da DPS assinado → GZip → Base64 → JSON.
Manual: "Contribuintes — Emissor Público API" v1.2 (out/2025), gov.br/nfse.

Ambientes:
  homologacao → produção restrita (sefin.producaorestrita.nfse.gov.br)
  producao    → sefin.nfse.gov.br
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import json
import os
import tempfile

import httpx

from nfse_core.signer import load_pfx_pem

BASE_URLS = {
    # SEM o prefixo /API: é o caminho dos integradores em produção (o /API/ da
    # página de docs roteia para um gateway com validador DIVERGENTE — E0714
    # em assinatura correta foi reproduzido lá)
    "homologacao": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
    "producao": "https://sefin.nfse.gov.br/SefinNacional",
}

# API DANFSe fica no ADN (Ambiente de Dados Nacional), domínio diferente do
# SEFIN — GET /{chaveAcesso} devolve o PDF oficial do governo. Instável em
# produção real na prática (502 observado) — sempre ter fallback para gerar
# a representação própria (nfse/danfe.py) quando esta API não responder.
DANFSE_BASE_URLS = {
    "homologacao": "https://adn.producaorestrita.nfse.gov.br/danfse",
    "producao": "https://adn.nfse.gov.br/danfse",
}


class SefinError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class SefinClient:
    """Uma instância por chamada — escreve o par cert/key em arquivos temporários
    (exigência do httpx/ssl) e os remove no close()."""

    def __init__(self, environment: str, pfx_base64: str, cert_password: str | None):
        if environment not in BASE_URLS:
            raise ValueError(f"Ambiente NFS-e inválido: {environment}")
        self.base_url = BASE_URLS[environment]
        key_pem, cert_pem, chain_pem = load_pfx_pem(pfx_base64, cert_password)
        self._cert_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        self._cert_file.write(cert_pem + b"".join(chain_pem))
        self._cert_file.close()
        self._key_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        self._key_file.write(key_pem)
        self._key_file.close()
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            cert=(self._cert_file.name, self._key_file.name),
            timeout=60.0,
            headers={"Content-Type": "application/json"},
        )

    async def close(self) -> None:
        await self._client.aclose()
        for path in (self._cert_file.name, self._key_file.name):
            try:
                os.unlink(path)
            except OSError:
                pass

    @staticmethod
    def _pack(xml_bytes: bytes) -> str:
        return base64.b64encode(gzip.compress(xml_bytes)).decode()

    @staticmethod
    def unpack(b64_gzip: str) -> bytes:
        return gzip.decompress(base64.b64decode(b64_gzip))

    async def emitir_dps(self, dps_xml_assinado: bytes) -> dict:
        """POST /nfse — emissão síncrona. Retorna o JSON da SEFIN.

        Sucesso traz a chave de acesso e o XML da NFS-e (GZip+B64); rejeição
        traz a lista de erros de validação. Nomes de campos variam entre
        versões do manual — o service usa parsing tolerante.
        """
        resp = await self._request("POST", "/nfse", json={"dpsXmlGZipB64": self._pack(dps_xml_assinado)})
        return self._handle(resp)

    async def consultar_nfse(self, chave_acesso: str) -> dict:
        resp = await self._request("GET", f"/nfse/{chave_acesso}")
        return self._handle(resp)

    async def registrar_evento(self, chave_acesso: str, evento_xml_assinado: bytes) -> dict:
        """POST /nfse/{chave}/eventos — registra um evento (ex.: cancelamento).
        Chave do JSON confirmada em SDKs de referência (não documentada em
        nenhum manual/swagger oficial): "pedidoRegistroEventoXmlGZipB64" no
        request — a resposta usa "eventoXmlGZipB64" (nomes diferentes!).
        Rota confirmada por sondagem: GET/PUT nesse recurso devolvem 405
        (existe, não aceita esses métodos)."""
        resp = await self._request(
            "POST", f"/nfse/{chave_acesso}/eventos",
            json={"pedidoRegistroEventoXmlGZipB64": self._pack(evento_xml_assinado)},
        )
        return self._handle(resp)

    async def consultar_dps(self, dps_id: str) -> dict:
        """GET /dps/{id} — devolve a chave de acesso se a DPS já virou NFS-e
        (idempotência: reenvio de DPS duplicada é rejeitado pela SEFIN)."""
        resp = await self._request("GET", f"/dps/{dps_id}")
        return self._handle(resp)

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Traduz falha de transporte (timeout, TLS, DNS) em SefinError para o
        service registrar no histórico em vez de estourar 500."""
        try:
            return await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SefinError(f"falha de rede com a SEFIN ({type(exc).__name__}): {exc}")

    @staticmethod
    async def fetch_danfse_pdf(
        environment: str, pfx_base64: str, cert_password: str | None, chave_acesso: str,
    ) -> bytes | None:
        """Busca o DANFSe (PDF oficial) na API do ADN. Retorna None (nunca
        levanta) se a API não responder após todas as tentativas — quem chama
        decide o fallback.

        Confirmado ao vivo (20/07): a API do ADN devolve 502 de forma
        intermitente — 2 tentativas seguidas falharam e só a 3ª trouxe o PDF
        real. Uma tentativa só é otimista demais pra essa infraestrutura;
        insiste algumas vezes antes de desistir (nunca sem verificação de
        certificado — é resiliência de rede, não workaround de segurança)."""
        if environment not in DANFSE_BASE_URLS:
            return None
        key_pem, cert_pem, chain_pem = load_pfx_pem(pfx_base64, cert_password)
        cert_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        cert_file.write(cert_pem + b"".join(chain_pem))
        cert_file.close()
        key_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
        key_file.write(key_pem)
        key_file.close()
        try:
            url = f"{DANFSE_BASE_URLS[environment]}/{chave_acesso}"
            for attempt in range(4):
                try:
                    async with httpx.AsyncClient(cert=(cert_file.name, key_file.name), timeout=20.0) as client:
                        resp = await client.get(url)
                    if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/pdf"):
                        return resp.content
                except httpx.HTTPError:
                    pass
                if attempt < 3:
                    await asyncio.sleep(1.5 * (attempt + 1))
            return None
        finally:
            for path in (cert_file.name, key_file.name):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    @staticmethod
    def _handle(resp: httpx.Response) -> dict:
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            payload = None
        if resp.status_code >= 500:
            raise SefinError(
                f"SEFIN indisponível (HTTP {resp.status_code})", resp.status_code, resp.text[:2000]
            )
        if payload is None:
            raise SefinError(
                f"Resposta não-JSON da SEFIN (HTTP {resp.status_code})", resp.status_code, resp.text[:2000]
            )
        payload["_http_status"] = resp.status_code
        return payload
