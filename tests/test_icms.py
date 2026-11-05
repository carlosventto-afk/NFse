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


def test_venda_interestadual_calcula_partilha_e_fcp():
    resultado = calcular_icms_item(Decimal("100.00"), "PA", "SP", Decimal("18.00"), "102")
    assert resultado.valor_icms_uf_destino > 0
    assert resultado.valor_icms_uf_remetente >= 0
