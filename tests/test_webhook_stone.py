import functools
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, StatusEmissao, Usuario


async def _empresa_com_token(db_session) -> Empresa:
    titular = Usuario(email=f"titular-webhook-{uuid.uuid4()}@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem de roupa",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash=hash_senha("token-secreto"), titular_id=titular.id,
    )
    db_session.add(empresa)
    await db_session.commit()
    return empresa


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_webhook_stone_cria_emissao_pendente_sem_documento_do_tomador(db_session):
    empresa = await _empresa_com_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/webhooks/stone/{empresa.id}",
                json={
                    "type": "charge.paid",
                    "id": "ch_abc123",
                    "amount": 4990,
                    "customer": {"id": "cus_1", "name": "Cliente Stone"},
                },
                headers={"X-Webhook-Token": "token-secreto"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["criado"] is True
    finally:
        app.dependency_overrides.clear()

    emissao = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalar_one()
    assert emissao.status == StatusEmissao.pendente
    assert emissao.stone_charge_id == "ch_abc123"
    assert emissao.numero == 1  # reservado na hora, sem esperar documento
    assert emissao.tomador_cpf_cnpj is None
    assert emissao.tomador_nome == "Cliente Stone"


@pytest.mark.asyncio
async def test_webhook_stone_e_idempotente(db_session):
    empresa = await _empresa_com_token(db_session)
    payload = {
        "type": "charge.paid", "id": "ch_repetido", "amount": 1000,
        "customer": {"id": "cus_2", "name": "Cliente Repetido"},
    }

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.post(
                f"/webhooks/stone/{empresa.id}", json=payload,
                headers={"X-Webhook-Token": "token-secreto"},
            )
            segunda = await client.post(
                f"/webhooks/stone/{empresa.id}", json=payload,
                headers={"X-Webhook-Token": "token-secreto"},
            )
        assert primeira.status_code == 200
        assert segunda.status_code == 200
        assert segunda.json().get("duplicado") is True
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(
            select(Emissao).where(
                Emissao.empresa_id == empresa.id, Emissao.stone_charge_id == "ch_repetido"
            )
        )
    ).scalars().all()
    assert len(total) == 1


@pytest.mark.asyncio
async def test_indice_unico_rejeita_stone_charge_id_duplicado_na_mesma_empresa(db_session):
    """Garante a idempotencia no nivel do banco, nao so na checagem da aplicacao.

    Insere duas Emissao com o mesmo (empresa_id, stone_charge_id) diretamente
    via session.add()/flush(), sem passar pelo router — contornando de
    proposito a checagem de "ja existe" que o endpoint faz antes de inserir.
    Se o indice parcial unico ix_emissoes_empresa_stone_charge_id (definido em
    app/models.py) for removido ou alterado por engano no futuro, este teste
    quebra.
    """
    empresa = await _empresa_com_token(db_session)

    primeira = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.webhook, stone_charge_id="ch_dup",
        status=StatusEmissao.pendente, serie="1", numero=1,
        descricao="Lavagem", valor=Decimal("10.00"), competencia=date.today().replace(day=1),
    )
    db_session.add(primeira)
    await db_session.flush()

    segunda = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.webhook, stone_charge_id="ch_dup",
        status=StatusEmissao.pendente, serie="1", numero=2,
        descricao="Lavagem", valor=Decimal("10.00"), competencia=date.today().replace(day=1),
    )
    db_session.add(segunda)
    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_webhook_stone_rejeita_empresa_id_nao_uuid_com_422(db_session):
    """empresa_id nao-UUID chegava cru no session.get() e virava asyncpg.DataError
    (500). Pior: isso acontecia ANTES da checagem do token, dando ao atacante um
    jeito de distinguir "UUID mal formado" de "UUID valido porem inexistente" —
    justamente o que o 404 de tempo constante evita. Tipando o path param como
    uuid.UUID, o FastAPI recusa com 422 antes de entrar no handler."""
    await _empresa_com_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/webhooks/stone/nao-e-um-uuid",
                json={"type": "charge.paid", "id": "x", "amount": 100,
                      "customer": {"id": "1", "name": "A"}},
                headers={"X-Webhook-Token": "token-secreto"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_webhook_stone_devolve_400_para_payload_malformado(db_session):
    """parse_stone_charge_paid levanta ValueError quando falta campo documentado.
    Sem tratamento, virava 500 — e a Stone REENVIA 5xx, entao um payload
    permanentemente malformado viraria retry infinito."""
    empresa = await _empresa_com_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/webhooks/stone/{empresa.id}",
                json={"type": "charge.paid", "id": "ch_sem_customer", "amount": 100},
                headers={"X-Webhook-Token": "token-secreto"},
            )
        assert resposta.status_code == 400
        assert "payload da Stone incompleto" in resposta.json()["detail"]
    finally:
        app.dependency_overrides.clear()

    nenhuma = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalars().all()
    assert nenhuma == []


@pytest.mark.asyncio
async def test_webhook_stone_trunca_nome_do_tomador_no_tamanho_da_coluna(db_session):
    """Emissao.tomador_nome e String(300): nome maior vindo da Stone causava
    StringDataRightTruncationError (500) em vez de ser aceito."""
    empresa = await _empresa_com_token(db_session)
    nome_gigante = "N" * 500

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/webhooks/stone/{empresa.id}",
                json={"type": "charge.paid", "id": "ch_nome_longo", "amount": 4990,
                      "customer": {"id": "cus_1", "name": nome_gigante}},
                headers={"X-Webhook-Token": "token-secreto"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["criado"] is True
    finally:
        app.dependency_overrides.clear()

    emissao = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalar_one()
    assert emissao.tomador_nome == "N" * 300


@pytest.mark.asyncio
async def test_webhook_stone_rejeita_token_longo_sem_estourar_500(db_session):
    """bcrypt.checkpw levanta ValueError acima de 72 bytes: um header
    X-Webhook-Token gigante virava 500 (e um oraculo para descobrir empresas
    existentes). Precisa cair no mesmo 404 de token errado."""
    empresa = await _empresa_com_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/webhooks/stone/{empresa.id}",
                json={"type": "charge.paid", "id": "x", "amount": 100,
                      "customer": {"id": "1", "name": "A"}},
                headers={"X-Webhook-Token": "T" * 200},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_webhook_stone_rejeita_token_errado(db_session):
    empresa = await _empresa_com_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/webhooks/stone/{empresa.id}",
                json={"type": "charge.paid", "id": "x", "amount": 100, "customer": {"id": "1", "name": "A"}},
                headers={"X-Webhook-Token": "token-errado"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()
