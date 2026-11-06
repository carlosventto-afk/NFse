from decimal import Decimal

import pytest

from app.adapters.icms import AliquotaInterestadualInvalida, calcular_icms_item


def test_venda_interna_nao_calcula_difal():
    resultado = calcular_icms_item(Decimal("100.00"), "PA", "PA", None, "102", dest_ie=None)
    assert resultado.valor_icms_uf_destino is None
    assert resultado.valor_fcp is None


def test_venda_interna_para_contribuinte_tambem_nao_calcula_difal():
    resultado = calcular_icms_item(Decimal("100.00"), "PA", "PA", Decimal("19.00"), "00", dest_ie="123456789")
    assert resultado.valor_icms == Decimal("19.00")
    assert resultado.valor_icms_uf_remetente is None
    assert resultado.valor_icms_uf_destino is None
    assert resultado.valor_fcp is None


def test_venda_interestadual_sem_aliquota_interna_levanta_erro_claro():
    with pytest.raises(AliquotaInterestadualInvalida, match="aliquota interna"):
        calcular_icms_item(Decimal("100.00"), "PA", "SP", None, "102", dest_ie=None)


@pytest.mark.parametrize("uf_origem", ["PR", "SC", "RS"])
def test_origem_sul_sudeste_para_norte_nordeste_co_es_usa_7_porcento(uf_origem):
    resultado = calcular_icms_item(Decimal("100.00"), uf_origem, "BA", Decimal("18.00"), "102", dest_ie=None)
    assert resultado.valor_icms == Decimal("100.00") * Decimal("0.07")


def test_venda_interestadual_calcula_partilha_e_fcp():
    resultado = calcular_icms_item(Decimal("100.00"), "PA", "SP", Decimal("18.00"), "102", dest_ie=None)
    assert resultado.valor_icms_uf_destino > 0
    assert resultado.valor_icms_uf_remetente >= 0


def test_venda_interestadual_nao_contribuinte_valores_exatos_da_partilha():
    # PA -> SP: interestadual 12%, interna do destino 18% => DIFAL 6% integral pro destino.
    resultado = calcular_icms_item(Decimal("100.00"), "PA", "SP", Decimal("18.00"), "101", dest_ie=None)
    assert resultado.base_icms == Decimal("100.00")
    assert resultado.valor_icms == Decimal("12.00")
    assert resultado.valor_icms_uf_destino == Decimal("6.00")
    assert resultado.valor_icms_uf_remetente == Decimal("0.00")
    assert resultado.valor_fcp == Decimal("0.00")


def test_venda_interestadual_para_contribuinte_nao_tem_partilha_nem_exige_aliquota_interna():
    # B2B interestadual (destinatario com IE): ICMS a aliquota interestadual,
    # sem DIFAL/partilha/FCP -- e aliquota_interna_destino e irrelevante.
    resultado = calcular_icms_item(Decimal("100.00"), "PA", "SP", None, "101", dest_ie="123456789")
    assert resultado.base_icms == Decimal("100.00")
    assert resultado.valor_icms == Decimal("12.00")
    assert resultado.valor_icms_uf_remetente is None
    assert resultado.valor_icms_uf_destino is None
    assert resultado.valor_fcp is None


def test_venda_interestadual_para_contribuinte_ignora_aliquota_interna_informada():
    resultado = calcular_icms_item(Decimal("100.00"), "SP", "BA", Decimal("20.50"), "00", dest_ie="123456789")
    assert resultado.valor_icms == Decimal("7.00")
    assert resultado.valor_icms_uf_destino is None
    assert resultado.valor_icms_uf_remetente is None
    assert resultado.valor_fcp is None
