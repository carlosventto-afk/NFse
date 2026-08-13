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


async def _empresa_titular_e_emissao_autorizada(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="1" * 50,
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    return empresa, titular, emissao


@pytest.mark.asyncio
async def test_admin_cancela_emissao_autorizada(db_session):
    empresa, titular, emissao = await _empresa_titular_e_emissao_autorizada(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/emissoes/{emissao.id}/cancelar",
                json={"motivo": "Servico nao foi prestado", "codigo_motivo": "2"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["status"] == "cancelamento_pendente"
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.cancelamento_pendente
    assert emissao.motivo_cancelamento == "Servico nao foi prestado"


@pytest.mark.asyncio
async def test_operador_nao_pode_cancelar(db_session):
    empresa, operador = await criar_empresa_titular(
        db_session, email_titular="operador-cancelamento@teste.com", papel_vinculo=PapelUsuario.operador,
    )
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="2" * 50,
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    token = criar_token(operador, empresa_id=empresa.id, papel=PapelUsuario.operador)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/emissoes/{emissao.id}/cancelar",
                json={"motivo": "Servico nao foi prestado", "codigo_motivo": "2"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cancelar_emissao_nao_autorizada_devolve_409(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/emissoes/{emissao.id}/cancelar",
                json={"motivo": "Erro na emissao", "codigo_motivo": "1"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 409
    finally:
        app.dependency_overrides.clear()
