"""Testes de nfe_core.nfe: NfeData, chave de acesso e build_nfe_xml."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from lxml import etree

from app.adapters.icms import calcular_icms_item
from nfe_core.nfe import NFE_NS, NfeData, NfeItemData, build_nfe_xml, chave_de_acesso

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
        "dh_emi": datetime(2026, 11, 5, 10, 0, 0, tzinfo=timezone.utc),
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


def _ide_tags(xml: bytes) -> list[str]:
    root = etree.fromstring(xml)
    ide = root.find(f".//{{{NFE_NS}}}ide")
    return [etree.QName(child).localname for child in ide]


def _ide_text(xml: bytes, tag: str) -> str | None:
    node = etree.fromstring(xml).find(f".//{{{NFE_NS}}}ide/{{{NFE_NS}}}{tag}")
    return None if node is None else node.text


@pytest.mark.parametrize("dest_ie,ind_final", [(None, "1"), ("123456789", "0")])
def test_build_nfe_xml_ind_final_deriva_do_dest_ie(dest_ie, ind_final):
    # indFinal: 1 = consumidor final (destinatario sem IE), 0 = contribuinte.
    xml = build_nfe_xml(_nfe_data_minima(dest_ie=dest_ie))
    assert _ide_text(xml, "indFinal") == ind_final


def test_build_nfe_xml_ind_final_vem_logo_apos_fin_nfe():
    tags = _ide_tags(build_nfe_xml(_nfe_data_minima()))
    assert tags[tags.index("finNFe") + 1] == "indFinal"


def test_build_nfe_xml_recusa_partilha_para_destinatario_contribuinte():
    # ICMSUFDest (DIFAL) so existe pra nao contribuinte -- partilha com
    # destinatario com IE e dado inconsistente, erra alto em vez de emitir.
    data = _nfe_data_minima(emit_uf="PA", dest_uf="SP", dest_ie="123456789",
                             valor_icms_uf_destino=Decimal("10.00"), valor_fcp=Decimal("2.00"),
                             valor_icms_uf_remetente=Decimal("0.00"))
    with pytest.raises(ValueError, match="contribuinte"):
        build_nfe_xml(data)


def test_build_nfe_xml_interestadual_para_contribuinte_sem_icms_uf_dest():
    data = _nfe_data_minima(emit_uf="PA", dest_uf="SP", dest_ie="123456789")
    xml = build_nfe_xml(data)
    assert b"ICMSUFDest" not in xml
    assert _ide_text(xml, "idDest") == "2"
    assert _ide_text(xml, "indFinal") == "0"


def _icms_grupo(xml: bytes) -> etree._Element:
    icms = etree.fromstring(xml).find(f".//{{{NFE_NS}}}ICMS")
    (grupo,) = list(icms)
    return grupo


def _filhos(grupo: etree._Element) -> list[str]:
    return [etree.QName(child).localname for child in grupo]


@pytest.mark.parametrize("csosn", ["102", "103", "300", "400"])
def test_build_nfe_xml_csosn_sem_calculo_omite_vbc_e_vicms(csosn):
    # CSOSN 102/103/300/400 nao tem vBC/vICMS no leiaute -- todos usam o
    # grupo ICMSSN102. Mesmo com base/valor preenchidos, nao vao pro XML.
    data = _nfe_data_minima(emit_crt=1, cst_icms=None, csosn_icms=csosn,
                             base_icms=Decimal("10.00"), valor_icms=Decimal("1.20"))
    grupo = _icms_grupo(build_nfe_xml(data))
    assert etree.QName(grupo).localname == "ICMSSN102"
    assert _filhos(grupo) == ["orig", "CSOSN"]
    assert grupo.find(f"{{{NFE_NS}}}CSOSN").text == csosn


@pytest.mark.parametrize("cst", ["40", "41", "50"])
def test_build_nfe_xml_cst_sem_calculo_omite_vbc_e_vicms(cst):
    # CST 40/41/50 (isenta/nao tributada/suspensao) usam o grupo ICMS40, sem vBC/vICMS.
    data = _nfe_data_minima(cst_icms=cst, base_icms=Decimal("10.00"), valor_icms=Decimal("1.80"))
    grupo = _icms_grupo(build_nfe_xml(data))
    assert etree.QName(grupo).localname == "ICMS40"
    assert _filhos(grupo) == ["orig", "CST"]
    assert grupo.find(f"{{{NFE_NS}}}CST").text == cst


@pytest.mark.parametrize("cst", ["00", "10", "20", "51", "70", "90"])
def test_build_nfe_xml_cst_com_vbc_vicms_mantem_vbc_e_vicms(cst):
    grupo = _icms_grupo(build_nfe_xml(_nfe_data_minima(cst_icms=cst)))
    assert etree.QName(grupo).localname == f"ICMS{cst}"
    assert grupo.find(f"{{{NFE_NS}}}vBC").text == "10.00"
    assert grupo.find(f"{{{NFE_NS}}}vICMS").text == "1.80"


@pytest.mark.parametrize("cst", ["30", "60"])
def test_build_nfe_xml_cst_30_e_60_omitem_vbc_e_vicms(cst):
    # CST 30 (isenta/nao tributada com ST) e 60 (ST ja retido) nao tem
    # vBC/vICMS no leiaute -- a antiga skip-list deixava passar.
    data = _nfe_data_minima(cst_icms=cst, base_icms=Decimal("10.00"), valor_icms=Decimal("1.80"))
    grupo = _icms_grupo(build_nfe_xml(data))
    assert etree.QName(grupo).localname == f"ICMS{cst}"
    assert _filhos(grupo) == ["orig", "CST"]


def test_build_nfe_xml_csosn_101_omite_vbc_e_vicms():
    # Regressao: CSOSN 101 (o mais comum do Simples Nacional) NAO tem
    # vBC/vICMS no leiaute (tem pCredSN/vCredICMSSN, ainda nao modelados).
    # Grupo sai "pelado" (orig+CSOSN) em vez de com campos errados.
    data = _nfe_data_minima(emit_crt=1, cst_icms=None, csosn_icms="101",
                             base_icms=Decimal("10.00"), valor_icms=Decimal("1.20"))
    grupo = _icms_grupo(build_nfe_xml(data))
    assert etree.QName(grupo).localname == "ICMSSN101"
    assert _filhos(grupo) == ["orig", "CSOSN"]


def test_build_nfe_xml_csosn_900_mantem_vbc_e_vicms():
    # CSOSN 900 ("Outros") e o unico do Simples Nacional com vBC/vICMS.
    data = _nfe_data_minima(emit_crt=1, cst_icms=None, csosn_icms="900",
                             base_icms=Decimal("10.00"), valor_icms=Decimal("1.20"))
    grupo = _icms_grupo(build_nfe_xml(data))
    assert etree.QName(grupo).localname == "ICMSSN900"
    assert _filhos(grupo) == ["orig", "CSOSN", "vBC", "vICMS"]
    assert grupo.find(f"{{{NFE_NS}}}vBC").text == "10.00"
    assert grupo.find(f"{{{NFE_NS}}}vICMS").text == "1.20"


def test_build_nfe_xml_recusa_difal_sem_valores_de_partilha():
    # Gate diz DIFAL (interestadual + nao contribuinte), mas o item nao traz
    # partilha nenhuma: calcular_icms_item nao foi chamado (ou foi chamado
    # com outro criterio de contribuinte) -- erra alto em vez de omitir ICMSUFDest.
    data = _nfe_data_minima(emit_uf="PA", dest_uf="SP", dest_ie=None)
    with pytest.raises(ValueError, match="partilha"):
        build_nfe_xml(data)


def _dest_text(xml: bytes, tag: str) -> str | None:
    node = etree.fromstring(xml).find(f".//{{{NFE_NS}}}dest/{{{NFE_NS}}}{tag}")
    return None if node is None else node.text


@pytest.mark.parametrize("dest_ie", ["", "   "])
def test_ie_vazia_e_nao_contribuinte_tanto_no_calculo_quanto_no_xml(dest_ie):
    # calcular_icms_item e build_nfe_xml chamados direto (sem o nfe_builder,
    # que ja normaliza IE em branco) precisam concordar: IE vazia = sem IE.
    icms = calcular_icms_item(Decimal("10.00"), "PA", "SP", Decimal("18.00"), "00", dest_ie=dest_ie)
    assert icms.valor_icms_uf_destino == Decimal("0.60")

    data = _nfe_data_minima(
        emit_uf="PA", dest_uf="SP", dest_ie=dest_ie,
        base_icms=icms.base_icms, valor_icms=icms.valor_icms,
        valor_icms_uf_remetente=icms.valor_icms_uf_remetente,
        valor_icms_uf_destino=icms.valor_icms_uf_destino, valor_fcp=icms.valor_fcp,
    )
    xml = build_nfe_xml(data)
    assert _ide_text(xml, "indFinal") == "1"
    assert _dest_text(xml, "indIEDest") == "9"
    assert _dest_text(xml, "IE") is None
    assert b"<vICMSUFDest>0.60</vICMSUFDest>" in xml


def test_build_nfe_xml_inclui_dhemi():
    data = _nfe_data_minima(dh_emi=datetime(2026, 11, 5, 10, 0, 0, tzinfo=timezone.utc))
    xml = build_nfe_xml(data)
    assert b"<dhEmi>2026-11-05T10:00:00+00:00</dhEmi>" in xml


def test_build_nfe_xml_recusa_dh_emi_naive():
    # dhEmi sem offset UTC e invalido no leiaute -- erra alto em vez de
    # gerar a tag sem fuso.
    data = _nfe_data_minima(dh_emi=datetime(2026, 11, 5, 10, 0, 0))
    with pytest.raises(ValueError, match="timezone"):
        build_nfe_xml(data)
