"""Testes de nfe_core.error_catalog: catálogo de cStat da SEFAZ."""
from nfe_core.error_catalog import CATALOGO_CSTAT, eh_autorizado, eh_denegado, nao_encontrada


def test_eh_autorizado_so_para_cstat_100():
    assert eh_autorizado("100") is True
    assert eh_autorizado("110") is False
    assert eh_autorizado("999") is False


def test_nao_encontrada_so_para_cstat_217():
    assert nao_encontrada("217") is True
    for c_stat in ("100", "110", "225", "999", None):
        assert nao_encontrada(c_stat) is False


def test_eh_denegado_so_para_110_301_302():
    for c_stat in ("110", "301", "302"):
        assert eh_denegado(c_stat) is True
    for c_stat in ("100", "217", "225", "233", "999", None):
        assert eh_denegado(c_stat) is False


def test_catalogo_contem_codigos_essenciais():
    for c_stat in ("100", "110", "217", "301", "302", "539", "204"):
        assert c_stat in CATALOGO_CSTAT
        assert CATALOGO_CSTAT[c_stat]
