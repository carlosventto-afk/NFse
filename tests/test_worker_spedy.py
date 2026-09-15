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
