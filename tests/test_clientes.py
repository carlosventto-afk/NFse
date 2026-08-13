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
async def test_criar_cliente_grava_dados_fiscais_completos(db_session):
    _empresa, token = await criar_empresa_e_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/clientes",
                json={
                    "cpf_cnpj": "98765432100", "nome": "Cliente Um",
                    "logradouro": "Rua A", "numero": "10", "bairro": "Centro",
                    "municipio_ibge": "3550308", "uf": "SP", "cep": "01001000",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["cpf_cnpj"] == "98765432100"
        assert corpo["cep"] == "01001000"
        assert corpo["ativo"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_criar_cliente_sem_documento_e_aceito(db_session):
    _empresa, token = await criar_empresa_e_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/clientes", json={"nome": "Sem documento"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["cpf_cnpj"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_criar_cliente_com_cpf_duplicado_devolve_409(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    db_session.add(Cliente(empresa_id=empresa.id, cpf_cnpj="98765432100", nome="Ja existe"))
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/clientes", json={"cpf_cnpj": "98765432100", "nome": "Duplicado"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_listar_clientes_omite_o_padrao_csv_e_respeita_isolamento(db_session):
    empresa_a, token_a = await criar_empresa_e_token(db_session)
    empresa_b, _token_b = await criar_empresa_e_token(
        db_session, cnpj="99999999000199", email="op-b@teste.com",
    )
    db_session.add_all([
        Cliente(empresa_id=empresa_a.id, nome="Da empresa A"),
        Cliente(empresa_id=empresa_a.id, nome="Padrao CSV da A", eh_padrao_csv=True),
        Cliente(empresa_id=empresa_b.id, nome="Da empresa B"),
    ])
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/clientes", headers={"Authorization": f"Bearer {token_a}"}
            )
        nomes = {item["nome"] for item in resposta.json()}
        assert nomes == {"Da empresa A"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_atualizar_cliente_permite_inativar(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    cliente = Cliente(empresa_id=empresa.id, nome="Original")
    db_session.add(cliente)
    await db_session.commit()
    await db_session.refresh(cliente)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                f"/api/clientes/{cliente.id}",
                json={"nome": "Original", "ativo": False},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_obter_cliente_de_outra_empresa_devolve_404(db_session):
    empresa_a, _token_a = await criar_empresa_e_token(db_session)
    empresa_b, token_b = await criar_empresa_e_token(
        db_session, cnpj="88888888000188", email="op-c@teste.com",
    )
    cliente_de_a = Cliente(empresa_id=empresa_a.id, nome="Da A")
    db_session.add(cliente_de_a)
    await db_session.commit()
    await db_session.refresh(cliente_de_a)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/api/clientes/{cliente_de_a.id}", headers={"Authorization": f"Bearer {token_b}"}
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()
