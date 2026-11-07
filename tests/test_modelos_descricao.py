import functools

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models import Cliente
from tests.apoio import criar_empresa_e_token


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_criar_modelo_descricao_geral_sem_cliente(db_session):
    _empresa, token = await criar_empresa_e_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/modelos-descricao",
                json={"titulo": "Consultoria mensal", "texto": "Servicos de consultoria referentes a {mes}."},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["titulo"] == "Consultoria mensal"
        assert corpo["cliente_id"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_criar_modelo_descricao_vinculado_a_cliente(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = Cliente(empresa_id=empresa.id, nome="Cliente Um")
    db_session.add(cliente)
    await db_session.commit()
    await db_session.refresh(cliente)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/modelos-descricao",
                json={"titulo": "Manutencao predial", "texto": "Manutencao predial do mes.", "cliente_id": str(cliente.id)},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["cliente_id"] == str(cliente.id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_criar_modelo_descricao_com_cliente_de_outra_empresa_devolve_404(db_session):
    _empresa_a, token_a = await criar_empresa_e_token(db_session, cnpj="11111111000111", email="a@teste.com")
    empresa_b, _token_b = await criar_empresa_e_token(db_session, cnpj="22222222000122", email="b@teste.com")
    cliente_de_b = Cliente(empresa_id=empresa_b.id, nome="Cliente de outra empresa")
    db_session.add(cliente_de_b)
    await db_session.commit()
    await db_session.refresh(cliente_de_b)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/modelos-descricao",
                json={"titulo": "X", "texto": "Y", "cliente_id": str(cliente_de_b.id)},
                headers={"Authorization": f"Bearer {token_a}"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_listar_modelos_descricao_so_da_propria_empresa(db_session):
    _empresa_a, token_a = await criar_empresa_e_token(db_session, cnpj="11111111000111", email="a@teste.com")
    empresa_b, token_b = await criar_empresa_e_token(db_session, cnpj="22222222000122", email="b@teste.com")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/modelos-descricao", json={"titulo": "Da empresa A", "texto": "texto"},
                headers={"Authorization": f"Bearer {token_a}"},
            )
            await client.post(
                "/api/modelos-descricao", json={"titulo": "Da empresa B", "texto": "texto"},
                headers={"Authorization": f"Bearer {token_b}"},
            )
            resposta = await client.get(
                "/api/modelos-descricao", headers={"Authorization": f"Bearer {token_a}"},
            )
        titulos = [m["titulo"] for m in resposta.json()]
        assert titulos == ["Da empresa A"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_atualizar_modelo_descricao_de_outra_empresa_devolve_404(db_session):
    _empresa_a, token_a = await criar_empresa_e_token(db_session, cnpj="11111111000111", email="a@teste.com")
    empresa_b, token_b = await criar_empresa_e_token(db_session, cnpj="22222222000122", email="b@teste.com")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            criado = await client.post(
                "/api/modelos-descricao", json={"titulo": "Da empresa B", "texto": "texto"},
                headers={"Authorization": f"Bearer {token_b}"},
            )
            modelo_id = criado.json()["id"]
            resposta = await client.put(
                f"/api/modelos-descricao/{modelo_id}", json={"titulo": "Invasao", "texto": "texto"},
                headers={"Authorization": f"Bearer {token_a}"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_remover_modelo_descricao(db_session):
    _empresa, token = await criar_empresa_e_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            criado = await client.post(
                "/api/modelos-descricao", json={"titulo": "Apagar", "texto": "texto"},
                headers={"Authorization": f"Bearer {token}"},
            )
            modelo_id = criado.json()["id"]
            resposta = await client.delete(
                f"/api/modelos-descricao/{modelo_id}", headers={"Authorization": f"Bearer {token}"},
            )
            listagem = await client.get(
                "/api/modelos-descricao", headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 204
        assert listagem.json() == []
    finally:
        app.dependency_overrides.clear()
