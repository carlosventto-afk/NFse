import functools

import pytest
from httpx import ASGITransport, AsyncClient

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import Empresa, PapelUsuario, Usuario
from app.security import criar_token
from datetime import datetime, timezone


async def _empresa_minima(db_session) -> Empresa:
    from app.models import AmbienteEnum

    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    db_session.add(empresa)
    await db_session.flush()
    return empresa


@pytest.mark.asyncio
async def test_login_com_credenciais_corretas_devolve_token(db_session):
    empresa = await _empresa_minima(db_session)
    usuario = Usuario(
        empresa_id=empresa.id, email="admin@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.admin,
    )
    db_session.add(usuario)
    await db_session.commit()

    # FastAPI so reconhece uma dependencia como "async generator" olhando
    # para a funcao geradora em si (via functools.partial ela continua
    # visivel atraves do unwrap); uma lambda que apenas retorna o generator
    # ja instanciado nao e reconhecida e quebra a injecao de sessao.
    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/auth/login", data={"username": "admin@teste.com", "password": "senha-forte-123"}
            )
        assert resposta.status_code == 200
        assert "access_token" in resposta.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_com_senha_errada_devolve_401(db_session):
    empresa = await _empresa_minima(db_session)
    usuario = Usuario(
        empresa_id=empresa.id, email="admin2@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.admin,
    )
    db_session.add(usuario)
    await db_session.commit()

    # FastAPI so reconhece uma dependencia como "async generator" olhando
    # para a funcao geradora em si (via functools.partial ela continua
    # visivel atraves do unwrap); uma lambda que apenas retorna o generator
    # ja instanciado nao e reconhecida e quebra a injecao de sessao.
    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/auth/login", data={"username": "admin2@teste.com", "password": "errada"}
            )
        assert resposta.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_cria_operador_na_propria_empresa(db_session):
    empresa = await _empresa_minima(db_session)
    admin = Usuario(
        empresa_id=empresa.id, email="admin3@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.admin,
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    token = criar_token(admin)

    # FastAPI so reconhece uma dependencia como "async generator" olhando
    # para a funcao geradora em si (via functools.partial ela continua
    # visivel atraves do unwrap); uma lambda que apenas retorna o generator
    # ja instanciado nao e reconhecida e quebra a injecao de sessao.
    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/usuarios",
                json={"email": "operador@teste.com", "senha": "outra-senha-123", "papel": "operador"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["papel"] == "operador"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "campo, valor_excessivo",
    [
        # bcrypt.hashpw levanta ValueError acima de 72 bytes -> era 500
        ("senha", "S" * 73),
        # 72 caracteres acentuados = 144 bytes: passa do max_length e ainda
        # assim estouraria no bcrypt, que conta BYTES
        ("senha", "á" * 72),
        # Usuario.email e String(255) -> era StringDataRightTruncationError (500)
        ("email", "u" * 250 + "@exemplo.com.br"),
    ],
)
async def test_criar_usuario_recusa_campo_excessivo_com_422(db_session, campo, valor_excessivo):
    empresa = await _empresa_minima(db_session)
    admin = Usuario(
        empresa_id=empresa.id, email="admin4@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.admin,
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    token = criar_token(admin)

    corpo = {"email": "novo@teste.com", "senha": "senha-valida-123", "papel": "operador"}
    corpo[campo] = valor_excessivo

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/usuarios", json=corpo, headers={"Authorization": f"Bearer {token}"}
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_com_senha_absurdamente_longa_devolve_401_e_nao_500(db_session):
    """bcrypt.checkpw levanta ValueError acima de 72 bytes: sem o guarda em
    `verificar_senha`, uma senha gigante no login virava 500."""
    empresa = await _empresa_minima(db_session)
    usuario = Usuario(
        empresa_id=empresa.id, email="admin5@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.admin,
    )
    db_session.add(usuario)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/auth/login",
                data={"username": "admin5@teste.com", "password": "x" * 500},
            )
        assert resposta.status_code == 401
    finally:
        app.dependency_overrides.clear()


async def _yield_session(session):
    yield session
