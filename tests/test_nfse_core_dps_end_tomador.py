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


def test_build_dps_xml_com_endereco_completo_monta_bloco_end():
    dados = _dados_base(
        toma_end_logradouro="Rua das Flores", toma_end_numero="100",
        toma_end_complemento="Ap 1", toma_end_bairro="Centro",
        toma_end_municipio_ibge="3550308", toma_end_cep="01001000",
    )

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    toma = root.find(f"{{{NFSE_NS}}}infDPS").find(f"{{{NFSE_NS}}}toma")
    end = toma.find(f"{{{NFSE_NS}}}end")
    assert end is not None
    assert end.find(f"{{{NFSE_NS}}}xLgr").text == "Rua das Flores"
    assert end.find(f"{{{NFSE_NS}}}nro").text == "100"
    assert end.find(f"{{{NFSE_NS}}}xCpl").text == "Ap 1"
    assert end.find(f"{{{NFSE_NS}}}xBairro").text == "Centro"
    end_nac = end.find(f"{{{NFSE_NS}}}endNac")
    assert end_nac.find(f"{{{NFSE_NS}}}cMun").text == "3550308"
    assert end_nac.find(f"{{{NFSE_NS}}}CEP").text == "01001000"


def test_build_dps_xml_sem_endereco_omite_bloco_end():
    dados = _dados_base()  # sem nenhum toma_end_*

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    toma = root.find(f"{{{NFSE_NS}}}infDPS").find(f"{{{NFSE_NS}}}toma")
    assert toma.find(f"{{{NFSE_NS}}}end") is None


def test_build_dps_xml_com_endereco_parcial_sem_municipio_omite_bloco_end():
    # logradouro sozinho, sem cLocEmi do tomador, nao e suficiente —
    # cMun e obrigatorio dentro de endNac quando o bloco existe.
    dados = _dados_base(toma_end_logradouro="Rua das Flores")

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    toma = root.find(f"{{{NFSE_NS}}}infDPS").find(f"{{{NFSE_NS}}}toma")
    assert toma.find(f"{{{NFSE_NS}}}end") is None


def test_build_dps_xml_com_endereco_mas_sem_tomador_nao_monta_bloco_toma():
    # Documento do tomador continua opcional (Task 5 do plano anterior) —
    # endereco sem documento nao "inventa" um bloco <toma>.
    dados = _dados_base(toma_cpf_cnpj=None, toma_nome="", toma_end_logradouro="Rua X",
                         toma_end_municipio_ibge="3550308")

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    assert root.find(f"{{{NFSE_NS}}}infDPS").find(f"{{{NFSE_NS}}}toma") is None
