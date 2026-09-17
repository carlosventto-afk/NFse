import functools

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import PapelUsuario, Usuario, UsuarioEmpresa
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


@pytest.mark.asyncio
async def test_admin_plataforma_entra_em_empresa_sem_vinculo_previo(db_session):
    empresa_alheia, _titular = await criar_empresa_titular(
        db_session, cnpj="44444444000144", email_titular="dono-alheio@teste.com",
    )
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/auth/trocar-empresa",
                json={"empresa_id": str(empresa_alheia.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        from jose import jwt

        from app.config import get_settings

        payload = jwt.decode(resposta.json()["access_token"], get_settings().jwt_secret, algorithms=["HS256"])
        assert payload["empresa_id"] == str(empresa_alheia.id)
        assert payload["papel"] == "admin"
    finally:
        app.dependency_overrides.clear()

    vinculo = (
        await db_session.execute(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == admin.id, UsuarioEmpresa.empresa_id == empresa_alheia.id,
            )
        )
    ).scalar_one()
    assert vinculo.papel == PapelUsuario.admin


@pytest.mark.asyncio
async def test_admin_plataforma_entrar_em_empresa_inexistente_devolve_404(db_session):
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/auth/trocar-empresa",
                json={"empresa_id": "00000000-0000-0000-0000-000000000000"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_plataforma_lista_todas_as_empresas(db_session):
    empresa_a, _ = await criar_empresa_titular(
        db_session, cnpj="55555555000155", email_titular="dono-a@teste.com",
    )
    empresa_b, _ = await criar_empresa_titular(
        db_session, cnpj="66666666000166", email_titular="dono-b@teste.com",
    )
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/empresas", headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        cnpjs = {item["cnpj"] for item in resposta.json()}
        assert {empresa_a.cnpj, empresa_b.cnpj}.issubset(cnpjs)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_usuario_comum_nao_lista_todas_as_empresas(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/empresas", headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_plataforma_lista_planos(db_session):
    from app.models import Plano

    plano = Plano(nome="Padrao", limite_empresas=5)
    db_session.add(plano)
    await db_session.commit()
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/planos", headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        nomes = {item["nome"] for item in resposta.json()}
        assert "Padrao" in nomes
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_usuario_comum_nao_lista_planos(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/planos", headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_plataforma_vincula_usuario_existente_a_empresa(db_session):
    empresa, _titular = await criar_empresa_titular(
        db_session, cnpj="77777777000177", email_titular="dono-c@teste.com",
    )
    usuario_solto = Usuario(email="solto@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(usuario_solto)
    await db_session.commit()
    await db_session.refresh(usuario_solto)
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/empresas/{empresa.id}/vincular-usuario",
                json={"email": "solto@teste.com", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 204
    finally:
        app.dependency_overrides.clear()

    vinculo = (
        await db_session.execute(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == usuario_solto.id, UsuarioEmpresa.empresa_id == empresa.id,
            )
        )
    ).scalar_one()
    assert vinculo.papel == PapelUsuario.operador


@pytest.mark.asyncio
async def test_vincular_usuario_inexistente_devolve_404(db_session):
    empresa, _titular = await criar_empresa_titular(
        db_session, cnpj="88888888000188", email_titular="dono-d@teste.com",
    )
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/empresas/{empresa.id}/vincular-usuario",
                json={"email": "nao-existe@teste.com", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_vincular_a_empresa_inexistente_devolve_404(db_session):
    usuario_solto = Usuario(email="solto2@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(usuario_solto)
    await db_session.commit()
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/empresas/00000000-0000-0000-0000-000000000000/vincular-usuario",
                json={"email": "solto2@teste.com", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_vincular_usuario_ja_vinculado_devolve_409(db_session):
    empresa, titular = await criar_empresa_titular(
        db_session, cnpj="99999999000199", email_titular="dono-e@teste.com",
    )
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/empresas/{empresa.id}/vincular-usuario",
                json={"email": "dono-e@teste.com", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_vincular_usuario_com_papel_invalido_devolve_422(db_session):
    empresa, _titular = await criar_empresa_titular(
        db_session, cnpj="10101010000110", email_titular="dono-f@teste.com",
    )
    admin = await _criar_admin_plataforma(db_session)
    token = criar_token(admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/empresas/{empresa.id}/vincular-usuario",
                json={"email": "dono-f@teste.com", "papel": "supervisor"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_usuario_comum_nao_pode_vincular(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/empresas/{empresa.id}/vincular-usuario",
                json={"email": "qualquer@teste.com", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()
