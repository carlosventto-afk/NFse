import functools
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.crypto import hash_senha, verificar_senha
from app.db import get_db
from app.main import app
from app.models import Convite, PapelUsuario, Plano, Usuario, UsuarioEmpresa
from app.security import criar_token
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_admin_plataforma_convida_titular_e_convite_e_criado(db_session, monkeypatch):
    import app.routers.convites as modulo

    enviados = []

    async def _enviar_falso(destinatario, link):
        enviados.append((destinatario, link))

    monkeypatch.setattr(modulo, "enviar_convite", _enviar_falso)

    adm = Usuario(email="adm@plataforma.com", senha_hash=hash_senha("senha-forte-123"), eh_admin_plataforma=True)
    db_session.add(adm)
    await db_session.flush()
    plano = Plano(nome="Basico", limite_empresas=2)
    db_session.add(plano)
    await db_session.commit()
    await db_session.refresh(adm)
    token = criar_token(adm)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites",
                json={"email": "titular@teste.com", "plano_id": str(plano.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["empresa_id"] is None
    finally:
        app.dependency_overrides.clear()

    assert len(enviados) == 1
    assert enviados[0][0] == "titular@teste.com"


@pytest.mark.asyncio
async def test_aceitar_convite_de_titular_cria_usuario_com_plano_sem_vinculo_de_empresa(db_session, monkeypatch):
    adm = Usuario(email="adm2@plataforma.com", senha_hash=hash_senha("senha-forte-123"), eh_admin_plataforma=True)
    db_session.add(adm)
    await db_session.flush()
    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.commit()
    convite = Convite(
        email="futuro-titular@teste.com", plano_id=plano.id,
        token="token-titular-123", expira_em=datetime.now(timezone.utc) + timedelta(days=7),
        criado_por_usuario_id=adm.id,
    )
    db_session.add(convite)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites/aceitar", json={"token": "token-titular-123", "senha": "senha-nova-123"}
            )
        assert resposta.status_code == 200
    finally:
        app.dependency_overrides.clear()

    novo_titular = (
        await db_session.execute(select(Usuario).where(Usuario.email == "futuro-titular@teste.com"))
    ).scalar_one()
    assert novo_titular.plano_id == plano.id
    vinculos = (
        await db_session.execute(select(UsuarioEmpresa).where(UsuarioEmpresa.usuario_id == novo_titular.id))
    ).scalars().all()
    assert vinculos == []


@pytest.mark.asyncio
async def test_admin_de_empresa_convida_operador_para_a_empresa_ativa(db_session, monkeypatch):
    import app.routers.convites as modulo

    async def _enviar_falso(destinatario, link):
        return None

    monkeypatch.setattr(modulo, "enviar_convite", _enviar_falso)

    empresa, titular = await criar_empresa_titular(db_session, email_titular="dono@teste.com")
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites",
                json={"email": "operador@teste.com", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["empresa_id"] == str(empresa.id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_operador_nao_pode_convidar(db_session):
    from tests.apoio import criar_empresa_e_token

    _empresa, token = await criar_empresa_e_token(
        db_session, papel=PapelUsuario.operador, email="operador2@teste.com", cnpj="55555555000155",
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites",
                json={"email": "x@teste.com", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_aceitar_convite_de_email_novo_cria_usuario_e_vinculo(db_session, monkeypatch):
    empresa, titular = await criar_empresa_titular(db_session, email_titular="convidante@teste.com")
    convite = Convite(
        email="novato@teste.com", empresa_id=empresa.id, papel=PapelUsuario.operador,
        token="token-de-teste-123", expira_em=datetime.now(timezone.utc) + timedelta(days=7),
        criado_por_usuario_id=titular.id,
    )
    db_session.add(convite)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites/aceitar",
                json={"token": "token-de-teste-123", "senha": "senha-nova-123"},
            )
        assert resposta.status_code == 200
    finally:
        app.dependency_overrides.clear()

    novo = (
        await db_session.execute(select(Usuario).where(Usuario.email == "novato@teste.com"))
    ).scalar_one()
    assert verificar_senha("senha-nova-123", novo.senha_hash)
    vinculo = (
        await db_session.execute(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == novo.id, UsuarioEmpresa.empresa_id == empresa.id,
            )
        )
    ).scalar_one()
    assert vinculo.papel == PapelUsuario.operador
    await db_session.refresh(convite)
    assert convite.aceito_em is not None


@pytest.mark.asyncio
async def test_aceitar_convite_de_usuario_existente_nao_pede_senha(db_session):
    empresa_a, titular = await criar_empresa_titular(db_session, email_titular="convidante2@teste.com")
    empresa_b, _outro = await criar_empresa_titular(
        db_session, cnpj="66666666000166", email_titular="dono-b@teste.com",
    )
    convite = Convite(
        email="titular@teste.com", empresa_id=empresa_b.id, papel=PapelUsuario.operador,
        token="token-existente-123", expira_em=datetime.now(timezone.utc) + timedelta(days=7),
        criado_por_usuario_id=titular.id,
    )
    ja_existente = Usuario(email="titular@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(ja_existente)
    db_session.add(convite)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post("/convites/aceitar", json={"token": "token-existente-123"})
        assert resposta.status_code == 200
    finally:
        app.dependency_overrides.clear()

    vinculo = (
        await db_session.execute(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == ja_existente.id, UsuarioEmpresa.empresa_id == empresa_b.id,
            )
        )
    ).scalar_one()
    assert vinculo.papel == PapelUsuario.operador


@pytest.mark.asyncio
async def test_aceitar_convite_expirado_devolve_400(db_session):
    empresa, titular = await criar_empresa_titular(db_session, email_titular="convidante3@teste.com")
    convite = Convite(
        email="tarde@teste.com", empresa_id=empresa.id, papel=PapelUsuario.operador,
        token="token-expirado-123", expira_em=datetime.now(timezone.utc) - timedelta(days=1),
        criado_por_usuario_id=titular.id,
    )
    db_session.add(convite)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/convites/aceitar", json={"token": "token-expirado-123", "senha": "senha-nova-123"}
            )
        assert resposta.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_novo_convite_para_o_mesmo_email_invalida_o_anterior(db_session, monkeypatch):
    import app.routers.convites as modulo

    async def _enviar_falso(destinatario, link):
        return None

    monkeypatch.setattr(modulo, "enviar_convite", _enviar_falso)

    empresa, titular = await criar_empresa_titular(db_session, email_titular="repete@teste.com")
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeiro = await client.post(
                "/convites", json={"email": "x@teste.com", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
            await client.post(
                "/convites", json={"email": "x@teste.com", "papel": "admin"},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.clear()

    convite_antigo = await db_session.get(Convite, primeiro.json()["id"])
    assert convite_antigo.expira_em <= datetime.now(timezone.utc)
