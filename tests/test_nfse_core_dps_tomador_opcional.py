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


def test_build_dps_xml_sem_tomador_omite_bloco_toma_inteiro():
    dados = _dados_base(toma_cpf_cnpj=None, toma_nome="")

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    inf = root.find(f"{{{NFSE_NS}}}infDPS")
    assert inf.find(f"{{{NFSE_NS}}}toma") is None


def test_build_dps_xml_com_tomador_mantem_bloco_toma_como_antes():
    dados = _dados_base()

    xml = build_dps_xml(dados)

    root = etree.fromstring(xml)
    inf = root.find(f"{{{NFSE_NS}}}infDPS")
    toma = inf.find(f"{{{NFSE_NS}}}toma")
    assert toma is not None
    assert toma.find(f"{{{NFSE_NS}}}CPF").text == "98765432100"
    assert toma.find(f"{{{NFSE_NS}}}xNome").text == "Cliente Teste"


def test_build_dps_xml_com_documento_invalido_ainda_levanta_erro():
    dados = _dados_base(toma_cpf_cnpj="123")  # nem 11 nem 14 digitos

    try:
        build_dps_xml(dados)
        assert False, "deveria ter levantado ValueError"
    except ValueError as exc:
        assert "tomador" in str(exc).lower()
