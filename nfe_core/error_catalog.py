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
    # Consulta
    "217": "NF-e não consta na base de dados da SEFAZ",
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
_C_STAT_NAO_ENCONTRADA = "217"
_C_STATS_DENEGADO = frozenset({"110", "301", "302"})


def eh_autorizado(c_stat: str | None) -> bool:
    """True somente para cStat 100 (NF-e autorizada)."""
    return c_stat == _C_STAT_AUTORIZADO


def nao_encontrada(c_stat: str | None) -> bool:
    """True somente para cStat 217 (NF-e não consta na base da SEFAZ).

    Na consulta de protocolo, é o ÚNICO status que garante que reenviar a
    chave é seguro: a SEFAZ não tem registro algum dela."""
    return c_stat == _C_STAT_NAO_ENCONTRADA


def eh_denegado(c_stat: str | None) -> bool:
    """True para uso denegado (110/301/302): resultado FINAL -- o número fica
    queimado na SEFAZ com protocolo de denegação; retentar não resolve."""
    return c_stat in _C_STATS_DENEGADO
