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


def test_build_dps_xml_sem_trib_mun_omite_a_tag():
    dados = _dados_base()

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    cserv = root.find(f"{{{NFSE_NS}}}infDPS/{{{NFSE_NS}}}serv/{{{NFSE_NS}}}cServ")
    assert cserv.find(f"{{{NFSE_NS}}}cTribMun") is None


def test_build_dps_xml_com_trib_mun_inclui_e_completa_com_zeros():
    # Belem (municipio_ibge 1501402) exige esse campo -- confirmado ao vivo
    # via rejeicao L0017 "O codigo de tributacao municipal nao foi informado".
    dados = _dados_base(c_trib_mun="7")

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    cserv = root.find(f"{{{NFSE_NS}}}infDPS/{{{NFSE_NS}}}serv/{{{NFSE_NS}}}cServ")
    trib_mun = cserv.find(f"{{{NFSE_NS}}}cTribMun")
    assert trib_mun is not None
    assert trib_mun.text == "007"


def test_build_dps_xml_trib_mun_vem_antes_da_descricao_do_servico():
    # Ordem importa no XSD (TCCServ): cTribNac, cTribMun, xDescServ, ...
    dados = _dados_base(c_trib_mun="123")

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    cserv = root.find(f"{{{NFSE_NS}}}infDPS/{{{NFSE_NS}}}serv/{{{NFSE_NS}}}cServ")
    tags = [child.tag.split("}")[-1] for child in cserv]
    assert tags.index("cTribMun") == tags.index("cTribNac") + 1
    assert tags.index("xDescServ") == tags.index("cTribMun") + 1
