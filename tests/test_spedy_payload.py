import uuid
from datetime import date
from decimal import Decimal

from app.adapters.spedy_payload import montar_payload_spedy
from app.models import Emissao, Empresa, OrigemEmissao, StatusEmissao


def _empresa(**overrides) -> Empresa:
    dados = dict(
        cnpj="12345678000199", municipio_ibge="1501402", op_simp_nac=3,
        codigo_tributacao="140106", codigo_tributacao_municipal=None,
        descricao_servico_padrao="Lavagem", local_prestacao_ibge=None,
    )
    dados.update(overrides)
    return Empresa(**dados)


def _emissao(**overrides) -> Emissao:
    dados = dict(
        id=uuid.uuid4(), origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, descricao="Lavagem de roupa", valor=Decimal("49.90"),
        competencia=date(2026, 9, 1), tomador_cpf_cnpj=None, tomador_nome=None, tomador_email=None,
    )
    dados.update(overrides)
    return Emissao(**dados)


def test_monta_campos_basicos():
    payload = montar_payload_spedy(_empresa(), _emissao())

    assert payload["description"] == "Lavagem de roupa"
    assert payload["total"]["invoiceAmount"] == 49.90
    assert payload["city"]["code"] == "1501402"
    assert payload["location"] == "companyMunicipality"
    assert payload["federalServiceCode"] == "140106"
    assert payload["issue"] is True
    assert "receiver" not in payload
    assert "cityServiceCode" not in payload


def test_integration_id_e_o_id_da_emissao():
    emissao = _emissao()
    payload = montar_payload_spedy(_empresa(), emissao)
    assert payload["integrationId"] == str(emissao.id)


def test_usa_local_de_prestacao_quando_diferente_do_municipio_emissor():
    payload = montar_payload_spedy(_empresa(local_prestacao_ibge="3550308"), _emissao())
    assert payload["city"]["code"] == "3550308"
    assert payload["location"] == "serviceProvisionMunicipality"


def test_inclui_receiver_quando_ha_documento_do_tomador():
    emissao = _emissao(tomador_cpf_cnpj="98765432100", tomador_nome="Cliente", tomador_email="c@x.com")
    payload = montar_payload_spedy(_empresa(), emissao)
    assert payload["receiver"] == {
        "federalTaxNumber": "98765432100", "name": "Cliente", "email": "c@x.com",
    }


def test_inclui_codigo_tributacao_municipal_quando_presente():
    payload = montar_payload_spedy(_empresa(codigo_tributacao_municipal="007"), _emissao())
    assert payload["cityServiceCode"] == "007"
