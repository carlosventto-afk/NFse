from decimal import Decimal

import pytest

from app.adapters.icms import AliquotaInterestadualInvalida, calcular_icms_item


def test_venda_interna_nao_calcula_difal():
    resultado = calcular_icms_item(Decimal("100.00"), "PA", "PA", None, "102")
    assert resultado.valor_icms_uf_destino is None
    assert resultado.valor_fcp is None


def test_venda_interestadual_sem_aliquota_interna_levanta_erro_claro():
    with pytest.raises(AliquotaInterestadualInvalida, match="aliquota interna"):
        calcular_icms_item(Decimal("100.00"), "PA", "SP", None, "102")


@pytest.mark.parametrize("uf_origem", ["PR", "SC", "RS"])
def test_origem_sul_sudeste_para_norte_nordeste_co_es_usa_7_porcento(uf_origem):
    resultado = calcular_icms_item(Decimal("100.00"), uf_origem, "BA", Decimal("18.00"), "102")
    assert resultado.valor_icms == Decimal("100.00") * Decimal("0.07")


def test_venda_interestadual_calcula_partilha_e_fcp():
    resultado = calcular_icms_item(Decimal("100.00"), "PA", "SP", Decimal("18.00"), "102")
    assert resultado.valor_icms_uf_destino > 0
    assert resultado.valor_icms_uf_remetente >= 0
