import functools
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import Emissao, OrigemEmissao, PapelUsuario, StatusEmissao
from app.security import criar_token
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


async def _empresa_titular_e_emissao(db_session, status: StatusEmissao) -> tuple:
    empresa, titular = await criar_empresa_titular(db_session)
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=status,
        stone_charge_id="stone-123",
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    return empresa, titular, emissao


@pytest.mark.asyncio
async def test_admin_exclui_emissao_rejeitada(db_session):
    empresa, titular, emissao = await _empresa_titular_e_emissao(db_session, StatusEmissao.rejeitada)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.delete(
                f"/api/emissoes/{emissao.id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 204
    finally:
        app.dependency_overrides.clear()

    restante = (
        await db_session.execute(select(Emissao).where(Emissao.id == emissao.id))
    ).scalar_one_or_none()
    assert restante is None


@pytest.mark.asyncio
async def test_admin_exclui_emissao_pendente(db_session):
    empresa, titular, emissao = await _empresa_titular_e_emissao(db_session, StatusEmissao.pendente)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.delete(
                f"/api/emissoes/{emissao.id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 204
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_excluir_emissao_autorizada_devolve_409(db_session):
    empresa, titular, emissao = await _empresa_titular_e_emissao(db_session, StatusEmissao.autorizada)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.delete(
                f"/api/emissoes/{emissao.id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 409
    finally:
        app.dependency_overrides.clear()

    restante = (
        await db_session.execute(select(Emissao).where(Emissao.id == emissao.id))
    ).scalar_one_or_none()
    assert restante is not None


@pytest.mark.asyncio
async def test_operador_nao_pode_excluir(db_session):
    empresa, operador = await criar_empresa_titular(
        db_session, email_titular="operador-exclusao@teste.com", papel_vinculo=PapelUsuario.operador,
    )
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.rejeitada,
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    token = criar_token(operador, empresa_id=empresa.id, papel=PapelUsuario.operador)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.delete(
                f"/api/emissoes/{emissao.id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_excluir_emissao_libera_stone_charge_id_para_nova_importacao(db_session):
    empresa, titular, emissao = await _empresa_titular_e_emissao(db_session, StatusEmissao.rejeitada)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.delete(
                f"/api/emissoes/{emissao.id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            resposta_preview = await client.post(
                "/api/emissoes/csv/preview",
                files={
                    "arquivo": (
                        "relatorio.csv",
                        (
                            "﻿CATEGORIA;DATA DA VENDA;DATA DE VENCIMENTO;STONE ID;QTD DE PARCELAS;"
                            "Nº DA PARCELA;VALOR BRUTO;ÚLTIMO STATUS;DATA DO ÚLTIMO STATUS\n"
                            "Venda;30/07/2026 14:30:04;31/07/2026;stone-123;1;1;49,90;Pago;"
                            "30/07/2026 14:30:04\n"
                        ).encode("utf-8"),
                        "text/csv",
                    )
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        corpo = resposta_preview.json()
        assert corpo["total_notas"] == 1
        assert corpo["ignoradas"]["ja_emitida_anteriormente"] == 0
    finally:
        app.dependency_overrides.clear()
