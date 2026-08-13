import functools

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models import PapelUsuario
from app.security import criar_token
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_login_com_uma_empresa_so_ja_sai_com_empresa_ativa(db_session):
    empresa, titular = await criar_empresa_titular(db_session, email_titular="unica@teste.com")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/auth/login", data={"username": "unica@teste.com", "password": "senha-forte-123"}
            )
            assert resposta.status_code == 200
            empresas = await client.get(
                "/api/auth/empresas",
                headers={"Authorization": f"Bearer {resposta.json()['access_token']}"},
            )
    finally:
        app.dependency_overrides.clear()

    # o token ja sai com empresa ativa: qualquer endpoint de negocio ja funciona
    # sem precisar de POST /auth/trocar-empresa antes
    assert empresas.status_code == 200


@pytest.mark.asyncio
async def test_login_com_senha_errada_devolve_401(db_session):
    await criar_empresa_titular(db_session, email_titular="admin2@teste.com")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/auth/login", data={"username": "admin2@teste.com", "password": "errada"}
            )
        assert resposta.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_com_senha_absurdamente_longa_devolve_401_e_nao_500(db_session):
    """bcrypt.checkpw levanta ValueError acima de 72 bytes: sem o guarda em
    `verificar_senha`, uma senha gigante no login virava 500."""
    await criar_empresa_titular(db_session, email_titular="admin5@teste.com")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/auth/login", data={"username": "admin5@teste.com", "password": "x" * 500}
            )
        assert resposta.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_com_duas_empresas_nao_sai_com_empresa_ativa_ate_trocar(db_session):
    empresa_a, titular = await criar_empresa_titular(
        db_session, cnpj="11111111000111", email_titular="multi@teste.com",
    )
    from app.models import Empresa, UsuarioEmpresa

    empresa_b = Empresa(
        cnpj="22222222000122", inscricao_municipal="2", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem B",
        ambiente=empresa_a.ambiente, certificado_pfx_cifrado="x", certificado_senha_cifrada="x",
        certificado_valido_ate=empresa_a.certificado_valido_ate, webhook_token_hash="x",
        titular_id=titular.id,
    )
    db_session.add(empresa_b)
    await db_session.flush()
    db_session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa_b.id, papel=PapelUsuario.admin))
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
                "/api/auth/login", data={"username": "multi@teste.com", "password": "senha-forte-123"}
            )
            token_sem_empresa = login.json()["access_token"]

            listagem = await client.get(
                "/api/auth/empresas", headers={"Authorization": f"Bearer {token_sem_empresa}"}
            )
            assert {item["empresa_id"] for item in listagem.json()} == {
                str(empresa_a.id), str(empresa_b.id),
            }

            troca = await client.post(
                "/api/auth/trocar-empresa",
                json={"empresa_id": str(empresa_b.id)},
                headers={"Authorization": f"Bearer {token_sem_empresa}"},
            )
        assert troca.status_code == 200
        token_com_empresa_b = troca.json()["access_token"]
        from jose import jwt

        from app.config import get_settings

        payload = jwt.decode(token_com_empresa_b, get_settings().jwt_secret, algorithms=["HS256"])
        assert payload["empresa_id"] == str(empresa_b.id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trocar_empresa_sem_vinculo_devolve_403(db_session):
    _empresa_a, titular = await criar_empresa_titular(db_session, email_titular="isolado@teste.com")
    empresa_alheia, _outro_titular = await criar_empresa_titular(
        db_session, cnpj="33333333000133", email_titular="dono-de-outra@teste.com",
    )
    token = criar_token(titular)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/auth/trocar-empresa",
                json={"empresa_id": str(empresa_alheia.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()
