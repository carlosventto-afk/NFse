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
    assert payload["location"] == {"code": "1501402"}
    assert payload["federalServiceCode"] == "140106"
    assert payload["issue"] is True
    assert "cityServiceCode" not in payload


def test_effective_date_usa_fuso_de_brasilia_nao_utc():
    # Fix I7: meia-noite UTC do dia de competencia e 21h BRT do dia ANTERIOR.
    # Se a Spedy localizar o effectiveDate, uma competencia no dia 1 do mes
    # cairia no ultimo dia do mes anterior. O offset gravado precisa ser
    # -03:00 (BRT, sem horario de verao desde 2019), nunca +00:00/Z.
    payload = montar_payload_spedy(_empresa(), _emissao())

    assert payload["effectiveDate"].endswith("-03:00")
    assert payload["effectiveDate"].startswith("2026-09-01T00:00:00")


def test_integration_id_e_diferente_a_cada_chamada():
    # Confirmado ao vivo (24/09): a Spedy usa integrationId como chave de
    # idempotencia -- reaproveitar o id da emissao (estavel entre tentativas
    # de "Reemitir") fazia ela devolver sempre o mesmo resultado rejeitado
    # antigo, sem nunca tentar de novo com a prefeitura.
    emissao = _emissao()
    primeira = montar_payload_spedy(_empresa(), emissao)
    segunda = montar_payload_spedy(_empresa(), emissao)
    assert primeira["integrationId"] != segunda["integrationId"]
    assert primeira["integrationId"] != str(emissao.id)


def test_usa_local_de_prestacao_quando_diferente_do_municipio_emissor():
    payload = montar_payload_spedy(_empresa(local_prestacao_ibge="3550308"), _emissao())
    assert payload["city"]["code"] == "3550308"
    assert payload["location"] == {"code": "3550308"}


def test_inclui_receiver_quando_ha_documento_do_tomador():
    emissao = _emissao(tomador_cpf_cnpj="98765432100", tomador_nome="Cliente", tomador_email="c@x.com")
    payload = montar_payload_spedy(_empresa(), emissao)
    assert payload["receiver"] == {
        "federalTaxNumber": "98765432100", "name": "Cliente", "email": "c@x.com",
    }


def test_inclui_receiver_generico_quando_tomador_nao_identificado():
    # Suspeita (23/09): a SEFIN de Belem devolve SPD999 ("erro ao
    # estabelecer comunicacao com o servico") pras notas importadas da
    # planilha de vendas, que nao tem tomador -- ver
    # .claude/challenges/2026-09-16-spedy-provisionamento-divergencias-reais.md
    # pro historico de divergencias doc-vs-API ja confirmadas dessa empresa.
    payload = montar_payload_spedy(_empresa(), _emissao())
    assert payload["receiver"] == {"name": "Consumidor nao identificado"}
    assert "federalTaxNumber" not in payload["receiver"]
    assert "email" not in payload["receiver"]


def test_inclui_receiver_com_nome_mas_sem_documento_do_tomador():
    emissao = _emissao(tomador_nome="Cliente sem documento")
    payload = montar_payload_spedy(_empresa(), emissao)
    assert payload["receiver"] == {"name": "Cliente sem documento"}


def test_inclui_codigo_tributacao_municipal_quando_presente():
    payload = montar_payload_spedy(_empresa(codigo_tributacao_municipal="007"), _emissao())
    assert payload["cityServiceCode"] == "007"


def test_nao_inclui_cnae_quando_ausente():
    payload = montar_payload_spedy(_empresa(), _emissao())
    assert "cnaeCode" not in payload


def test_inclui_cnae_quando_presente():
    # Confirmado ao vivo (17/09): Belem rejeita a emissao via Spedy sem esse
    # campo (L999 "Atividade nao informada"), mesmo com federalServiceCode
    # preenchido.
    payload = montar_payload_spedy(_empresa(cnae="9601302"), _emissao())
    assert payload["cnaeCode"] == "9601302"
