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


def _sem_pausas_reais(monkeypatch) -> None:
    """provisionar_empresa espera _INTERVALO_ENTRE_CHAMADAS_SEGUNDOS entre
    cada chamada de verdade pra Spedy (evita rajada) -- nos testes, com
    cliente falso, essa espera so deixaria a suite lenta a toa."""
    async def _sleep_falso(segundos):
        return None

    monkeypatch.setattr(provisionamento.asyncio, "sleep", _sleep_falso)


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
    _sem_pausas_reais(monkeypatch)
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
    # empresa -- os TRES passos usam a mesma chave MESTRE, um unico cliente.
    # A chave da empresa (api_key retornado) so serve pras operacoes de
    # emissao depois.
    assert chamadas[0] == ("init", "homologacao", "chave-mestre")
    assert len([c for c in chamadas if c[0] == "init"]) == 1
    assert chamadas[2][2] == b"conteudo-pfx"  # pfx decodificado de base64
    assert chamadas[2][3] == "senha123"


@pytest.mark.asyncio
async def test_provisionar_empresa_apaga_orfa_e_recria_quando_cnpj_ja_existe(monkeypatch):
    """Confirmado ao vivo em producao (16/09): uma tentativa anterior que
    falhou entre criar a empresa na Spedy e terminar o provisionamento local
    deixa uma empresa orfa la -- a proxima tentativa precisa se recuperar
    sozinha (apagar a orfa e recriar), sem exigir intervencao manual."""
    _sem_pausas_reais(monkeypatch)
    settings = _settings_teste(spedy_api_key_master_homologacao="chave-mestre")
    empresa = _empresa_para_provisionar()
    chamadas = []

    class _ClienteFalso:
        def __init__(self, ambiente, api_key):
            chamadas.append(("init", ambiente, api_key))

        async def criar_empresa(self, dados):
            chamadas.append(("criar_empresa", dados))
            if not any(c[0] == "excluir_empresa" for c in chamadas):
                raise SpedyError("O CNPJ já possui uma conta vinculada.")
            return {"id": "empresa-nova", "apiCredentials": {"apiKey": "chave-nova"}}

        async def listar_empresas_por_cnpj(self, cnpj):
            chamadas.append(("listar_empresas_por_cnpj", cnpj))
            return [{"id": "empresa-orfa", "federalTaxNumber": cnpj}]

        async def excluir_empresa(self, spedy_empresa_id):
            chamadas.append(("excluir_empresa", spedy_empresa_id))

        async def adicionar_certificado(self, spedy_empresa_id, pfx_bytes, senha):
            chamadas.append(("adicionar_certificado", spedy_empresa_id, pfx_bytes, senha))

        async def configurar_nfse(self, spedy_empresa_id, dados):
            chamadas.append(("configurar_nfse", spedy_empresa_id, dados))

        async def close(self):
            pass

    monkeypatch.setattr(provisionamento, "SpedyClient", _ClienteFalso)

    spedy_empresa_id, api_key = await provisionamento.provisionar_empresa(
        empresa, base64.b64encode(b"conteudo-pfx").decode(), "senha123", settings,
    )

    assert spedy_empresa_id == "empresa-nova"
    assert api_key == "chave-nova"
    nomes_das_chamadas = [c[0] for c in chamadas if c[0] != "init"]
    assert nomes_das_chamadas == [
        "criar_empresa", "listar_empresas_por_cnpj", "excluir_empresa",
        "criar_empresa", "adicionar_certificado", "configurar_nfse",
    ]


@pytest.mark.asyncio
async def test_provisionar_empresa_propaga_outros_erros_sem_tentar_recuperar(monkeypatch):
    """So o erro especifico de CNPJ duplicado aciona a auto-recuperacao --
    qualquer outro erro de criar_empresa precisa continuar subindo direto."""
    settings = _settings_teste(spedy_api_key_master_homologacao="chave-mestre")
    empresa = _empresa_para_provisionar()

    class _ClienteFalso:
        def __init__(self, ambiente, api_key):
            pass

        async def criar_empresa(self, dados):
            raise SpedyError("federalTaxNumber invalido")

        async def close(self):
            pass

    monkeypatch.setattr(provisionamento, "SpedyClient", _ClienteFalso)

    with pytest.raises(SpedyError, match="federalTaxNumber invalido"):
        await provisionamento.provisionar_empresa(
            empresa, base64.b64encode(b"x").decode(), "senha123", settings,
        )


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
