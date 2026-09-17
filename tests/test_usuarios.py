import functools

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.crypto import hash_senha, verificar_senha
from app.db import get_db
from app.main import app
from app.models import PapelUsuario, Plano, Usuario
from app.security import criar_token
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


async def _criar_admin_plataforma(db_session, email: str = "admin-plataforma@teste.com") -> Usuario:
    usuario = Usuario(email=email, senha_hash=hash_senha("senha-forte-123"), eh_admin_plataforma=True)
    db_session.add(usuario)
    await db_session.commit()
    await db_session.refresh(usuario)
    return usuario


async def _criar_plano(db_session, *, nome: str = "Padrao", limite_empresas: int = 5) -> Plano:
    plano = Plano(nome=nome, limite_empresas=limite_empresas)
    db_session.add(plano)
    await db_session.commit()
    await db_session.refresh(plano)
    return plano


@pytest.mark.asyncio
async def test_admin_plataforma_cria_usuario_diretamente(db_session):
    plano = await _criar_plano(db_session)
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/usuarios",
                json={"email": "novo-titular@teste.com", "senha": "senha-nova-123", "plano_id": str(plano.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["email"] == "novo-titular@teste.com"
    finally:
        app.dependency_overrides.clear()

    usuario = (
        await db_session.execute(select(Usuario).where(Usuario.email == "novo-titular@teste.com"))
    ).scalar_one()
    assert usuario.plano_id == plano.id
    assert verificar_senha("senha-nova-123", usuario.senha_hash)


@pytest.mark.asyncio
async def test_criar_usuario_com_email_ja_usado_devolve_409(db_session):
    plano = await _criar_plano(db_session)
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)
    await criar_empresa_titular(db_session, email_titular="ja-existe@teste.com")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/usuarios",
                json={"email": "ja-existe@teste.com", "senha": "senha-nova-123", "plano_id": str(plano.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_criar_usuario_com_senha_curta_devolve_422(db_session):
    plano = await _criar_plano(db_session)
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/usuarios",
                json={"email": "curta@teste.com", "senha": "123", "plano_id": str(plano.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_usuario_comum_nao_pode_criar_usuario(db_session):
    plano = await _criar_plano(db_session)
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/usuarios",
                json={"email": "x@teste.com", "senha": "senha-nova-123", "plano_id": str(plano.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()
