"""Catálogo de códigos de status (cStat) retornados pela SEFAZ para NF-e.

Tabela estática com os códigos mais comuns da documentação pública do
Manual de Orientação do Contribuinte (MOC). Não é exaustiva: código fora
da tabela cai no fallback genérico do chamador, que mostra o código e a
descrição original retornada pela SEFAZ, sem inventar explicação.
"""
from __future__ import annotations

CATALOGO_CSTAT: dict[str, str] = {
    # Sucesso / processamento
    "100": "Autorizado o uso da NF-e",
    "101": "Cancelamento de NF-e homologado",
    "103": "Lote recebido com sucesso",
    "104": "Lote processado",
    "105": "Lote em processamento",
    # Rejeições de conteúdo e schema
    "202": "Rejeição: falha no preenchimento da NF-e",
    "204": "Rejeição: duplicidade de NF-e",
    "225": "Rejeição: erro no schema XML",
    "233": "Rejeição: IE do destinatário não cadastrada",
    "539": "Rejeição: duplicidade de NF-e com diferença na chave de acesso",
    # Uso denegado
    "110": "Uso denegado",
    "301": "Uso denegado: irregularidade fiscal do emitente",
    "302": "Uso denegado: irregularidade fiscal do destinatário",
}

_C_STAT_AUTORIZADO = "100"


def eh_autorizado(c_stat: str) -> bool:
    """True somente para cStat 100 (NF-e autorizada)."""
    return c_stat == _C_STAT_AUTORIZADO
