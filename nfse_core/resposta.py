"""Leitura tolerante das respostas da SEFIN Nacional.

Os nomes das chaves do JSON **variam entre versões do manual** e entre
endpoints — `chaveAcesso` / `chave_acesso` / `idNfse`, `nfseXmlGZipB64` /
`nfseXmlGzipB64` / `xmlGZipB64`, `erros` / `Erros` / `erro` / `alertas`.
Ler direto por uma chave fixa funciona hoje e quebra na próxima atualização
do ambiente.

Este módulo concentra essa tolerância num lugar só, para o seu código lidar
com um objeto estável (`RespostaEmissao`) em vez de com o dicionário cru.
"""
from __future__ import annotations

import gzip
import base64
import json
import re
from dataclasses import dataclass, field

from nfse_core.error_catalog import translate_erros


def _primeiro(dados: dict, *chaves: str):
    """Primeiro valor não-vazio entre as chaves candidatas."""
    for chave in chaves:
        valor = dados.get(chave)
        if valor:
            return valor
    return None


def _descompactar(b64_gzip: str) -> bytes:
    return gzip.decompress(base64.b64decode(b64_gzip))


@dataclass
class RespostaEmissao:
    """O resultado de uma emissão, já interpretado.

    `autorizada` é a única coisa que o seu código precisa checar para decidir
    o caminho feliz — ele já considera status HTTP e presença da chave.
    """
    autorizada: bool
    http_status: int
    chave_acesso: str | None = None
    numero_nfse: str | None = None       # nDFSe, quando vem no XML autorizado
    xml_nfse: bytes | None = None        # o DOCUMENTO FISCAL — guarde este
    erros: list[dict] = field(default_factory=list)   # já traduzidos
    bruta: dict = field(default_factory=dict)         # a resposta original, intacta

    @property
    def resumo_erros(self) -> str:
        """Uma linha para log ou mensagem de erro."""
        if not self.erros:
            return ""
        return " | ".join(f"[{e['codigo']}] {e['titulo']}" for e in self.erros)

    def erros_json(self) -> str | None:
        """Pronto para gravar numa coluna de texto."""
        return json.dumps(self.erros, ensure_ascii=False) if self.erros else None


def ler_resposta_emissao(resposta: dict) -> RespostaEmissao:
    """Interpreta o retorno de `SefinClient.emitir_dps`."""
    http_status = int(resposta.get("_http_status") or 0)
    chave = _primeiro(resposta, "chaveAcesso", "chaveAcessoNfse", "chave_acesso", "idNfse")
    xml_b64 = _primeiro(resposta, "nfseXmlGZipB64", "nfseXmlGzipB64", "xmlGZipB64")
    erros_crus = _primeiro(resposta, "erros", "Erros", "erro", "alertas") or []

    xml_nfse = None
    numero = _primeiro(resposta, "nNFSe", "numero")
    if xml_b64:
        try:
            xml_nfse = _descompactar(xml_b64)
            if not numero:
                achado = re.search(rb"<nDFSe>(\d+)</nDFSe>", xml_nfse)
                numero = achado.group(1).decode() if achado else None
        except Exception:
            xml_nfse = None   # resposta corrompida não deve derrubar a leitura

    autorizada = bool(chave) and http_status < 400
    return RespostaEmissao(
        autorizada=autorizada,
        http_status=http_status,
        chave_acesso=str(chave)[:50] if chave else None,
        numero_nfse=str(numero)[:20] if numero else None,
        xml_nfse=xml_nfse,
        erros=translate_erros(erros_crus),
        bruta=resposta,
    )


@dataclass
class RespostaEvento:
    """Resultado de um cancelamento (ou outro evento)."""
    registrado: bool
    http_status: int
    xml_evento: bytes | None = None
    erros: list[dict] = field(default_factory=list)
    bruta: dict = field(default_factory=dict)

    @property
    def resumo_erros(self) -> str:
        return " | ".join(f"[{e['codigo']}] {e['titulo']}" for e in self.erros)


def ler_resposta_evento(resposta: dict) -> RespostaEvento:
    """Interpreta o retorno de `SefinClient.registrar_evento`.

    ⚠️ A chave do XML na RESPOSTA (`eventoXmlGZipB64`) é diferente da chave do
    REQUEST (`pedidoRegistroEventoXmlGZipB64`) — ver docs/ARMADILHAS.md item 7.
    """
    http_status = int(resposta.get("_http_status") or 0)
    erros_crus = _primeiro(resposta, "erros", "Erros", "erro", "alertas") or []
    xml_b64 = _primeiro(resposta, "eventoXmlGZipB64", "eventoXmlGzipB64", "xmlGZipB64")

    xml_evento = None
    if xml_b64:
        try:
            xml_evento = _descompactar(xml_b64)
        except Exception:
            xml_evento = None

    return RespostaEvento(
        registrado=http_status < 300 and not erros_crus,
        http_status=http_status,
        xml_evento=xml_evento,
        erros=translate_erros(erros_crus),
        bruta=resposta,
    )


def erros_de_falha(excecao) -> list[dict]:
    """Extrai a lista de erros do corpo bruto de um `SefinError`.

    Erro de infraestrutura/gateway às vezes traz JSON com a causa real no corpo,
    mesmo tendo estourado como falha de transporte. Sem isto, a mensagem que
    chega ao operador é só "falha de rede".
    """
    corpo = getattr(excecao, "body", None)
    if not corpo:
        return []
    try:
        dados = json.loads(corpo)
    except (ValueError, TypeError):
        return []
    return translate_erros(_primeiro(dados, "erros", "Erros", "erro") or [])
