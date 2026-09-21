from datetime import datetime, timezone

from app.adapters.spedy_provisionamento import montar_dados_regime_tributario
from app.models import AmbienteEnum, Empresa


def _empresa(**overrides) -> Empresa:
    dados = dict(
        cnpj="12345678000199", municipio_ibge="1501402", op_simp_nac=3, regime_apuracao_sn=None,
        codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao,
        certificado_pfx_cifrado="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    dados.update(overrides)
    return Empresa(**dados)


def test_nao_optante_vira_regime_normal_sem_regime_especial():
    dados = montar_dados_regime_tributario(_empresa(op_simp_nac=1))
    assert dados == {"taxRegime": "regimeNormal", "specialTaxRegime": "noSpecialRegime"}


def test_optante_mei_vira_taxregime_mei():
    dados = montar_dados_regime_tributario(_empresa(op_simp_nac=2))
    assert dados == {"taxRegime": "simplesNacionalMEI", "specialTaxRegime": "individualMicroenterprise"}


def test_optante_me_epp_vira_simples_nacional_me_epp():
    # Confirmado ao vivo (Belem, erro E188): sem esses dois campos no
    # cadastro da empresa na Spedy, o regime especial (05-MEI ou 06-ME/EPP)
    # que a prefeitura assume por conta propria conflita com a ausencia de
    # "optante pelo Simples = SIM" do nosso lado.
    dados = montar_dados_regime_tributario(_empresa(op_simp_nac=3, regime_apuracao_sn=None))
    assert dados == {"taxRegime": "simplesNacional", "specialTaxRegime": "microenterpriseAndSmallBusiness"}


def test_optante_me_epp_inclui_regime_de_apuracao_quando_informado():
    dados = montar_dados_regime_tributario(_empresa(op_simp_nac=3, regime_apuracao_sn=2))
    assert dados["simplesNacionalTaxRegime"] == "federalBySimplesAndIssqnByNfse"
