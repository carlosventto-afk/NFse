import functools

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models import Cliente, EmissaoNfe, PapelUsuario, StatusEmissao
from app.security import criar_token
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


async def _criar_emissao_nfe(db_session, empresa, serie: str, numero: int) -> None:
    cliente = Cliente(empresa_id=empresa.id, nome="Comprador", cpf_cnpj="12345678901")
    db_session.add(cliente)
    await db_session.flush()
    db_session.add(EmissaoNfe(
        empresa_id=empresa.id, cliente_id=cliente.id, serie=serie, numero=numero,
        status=StatusEmissao.autorizada,
    ))
    await db_session.commit()


@pytest.mark.asyncio
async def test_admin_define_numeracao_nfe_sem_mexer_na_da_nfse(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)
    serie_nfse, proximo_numero_nfse = empresa.serie, empresa.proximo_numero

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/numeracao-nfe",
                json={"serie": "2", "proximo_numero": 501},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json() == {"serie": "2", "proximo_numero": 501}
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.serie_nfe == "2"
    assert empresa.proximo_numero_nfe == 501
    assert (empresa.serie, empresa.proximo_numero) == (serie_nfse, proximo_numero_nfse)


@pytest.mark.asyncio
async def test_nao_permite_numero_nfe_menor_ou_igual_ao_ja_usado_na_serie(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    await _criar_emissao_nfe(db_session, empresa, serie="1", numero=10)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/numeracao-nfe",
                json={"serie": "1", "proximo_numero": 5},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.proximo_numero_nfe == 1


@pytest.mark.asyncio
async def test_permite_numero_nfe_igual_ao_usado_em_outra_serie(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    await _criar_emissao_nfe(db_session, empresa, serie="1", numero=10)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/numeracao-nfe",
                json={"serie": "2", "proximo_numero": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_serie_nfe_maior_que_a_coluna_devolve_422(db_session):
    # Empresa.serie_nfe/EmissaoNfe.serie sao String(3): serie maior viraria
    # erro do banco (500) em vez de 422.
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/numeracao-nfe",
                json={"serie": "1234", "proximo_numero": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_operador_nao_pode_definir_numeracao_nfe(db_session):
    empresa, operador = await criar_empresa_titular(
        db_session, email_titular="operador-numeracao-nfe@teste.com", papel_vinculo=PapelUsuario.operador,
    )
    token = criar_token(operador, empresa_id=empresa.id, papel=PapelUsuario.operador)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/numeracao-nfe",
                json={"serie": "1", "proximo_numero": 100},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()
