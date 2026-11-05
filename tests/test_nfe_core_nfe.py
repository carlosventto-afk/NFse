"""Testes de nfe_core.nfe: NfeData, chave de acesso e build_nfe_xml."""
from datetime import datetime
from decimal import Decimal

import pytest

from nfe_core.nfe import NfeData, NfeItemData, build_nfe_xml, chave_de_acesso

_ITEM_FIELDS = {
    "n_item", "c_prod", "descricao", "ncm", "cfop", "unidade", "quantidade",
    "valor_unitario", "valor_total", "cst_icms", "csosn_icms", "base_icms",
    "valor_icms", "valor_icms_uf_remetente", "valor_icms_uf_destino", "valor_fcp",
}


def _nfe_data_minima(**overrides) -> NfeData:
    item_kwargs = {
        "n_item": 1,
        "c_prod": "PROD1",
        "descricao": "Produto Teste",
        "ncm": "12345678",
        "cfop": "5102",
        "unidade": "UN",
        "quantidade": Decimal("1"),
        "valor_unitario": Decimal("10.00"),
        "valor_total": Decimal("10.00"),
        "cst_icms": "00",
        "csosn_icms": None,
        "base_icms": Decimal("10.00"),
        "valor_icms": Decimal("1.80"),
        "valor_icms_uf_remetente": None,
        "valor_icms_uf_destino": None,
        "valor_fcp": None,
    }
    for key in list(overrides):
        if key in _ITEM_FIELDS:
            item_kwargs[key] = overrides.pop(key)

    data_kwargs = {
        "tp_amb": 2,
        "c_uf_emit": "15",
        "dh_emi": datetime(2026, 11, 5, 10, 0, 0),
        "serie": "1",
        "numero": 1,
        "emit_cnpj": "12345678000195",
        "emit_ie": "123456789",
        "emit_crt": 3,
        "emit_uf": "PA",
        "dest_cpf_cnpj": "12345678901",
        "dest_nome": "Cliente Teste",
        "dest_uf": "PA",
        "dest_ie": None,
        "itens": [NfeItemData(**item_kwargs)],
    }
    data_kwargs.update(overrides)
    return NfeData(**data_kwargs)


def test_chave_de_acesso_tem_44_digitos_e_dv_valido():
    data = _nfe_data_minima()
    chave = chave_de_acesso(data, c_nf="12345678")
    assert len(chave) == 44
    assert chave.isdigit()


def test_build_nfe_xml_rejeita_item_sem_cst_nem_csosn():
    data = _nfe_data_minima(cst_icms=None, csosn_icms=None)
    with pytest.raises(ValueError, match="CST ou CSOSN"):
        build_nfe_xml(data)


def test_build_nfe_xml_inclui_icms_uf_destino_quando_interestadual():
    data = _nfe_data_minima(emit_uf="PA", dest_uf="SP",
                             valor_icms_uf_destino=Decimal("10.00"), valor_fcp=Decimal("2.00"))
    xml = build_nfe_xml(data)
    assert b"vICMSUFDest" in xml
    assert b"vFCP" in xml


def test_build_nfe_xml_inclui_dhemi():
    data = _nfe_data_minima(dh_emi=datetime(2026, 11, 5, 10, 0, 0))
    xml = build_nfe_xml(data)
    assert b"<dhEmi>2026-11-05T10:00:00</dhEmi>" in xml
