import functools

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models import Produto
from tests.apoio import criar_empresa_e_token


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_criar_produto_com_substituicao_tributaria_e_aceito_mas_marcado(db_session):
    _empresa, token = await criar_empresa_e_token(db_session)
    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/produtos",
                json={"codigo_interno": "P1", "descricao": "Camiseta", "ncm": "61091000",
                      "cfop_padrao": "5102", "unidade": "UN", "eh_substituicao_tributaria": True},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["eh_substituicao_tributaria"] is True
        assert corpo["codigo_interno"] == "P1"
        assert corpo["ativo"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_listar_produtos_so_da_propria_empresa(db_session):
    empresa_a, token_a = await criar_empresa_e_token(db_session)
    empresa_b, _token_b = await criar_empresa_e_token(
        db_session, cnpj="99999999000199", email="op-produtos-b@teste.com",
    )
    db_session.add_all([
        Produto(
            empresa_id=empresa_a.id, codigo_interno="A1", descricao="Da empresa A",
            ncm="61091000", cfop_padrao="5102", unidade="UN",
        ),
        Produto(
            empresa_id=empresa_b.id, codigo_interno="B1", descricao="Da empresa B",
            ncm="61091000", cfop_padrao="5102", unidade="UN",
        ),
    ])
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/produtos", headers={"Authorization": f"Bearer {token_a}"}
            )
        assert resposta.status_code == 200
        descricoes = {item["descricao"] for item in resposta.json()}
        assert descricoes == {"Da empresa A"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_obter_produto_de_outra_empresa_devolve_404(db_session):
    empresa_a, _token_a = await criar_empresa_e_token(db_session)
    empresa_b, token_b = await criar_empresa_e_token(
        db_session, cnpj="88888888000188", email="op-produtos-c@teste.com",
    )
    produto_de_a = Produto(
        empresa_id=empresa_a.id, codigo_interno="A1", descricao="Da A",
        ncm="61091000", cfop_padrao="5102", unidade="UN",
    )
    db_session.add(produto_de_a)
    await db_session.commit()
    await db_session.refresh(produto_de_a)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/api/produtos/{produto_de_a.id}", headers={"Authorization": f"Bearer {token_b}"}
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_atualizar_produto_permite_inativar(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    produto = Produto(
        empresa_id=empresa.id, codigo_interno="P1", descricao="Original",
        ncm="61091000", cfop_padrao="5102", unidade="UN",
    )
    db_session.add(produto)
    await db_session.commit()
    await db_session.refresh(produto)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                f"/api/produtos/{produto.id}",
                json={
                    "codigo_interno": "P1", "descricao": "Original", "ncm": "61091000",
                    "cfop_padrao": "5102", "unidade": "UN", "ativo": False,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_atualizar_produto_de_outra_empresa_devolve_404(db_session):
    empresa_a, _token_a = await criar_empresa_e_token(db_session)
    empresa_b, token_b = await criar_empresa_e_token(
        db_session, cnpj="77777777000177", email="op-produtos-d@teste.com",
    )
    produto_de_a = Produto(
        empresa_id=empresa_a.id, codigo_interno="A1", descricao="Da A",
        ncm="61091000", cfop_padrao="5102", unidade="UN",
    )
    db_session.add(produto_de_a)
    await db_session.commit()
    await db_session.refresh(produto_de_a)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                f"/api/produtos/{produto_de_a.id}",
                json={
                    "codigo_interno": "A1", "descricao": "Tentativa invasao", "ncm": "61091000",
                    "cfop_padrao": "5102", "unidade": "UN",
                },
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_deletar_produto_faz_soft_delete(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    produto = Produto(
        empresa_id=empresa.id, codigo_interno="P1", descricao="Para apagar",
        ncm="61091000", cfop_padrao="5102", unidade="UN",
    )
    db_session.add(produto)
    await db_session.commit()
    await db_session.refresh(produto)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.delete(
                f"/api/produtos/{produto.id}", headers={"Authorization": f"Bearer {token}"}
            )
        assert resposta.status_code == 204
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(produto)
    assert produto.ativo is False


@pytest.mark.asyncio
async def test_deletar_produto_de_outra_empresa_devolve_404(db_session):
    empresa_a, _token_a = await criar_empresa_e_token(db_session)
    empresa_b, token_b = await criar_empresa_e_token(
        db_session, cnpj="66666666000166", email="op-produtos-e@teste.com",
    )
    produto_de_a = Produto(
        empresa_id=empresa_a.id, codigo_interno="A1", descricao="Da A",
        ncm="61091000", cfop_padrao="5102", unidade="UN",
    )
    db_session.add(produto_de_a)
    await db_session.commit()
    await db_session.refresh(produto_de_a)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.delete(
                f"/api/produtos/{produto_de_a.id}", headers={"Authorization": f"Bearer {token_b}"}
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()
