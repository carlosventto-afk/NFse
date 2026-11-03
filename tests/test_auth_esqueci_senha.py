import functools
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.crypto import hash_senha, verificar_senha
from app.db import get_db
from app.main import app
from app.models import RedefinicaoSenha, Usuario
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_esqueci_senha_de_email_existente_cria_token_e_envia_email(db_session, monkeypatch):
    import app.routers.auth as modulo

    enviados = []

    async def _enviar_falso(destinatario, link):
        enviados.append((destinatario, link))

    monkeypatch.setattr(modulo, "enviar_redefinicao_senha", _enviar_falso)

    _empresa, titular = await criar_empresa_titular(db_session, email_titular="recupera@teste.com")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post("/api/auth/esqueci-senha", json={"email": "recupera@teste.com"})
        assert resposta.status_code == 204
    finally:
        app.dependency_overrides.clear()

    assert len(enviados) == 1
    assert enviados[0][0] == "recupera@teste.com"
    assert "token=" in enviados[0][1]

    redefinicao = (
        await db_session.execute(
            select(RedefinicaoSenha).where(RedefinicaoSenha.usuario_id == titular.id)
        )
    ).scalar_one()
    assert redefinicao.usado_em is None


@pytest.mark.asyncio
async def test_esqueci_senha_de_email_inexistente_tambem_devolve_204_sem_enviar_email(db_session, monkeypatch):
    import app.routers.auth as modulo

    enviados = []

    async def _enviar_falso(destinatario, link):
        enviados.append((destinatario, link))

    monkeypatch.setattr(modulo, "enviar_redefinicao_senha", _enviar_falso)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post("/api/auth/esqueci-senha", json={"email": "nao-existe@teste.com"})
        assert resposta.status_code == 204
    finally:
        app.dependency_overrides.clear()

    assert enviados == []


@pytest.mark.asyncio
async def test_redefinir_senha_com_token_valido_troca_a_senha_e_permite_login(db_session):
    _empresa, titular = await criar_empresa_titular(db_session, email_titular="trocasenha@teste.com")
    redefinicao = RedefinicaoSenha(
        usuario_id=titular.id, token="token-redefinicao-123",
        expira_em=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(redefinicao)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/auth/redefinir-senha",
                json={"token": "token-redefinicao-123", "nova_senha": "senha-novissima-123"},
            )
            assert resposta.status_code == 204
            login = await client.post(
                "/api/auth/login",
                data={"username": "trocasenha@teste.com", "password": "senha-novissima-123"},
            )
    finally:
        app.dependency_overrides.clear()

    assert login.status_code == 200
    await db_session.refresh(titular)
    assert verificar_senha("senha-novissima-123", titular.senha_hash)
    await db_session.refresh(redefinicao)
    assert redefinicao.usado_em is not None


@pytest.mark.asyncio
async def test_redefinir_senha_com_token_usado_devolve_400(db_session):
    _empresa, titular = await criar_empresa_titular(db_session, email_titular="reusotoken@teste.com")
    redefinicao = RedefinicaoSenha(
        usuario_id=titular.id, token="token-ja-usado-123",
        expira_em=datetime.now(timezone.utc) + timedelta(hours=1),
        usado_em=datetime.now(timezone.utc),
    )
    db_session.add(redefinicao)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/auth/redefinir-senha",
                json={"token": "token-ja-usado-123", "nova_senha": "outra-senha-123"},
            )
        assert resposta.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_redefinir_senha_com_token_expirado_devolve_400(db_session):
    _empresa, titular = await criar_empresa_titular(db_session, email_titular="tokenexpirado@teste.com")
    redefinicao = RedefinicaoSenha(
        usuario_id=titular.id, token="token-vencido-123",
        expira_em=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(redefinicao)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/auth/redefinir-senha",
                json={"token": "token-vencido-123", "nova_senha": "outra-senha-123"},
            )
        assert resposta.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_redefinir_senha_com_token_inexistente_devolve_400(db_session):
    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/auth/redefinir-senha",
                json={"token": "token-nunca-existiu", "nova_senha": "outra-senha-123"},
            )
        assert resposta.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_pedido_novo_de_esqueci_senha_invalida_token_anterior(db_session, monkeypatch):
    import app.routers.auth as modulo

    async def _enviar_falso(destinatario, link):
        return None

    monkeypatch.setattr(modulo, "enviar_redefinicao_senha", _enviar_falso)

    _empresa, titular = await criar_empresa_titular(db_session, email_titular="duplopedido@teste.com")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post("/api/auth/esqueci-senha", json={"email": "duplopedido@teste.com"})
            await client.post("/api/auth/esqueci-senha", json={"email": "duplopedido@teste.com"})
    finally:
        app.dependency_overrides.clear()

    tokens = (
        await db_session.execute(
            select(RedefinicaoSenha).where(RedefinicaoSenha.usuario_id == titular.id)
        )
    ).scalars().all()
    assert len(tokens) == 2
    antigo, novo = sorted(tokens, key=lambda t: t.criado_em)
    assert antigo.expira_em <= datetime.now(timezone.utc)
    assert novo.expira_em > datetime.now(timezone.utc)
