"""Cliente REST da Spedy (docs.spedy.com.br) -- provedor alternativo de
emissao de NFS-e. Ao contrario de nfse_core/client.py, aqui NAO ha
montagem/assinatura de XML: a Spedy recebe dados estruturados e assina do
lado dela, usando o certificado A1 enviado uma vez no provisionamento
(ver provisionar_empresa)."""
from __future__ import annotations

import httpx

BASE_URLS = {
    "homologacao": "https://sandbox-api.spedy.com.br/v1",
    "producao": "https://api.spedy.com.br/v1",
}


class SpedyError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class SpedyClient:
    def __init__(self, ambiente: str, api_key: str):
        if ambiente not in BASE_URLS:
            raise ValueError(f"Ambiente Spedy invalido: {ambiente}")
        self._client = httpx.AsyncClient(
            base_url=BASE_URLS[ambiente],
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SpedyError(f"falha de rede com a Spedy ({type(exc).__name__}): {exc}")

    # -- provisionamento (chamadas com a chave MESTRE ou a da empresa recem-criada) --

    async def criar_empresa(self, dados: dict) -> dict:
        resp = await self._request("POST", "/companies", json=dados)
        corpo = self._handle_estrito(resp)
        # Confirmado ao vivo em producao (16/09): a resposta real do POST
        # /companies NAO vem no formato {"result": {...}} que a doc publica
        # descreve -- os campos (id, apiCredentials) vem direto na raiz.
        # Tolerante aos dois formatos, igual ao resto do modulo.
        return corpo.get("result", corpo)

    async def adicionar_certificado(self, spedy_empresa_id: str, pfx_bytes: bytes, senha: str) -> dict:
        resp = await self._request(
            "POST", f"/companies/{spedy_empresa_id}/certificates",
            files={"certificateFile": ("certificado.pfx", pfx_bytes, "application/x-pkcs12")},
            data={"password": senha},
        )
        return self._handle_estrito(resp)

    async def configurar_nfse(self, spedy_empresa_id: str, dados: dict) -> dict:
        resp = await self._request(
            "PUT", f"/companies/{spedy_empresa_id}/settings", json={"serviceInvoice": dados},
        )
        return self._handle_estrito(resp)

    # -- emissao/consulta/cancelamento (chamadas com a X-Api-Key da empresa) --

    async def emitir_nfse(self, payload: dict) -> dict:
        resp = await self._request("POST", "/service-invoices", json=payload)
        return self._handle(resp)

    async def consultar_nfse(self, spedy_nota_id: str) -> dict:
        resp = await self._request("GET", f"/service-invoices/{spedy_nota_id}")
        return self._handle(resp)

    async def cancelar_nfse(self, spedy_nota_id: str, motivo: str) -> dict:
        resp = await self._request(
            "DELETE", f"/service-invoices/{spedy_nota_id}", json={"reason": motivo},
        )
        return self._handle(resp)

    async def baixar_pdf(self, spedy_nota_id: str) -> bytes:
        resp = await self._request("GET", f"/service-invoices/{spedy_nota_id}/pdf")
        if resp.status_code >= 400:
            raise SpedyError(
                f"Spedy recusou o PDF (HTTP {resp.status_code})", resp.status_code, str(resp.text)[:2000],
            )
        return resp.content

    @staticmethod
    def _handle(resp: httpx.Response) -> dict:
        """Tolerante: so levanta em 5xx/resposta nao-JSON. Rejeicao de negocio
        (4xx) volta como dict com `_http_status`, pro worker interpretar --
        mesmo padrao de nfse_core/client.py."""
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if resp.status_code >= 500 or payload is None:
            raise SpedyError(
                f"Spedy indisponivel ou resposta invalida (HTTP {resp.status_code})",
                resp.status_code, str(resp.text)[:2000],
            )
        payload["_http_status"] = resp.status_code
        return payload

    @staticmethod
    def _handle_estrito(resp: httpx.Response) -> dict:
        """Usado so no provisionamento: e uma acao explicita do admin, entao
        QUALQUER erro (nao so 5xx) deve virar excecao na hora."""
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if resp.status_code >= 400 or payload is None:
            detalhe = (payload or {}).get("message") if isinstance(payload, dict) else None
            raise SpedyError(
                detalhe or f"Spedy recusou a requisicao (HTTP {resp.status_code})",
                resp.status_code, str(resp.text)[:2000],
            )
        return payload
