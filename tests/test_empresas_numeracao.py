import functools
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models import Emissao, OrigemEmissao, PapelUsuario, StatusEmissao
from app.security import criar_token
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_admin_le_numeracao_atual(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/empresas/numeracao", headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json() == {"serie": "1", "proximo_numero": 1}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_define_numeracao_para_continuar_de_outro_sistema(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/numeracao",
                json={"serie": "2", "proximo_numero": 501},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json() == {"serie": "2", "proximo_numero": 501}
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.serie == "2"
    assert empresa.proximo_numero == 501


@pytest.mark.asyncio
async def test_nao_permite_numero_menor_ou_igual_ao_ja_usado_na_serie(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=10, chave_acesso="1" * 50,
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/numeracao",
                json={"serie": "1", "proximo_numero": 5},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.proximo_numero == 1


@pytest.mark.asyncio
async def test_permite_numero_igual_ao_usado_em_outra_serie(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=10, chave_acesso="1" * 50,
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/numeracao",
                json={"serie": "2", "proximo_numero": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_operador_nao_pode_definir_numeracao(db_session):
    empresa, operador = await criar_empresa_titular(
        db_session, email_titular="operador-numeracao@teste.com", papel_vinculo=PapelUsuario.operador,
    )
    token = criar_token(operador, empresa_id=empresa.id, papel=PapelUsuario.operador)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/numeracao",
                json={"serie": "1", "proximo_numero": 100},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()
