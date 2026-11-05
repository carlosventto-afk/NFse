"""Testes de nfe_core.error_catalog: catálogo de cStat da SEFAZ."""
from nfe_core.error_catalog import CATALOGO_CSTAT, eh_autorizado


def test_eh_autorizado_so_para_cstat_100():
    assert eh_autorizado("100") is True
    assert eh_autorizado("110") is False
    assert eh_autorizado("999") is False


def test_catalogo_contem_codigos_essenciais():
    for c_stat in ("100", "110", "301", "302", "539", "204"):
        assert c_stat in CATALOGO_CSTAT
        assert CATALOGO_CSTAT[c_stat]
