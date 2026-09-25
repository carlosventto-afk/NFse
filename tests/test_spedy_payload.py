import uuid
from datetime import date
from decimal import Decimal

from app.adapters.spedy_payload import montar_payload_spedy
from app.models import Cliente, Emissao, Empresa, OrigemEmissao, StatusEmissao


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
    assert payload["federalServiceCode"] == "14.01"
    assert payload["issue"] is True
    assert "cityServiceCode" not in payload


def test_federal_service_code_usa_formato_lc116_com_ponto():
    # Doc oficial da Spedy (24/09): federalServiceCode e o "Codigo do Item
    # da Lista de Servico (LC 116/03)", formato com ponto -- nao o cTribNac
    # nacional de 6 digitos que a empresa tem cadastrado (usado no XML do
    # caminho direto). "141001" = item 14.10 (Tinturaria e lavanderia).
    payload = montar_payload_spedy(_empresa(codigo_tributacao="141001"), _emissao())
    assert payload["federalServiceCode"] == "14.10"


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


def test_nunca_inclui_receiver():
    # Removido inteiro de proposito em teste (25/09), a pedido explicito --
    # CUIDADO, contraria achado ja confirmado em 23/09 (sem receiver, Belem
    # devolvia o mesmo SPD999 que motivou este teste). Se o SPD999 nao
    # sumir, restaurar a partir do git log deste arquivo.
    emissao = _emissao(tomador_cpf_cnpj="98765432100", tomador_nome="Cliente", tomador_email="c@x.com")
    payload = montar_payload_spedy(_empresa(), emissao)
    assert "receiver" not in payload

    payload_generico = montar_payload_spedy(_empresa(), _emissao())
    assert "receiver" not in payload_generico


def test_inclui_codigo_tributacao_municipal_quando_presente():
    payload = montar_payload_spedy(_empresa(codigo_tributacao_municipal="007"), _emissao())
    assert payload["cityServiceCode"] == "007"


def test_nunca_inclui_cnae_code():
    # Removido de proposito em teste (25/09) -- uma nota autorizada de
    # 21/09 nao tinha esse campo no XML SEFIN de saida (comparacao fraca,
    # ver comentario em spedy_payload.py). Historico anterior (17/09) era
    # o oposto (Belem rejeitava com L999 sem cnaeCode) -- se voltar a dar
    # L999, restaurar este campo a partir do git blame.
    payload = montar_payload_spedy(_empresa(cnae="9601302"), _emissao())
    assert "cnaeCode" not in payload


def test_inclui_rps_number_e_series_quando_presentes():
    payload = montar_payload_spedy(_empresa(), _emissao(serie="2", numero=42))
    assert payload["rpsNumber"] == 42
    assert payload["rpsSeries"] == "2"


def test_nao_inclui_rps_number_e_series_quando_ausentes():
    payload = montar_payload_spedy(_empresa(), _emissao(serie=None, numero=None))
    assert "rpsNumber" not in payload
    assert "rpsSeries" not in payload


def test_inclui_iss_rate_quando_empresa_tem_aliquota():
    payload = montar_payload_spedy(_empresa(aliquota_iss=Decimal("2.5")), _emissao())
    assert payload["total"]["issRate"] == 2.5


def test_nao_inclui_iss_rate_quando_empresa_sem_aliquota():
    payload = montar_payload_spedy(_empresa(), _emissao())
    assert "issRate" not in payload["total"]


def test_cliente_vinculado_nao_afeta_payload_enquanto_receiver_esta_fora():
    # receiver removido em teste (25/09, ver test_nunca_inclui_receiver) --
    # o parametro cliente fica sem efeito ate o bloco voltar.
    cliente = Cliente(
        empresa_id=uuid.uuid4(), nome="Cliente", telefone="11999999999",
        cep="01310100", logradouro="Avenida Paulista", numero="1000",
        complemento="Conjunto 101", bairro="Bela Vista", municipio_ibge="3550308",
    )
    payload = montar_payload_spedy(_empresa(), _emissao(), cliente)
    assert "receiver" not in payload
