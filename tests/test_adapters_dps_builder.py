from datetime import date, datetime, timezone
from decimal import Decimal

from app.adapters.dps_builder import DadosEmissao, montar_dps_data
from app.models import AmbienteEnum, Empresa


def _empresa() -> Empresa:
    return Empresa(
        cnpj="12345678000199", inscricao_municipal="123456", municipio_ibge="1501402",
        op_simp_nac=3, codigo_tributacao="141001", descricao_servico_padrao="Lavagem de roupa",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )


def test_montar_dps_data_mapeia_empresa_e_dados_corretamente():
    dados = DadosEmissao(
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente Teste",
        tomador_email="cliente@teste.com", descricao="Lavagem de 5kg de roupa",
        valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )

    dps_data = montar_dps_data(_empresa(), serie="1", numero=42, dados=dados)

    assert dps_data.tp_amb == 2  # homologacao
    assert dps_data.serie == "1"
    assert dps_data.numero == 42
    assert dps_data.prest_cnpj == "12345678000199"
    assert dps_data.prest_im == "123456"
    assert dps_data.c_loc_emi == "1501402"
    # sem local_prestacao_ibge configurado, cai no municipio emissor (default do nfse_core)
    assert dps_data.c_loc_prestacao == ""
    assert dps_data.op_simp_nac == 3
    assert dps_data.toma_cpf_cnpj == "98765432100"
    assert dps_data.toma_nome == "Cliente Teste"
    assert dps_data.c_trib_nac == "141001"
    assert dps_data.x_desc_serv == "Lavagem de 5kg de roupa"
    assert dps_data.v_serv == Decimal("49.90")


def test_montar_dps_data_producao_usa_tp_amb_1():
    empresa = _empresa()
    empresa.ambiente = AmbienteEnum.producao
    dados = DadosEmissao(
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente Teste", tomador_email=None,
        descricao="Lavagem", valor=Decimal("10.00"), competencia=date(2026, 8, 1),
    )

    dps_data = montar_dps_data(empresa, serie="1", numero=1, dados=dados)

    assert dps_data.tp_amb == 1


def test_montar_dps_data_sem_inscricao_municipal_passa_none_adiante():
    # Alguns municipios (sem cadastro complementar no CNC NFS-e) rejeitam a
    # DPS se a IM vier preenchida (SEFIN E0120) -- empresa sem IM cadastrada
    # precisa gerar prest_im=None, nao string vazia nem erro.
    empresa = _empresa()
    empresa.inscricao_municipal = None
    dados = DadosEmissao(
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente Teste", tomador_email=None,
        descricao="Lavagem", valor=Decimal("10.00"), competencia=date(2026, 8, 1),
    )

    dps_data = montar_dps_data(empresa, serie="1", numero=1, dados=dados)

    assert dps_data.prest_im is None


def test_montar_dps_data_usa_local_prestacao_quando_diferente_do_emissor():
    empresa = _empresa()
    empresa.local_prestacao_ibge = "3304557"
    dados = DadosEmissao(
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente Teste", tomador_email=None,
        descricao="Lavagem", valor=Decimal("10.00"), competencia=date(2026, 8, 1),
    )

    dps_data = montar_dps_data(empresa, serie="1", numero=1, dados=dados)

    assert dps_data.c_loc_emi == "1501402"
    assert dps_data.c_loc_prestacao == "3304557"


def test_montar_dps_data_sem_documento_do_tomador_passa_none_adiante():
    dados = DadosEmissao(
        tomador_cpf_cnpj=None, tomador_nome="Cliente Sem Documento", tomador_email=None,
        descricao="Lavagem", valor=Decimal("15.00"), competencia=date(2026, 8, 1),
    )

    dps_data = montar_dps_data(_empresa(), serie="1", numero=2, dados=dados)

    assert dps_data.toma_cpf_cnpj is None
    assert dps_data.toma_nome == "Cliente Sem Documento"
