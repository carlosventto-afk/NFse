from datetime import date, datetime, timezone
from decimal import Decimal

from lxml import etree

from nfse_core import DpsData, build_dps_xml
from nfse_core.dps import NFSE_NS


def _dados_base(**overrides) -> DpsData:
    base = dict(
        tp_amb=2, dh_emi=datetime.now(timezone.utc), serie="1", numero=1,
        competencia=date(2026, 8, 1), prest_cnpj="12345678000199", prest_im="123456",
        c_loc_emi="1501402", op_simp_nac=3, toma_cpf_cnpj="98765432100",
        toma_nome="Cliente Teste", c_trib_nac="141001", x_desc_serv="Lavagem de roupa",
        v_serv=Decimal("49.90"),
    )
    base.update(overrides)
    return DpsData(**base)


def test_sem_ibs_cbs_mantem_versao_1_00_e_omite_o_bloco():
    xml = build_dps_xml(_dados_base())

    root = etree.fromstring(xml)
    assert root.get("versao") == "1.00"
    assert root.find(f"{{{NFSE_NS}}}infDPS/{{{NFSE_NS}}}IBSCBS") is None


def test_ibs_cbs_completo_usa_versao_1_01_e_inclui_o_bloco():
    dados = _dados_base(ibs_cbs_cst="200", ibs_cbs_class_trib="200001", ibs_cbs_cod_ind_op="1")

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    assert root.get("versao") == "1.01"
    ibscbs = root.find(f"{{{NFSE_NS}}}infDPS/{{{NFSE_NS}}}IBSCBS")
    assert ibscbs is not None
    assert ibscbs.find(f"{{{NFSE_NS}}}finNFSe").text == "0"
    assert ibscbs.find(f"{{{NFSE_NS}}}cIndOp").text == "000001"
    assert ibscbs.find(f"{{{NFSE_NS}}}indDest").text == "0"
    gibscbs = ibscbs.find(
        f"{{{NFSE_NS}}}valores/{{{NFSE_NS}}}trib/{{{NFSE_NS}}}gIBSCBS",
    )
    assert gibscbs is not None
    assert gibscbs.find(f"{{{NFSE_NS}}}CST").text == "200"
    assert gibscbs.find(f"{{{NFSE_NS}}}cClassTrib").text == "200001"


def test_ibs_cbs_parcial_nao_inclui_o_bloco():
    # "Obrigatorios quando aplicavel" -- nunca manda o grupo pela metade.
    dados = _dados_base(ibs_cbs_cst="200", ibs_cbs_class_trib="200001", ibs_cbs_cod_ind_op=None)

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    assert root.get("versao") == "1.00"
    assert root.find(f"{{{NFSE_NS}}}infDPS/{{{NFSE_NS}}}IBSCBS") is None


def test_ibs_cbs_vem_depois_de_valores():
    # Ordem importa no XSD (infDPS): ... toma, serv, valores, IBSCBS.
    dados = _dados_base(ibs_cbs_cst="200", ibs_cbs_class_trib="200001", ibs_cbs_cod_ind_op="1")

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    inf = root.find(f"{{{NFSE_NS}}}infDPS")
    tags = [child.tag.split("}")[-1] for child in inf]
    assert tags.index("IBSCBS") == tags.index("valores") + 1
