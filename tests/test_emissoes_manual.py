import functools

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models import Empresa
from tests.apoio import criar_empresa_e_token


async def _empresa_e_usuario(db_session) -> tuple[Empresa, str]:
    return await criar_empresa_e_token(db_session)


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_emissao_manual_reserva_numero_e_cria_pendente(db_session):
    empresa, token = await _empresa_e_usuario(db_session)

    # FastAPI so reconhece uma dependencia como "async generator" olhando para
    # a funcao geradora em si (via functools.partial ela continua visivel
    # atraves do unwrap); uma lambda que apenas retorna o generator ja
    # instanciado nao e reconhecida e quebra a injecao de sessao.
    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/manual",
                json={
                    "cpf_cnpj": "98765432100", "nome": "Cliente Manual",
                    "descricao": "Lavagem de edredom", "valor": "35.00",
                    "competencia": "2026-08-01",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["origem"] == "manual"
        assert corpo["status"] == "pendente"
        assert corpo["numero"] == 1
        assert corpo["tomador_cpf_cnpj"] == "98765432100"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_emissao_manual_com_cpf_invalido_nao_reserva_numero(db_session):
    empresa, token = await _empresa_e_usuario(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/manual",
                json={
                    "cpf_cnpj": "123", "nome": "Cliente Invalido",
                    "descricao": "Lavagem", "valor": "10.00", "competencia": "2026-08-01",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422

        await db_session.refresh(empresa)
        assert empresa.proximo_numero == 1  # nao avancou
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "campo, valor_excessivo",
    [
        ("nome", "N" * 301),          # Emissao.tomador_nome String(300)
        ("descricao", "D" * 2001),    # Emissao.descricao String(2000)
        ("email", "e" * 70 + "@exemplo.com.br"),  # Emissao.tomador_email String(80)
        ("valor", "1000000000000.00"),  # Emissao.valor Numeric(14, 2)
    ],
)
async def test_emissao_manual_recusa_campo_maior_que_a_coluna_com_422(
    db_session, campo, valor_excessivo
):
    """Sem limite no schema, o excesso so era detectado no INSERT e virava 500
    (StringDataRightTruncationError / numeric field overflow)."""
    empresa, token = await _empresa_e_usuario(db_session)
    corpo = {
        "nome": "Cliente", "descricao": "Lavagem",
        "valor": "10.00", "competencia": "2026-08-01",
    }
    corpo[campo] = valor_excessivo

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/manual", json=corpo,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422

        await db_session.refresh(empresa)
        assert empresa.proximo_numero == 1  # nao reservou numero
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_emissao_manual_sem_documento_do_tomador_e_aceita(db_session):
    empresa, token = await _empresa_e_usuario(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/manual",
                json={
                    "nome": "Cliente Sem Documento",
                    "descricao": "Lavagem", "valor": "10.00", "competencia": "2026-08-01",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["numero"] == 1
        assert corpo["tomador_cpf_cnpj"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_listar_emissoes_sem_empresa_ativa_devolve_409(db_session):
    from app.crypto import hash_senha
    from app.models import Usuario
    from app.security import criar_token

    usuario_sem_empresa = Usuario(email="sem-empresa-ativa@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(usuario_sem_empresa)
    await db_session.commit()
    await db_session.refresh(usuario_sem_empresa)
    token = criar_token(usuario_sem_empresa)  # sem empresa_id/papel

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get("/api/emissoes", headers={"Authorization": f"Bearer {token}"})
        assert resposta.status_code == 409
    finally:
        app.dependency_overrides.clear()
