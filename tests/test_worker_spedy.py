import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.config import get_settings
from app.crypto import cifrar, hash_senha
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, ProvedorEmissao, StatusEmissao, Usuario
from app.adapters.spedy_client import SpedyError
import app.worker as worker


async def _empresa_spedy_e_emissao_pendente(db_session, **overrides_empresa) -> Emissao:
    fernet_key = get_settings().fernet_key
    titular = Usuario(email=f"titular-spedy-{uuid.uuid4()}@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    dados = dict(
        cnpj="12345678000199", municipio_ibge="1501402", op_simp_nac=3,
        codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, provedor_emissao=ProvedorEmissao.spedy,
        spedy_empresa_id="spedy-empresa-1",
        spedy_api_key_cifrada=cifrar("spedy-chave-1", fernet_key),
        certificado_pfx_cifrado="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular.id,
    )
    dados.update(overrides_empresa)
    empresa = Empresa(**dados)
    db_session.add(empresa)
    await db_session.flush()
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, tomador_cpf_cnpj="98765432100", tomador_nome="Cliente",
        descricao="Lavagem de roupa", valor=Decimal("49.90"), competencia=date(2026, 9, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    return emissao


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_aceita_e_fica_aguardando_confirmacao(db_session, monkeypatch):
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            assert payload["integrationId"] == str(emissao.id)
            return {"_http_status": 200, "id": "nota-spedy-1", "status": "enqueued"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.aguardando_confirmacao
    assert emissao.spedy_nota_id == "nota-spedy-1"


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_rejeicao_sincrona(db_session, monkeypatch):
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            return {
                "_http_status": 400,
                "processingDetail": {"message": "CNPJ do tomador invalido"},
            }

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert "CNPJ do tomador invalido" in erros[0]["titulo"]
    assert emissao.resposta_bruta is not None


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_falha_de_transporte(db_session, monkeypatch):
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def emitir_nfse(self, payload):
            raise SpedyError("falha de rede com a Spedy (ConnectTimeout)")

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "TRANSPORTE"


@pytest.mark.asyncio
async def test_processar_uma_pendente_via_spedy_sem_provisionamento_marca_rejeitada(db_session):
    emissao = await _empresa_spedy_e_emissao_pendente(
        db_session, spedy_empresa_id=None, spedy_api_key_cifrada=None,
    )

    processou = await worker.processar_uma_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "SPEDY_NAO_PROVISIONADA"


async def _emissao_aguardando_confirmacao(db_session) -> Emissao:
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)
    emissao.status = StatusEmissao.aguardando_confirmacao
    emissao.spedy_nota_id = "nota-spedy-1"
    await db_session.commit()
    return emissao


@pytest.mark.asyncio
async def test_confirmacao_spedy_marca_autorizada(db_session, monkeypatch):
    emissao = await _emissao_aguardando_confirmacao(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            assert spedy_nota_id == "nota-spedy-1"
            return {"_http_status": 200, "status": "authorized", "accessKey": "chave-final-1"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.autorizada
    assert emissao.chave_acesso == "chave-final-1"


@pytest.mark.asyncio
async def test_confirmacao_spedy_marca_rejeitada(db_session, monkeypatch):
    emissao = await _emissao_aguardando_confirmacao(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {
                "_http_status": 200, "status": "rejected",
                "processingDetail": {"code": "SPD123", "message": "servico invalido"},
            }

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.rejeitada
    erros = json.loads(emissao.erros)
    assert erros[0]["codigo"] == "SPD123"


@pytest.mark.asyncio
async def test_confirmacao_spedy_ainda_processando_nao_conta_como_trabalho(db_session, monkeypatch):
    emissao = await _emissao_aguardando_confirmacao(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 200, "status": "enqueued"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)

    assert processou is False
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.aguardando_confirmacao


@pytest.mark.asyncio
async def test_processar_uma_aguardando_confirmacao_spedy_devolve_falso_quando_fila_vazia(db_session):
    processou = await worker.processar_uma_aguardando_confirmacao_spedy(db_session)
    assert processou is False


async def _emissao_cancelamento_pendente_spedy(db_session) -> Emissao:
    emissao = await _empresa_spedy_e_emissao_pendente(db_session)
    emissao.status = StatusEmissao.cancelamento_pendente
    emissao.chave_acesso = "chave-final-1"
    emissao.spedy_nota_id = "nota-spedy-1"
    emissao.motivo_cancelamento = "Servico nao prestado"
    await db_session.commit()
    return emissao


@pytest.mark.asyncio
async def test_cancelamento_pendente_via_spedy_fica_aguardando_confirmacao(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def cancelar_nfse(self, spedy_nota_id, motivo):
            assert spedy_nota_id == "nota-spedy-1"
            assert motivo == "Servico nao prestado"
            return {"_http_status": 200, "status": "canceling"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelamento_aguardando_confirmacao


@pytest.mark.asyncio
async def test_cancelamento_pendente_via_spedy_rejeicao_sincrona(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def cancelar_nfse(self, spedy_nota_id, motivo):
            return {
                "_http_status": 400,
                "errors": [{"message": "A nota fiscal não pode ser cancelada."}],
            }

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.erro_cancelamento
    erros = json.loads(emissao.erros)
    assert "não pode ser cancelada" in erros[0]["titulo"]


@pytest.mark.asyncio
async def test_cancelamento_pendente_via_spedy_falha_de_transporte(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def cancelar_nfse(self, spedy_nota_id, motivo):
            raise SpedyError("falha de rede")

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_pendente(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.erro_cancelamento


@pytest.mark.asyncio
async def test_confirmacao_cancelamento_spedy_marca_cancelada(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)
    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    await db_session.commit()

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 200, "status": "canceled"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_aguardando_confirmacao_spedy(db_session)

    assert processou is True
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelada
    assert emissao.cancelada_em is not None


@pytest.mark.asyncio
async def test_confirmacao_cancelamento_spedy_ainda_processando_nao_conta_como_trabalho(db_session, monkeypatch):
    emissao = await _emissao_cancelamento_pendente_spedy(db_session)
    emissao.status = StatusEmissao.cancelamento_aguardando_confirmacao
    await db_session.commit()

    class ClienteFalso:
        def __init__(self, *args, **kwargs):
            pass

        async def consultar_nfse(self, spedy_nota_id):
            return {"_http_status": 200, "status": "canceling"}

        async def close(self):
            pass

    monkeypatch.setattr(worker, "SpedyClient", ClienteFalso)

    processou = await worker.processar_um_cancelamento_aguardando_confirmacao_spedy(db_session)

    assert processou is False
    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelamento_aguardando_confirmacao
