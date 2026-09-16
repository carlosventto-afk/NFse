import base64
from datetime import datetime, timezone

import pytest

from app.adapters.spedy_client import SpedyError
import app.adapters.spedy_provisionamento as provisionamento
from app.config import Settings
from app.models import AmbienteEnum, Empresa


def _settings_teste(**overrides) -> Settings:
    """Instancia nova (nao o singleton cacheado de get_settings()) -- evita
    contaminar outros testes com a chave mestre setada aqui."""
    dados = {"spedy_api_key_master_homologacao": "", "spedy_api_key_master_producao": ""}
    dados.update(overrides)
    return Settings(**dados)


def _empresa_para_provisionar(**overrides) -> Empresa:
    dados = dict(
        cnpj="12345678000199", municipio_ibge="1501402", op_simp_nac=3,
        codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, razao_social="EMPRESA TESTE LTDA",
        serie="1", proximo_numero=1,
        certificado_pfx_cifrado="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    dados.update(overrides)
    return Empresa(**dados)


@pytest.mark.asyncio
async def test_provisionar_empresa_chama_os_tres_passos_na_ordem(monkeypatch):
    settings = _settings_teste(spedy_api_key_master_homologacao="chave-mestre")
    empresa = _empresa_para_provisionar()
    chamadas = []

    class _ClienteFalso:
        def __init__(self, ambiente, api_key):
            chamadas.append(("init", ambiente, api_key))

        async def criar_empresa(self, dados):
            chamadas.append(("criar_empresa", dados))
            return {"id": "empresa-1", "apiCredentials": {"apiKey": "chave-empresa"}}

        async def adicionar_certificado(self, spedy_empresa_id, pfx_bytes, senha):
            chamadas.append(("adicionar_certificado", spedy_empresa_id, pfx_bytes, senha))
            return {"id": "cert-1"}

        async def configurar_nfse(self, spedy_empresa_id, dados):
            chamadas.append(("configurar_nfse", spedy_empresa_id, dados))
            return {}

        async def close(self):
            pass

    monkeypatch.setattr(provisionamento, "SpedyClient", _ClienteFalso)

    spedy_empresa_id, api_key = await provisionamento.provisionar_empresa(
        empresa, base64.b64encode(b"conteudo-pfx").decode(), "senha123", settings,
    )

    assert spedy_empresa_id == "empresa-1"
    assert api_key == "chave-empresa"
    nomes_das_chamadas = [c[0] for c in chamadas if c[0] != "init"]
    assert nomes_das_chamadas == ["criar_empresa", "adicionar_certificado", "configurar_nfse"]
    # Confirmado ao vivo em producao (16/09): adicionar_certificado e
    # configurar_nfse devolvem 403 "Acesso nao autorizado" com a chave da
    # empresa -- os TRES passos usam a chave MESTRE. A chave da empresa
    # (api_key retornado) so serve pras operacoes de emissao depois.
    assert chamadas[0] == ("init", "homologacao", "chave-mestre")
    assert chamadas[2] == ("init", "homologacao", "chave-mestre")
    assert chamadas[3][2] == b"conteudo-pfx"  # pfx decodificado de base64
    assert chamadas[3][3] == "senha123"


@pytest.mark.asyncio
async def test_provisionar_empresa_sem_chave_mestre_configurada_levanta_erro_claro(monkeypatch):
    settings = _settings_teste()
    empresa = _empresa_para_provisionar()

    with pytest.raises(SpedyError, match="chave mestre"):
        await provisionamento.provisionar_empresa(empresa, base64.b64encode(b"x").decode(), None, settings)


@pytest.mark.asyncio
async def test_provisionar_empresa_sem_razao_social_levanta_erro_claro(monkeypatch):
    settings = _settings_teste(spedy_api_key_master_homologacao="chave-mestre")
    empresa = _empresa_para_provisionar(razao_social=None)

    with pytest.raises(SpedyError, match="razao_social"):
        await provisionamento.provisionar_empresa(empresa, base64.b64encode(b"x").decode(), "senha123", settings)
