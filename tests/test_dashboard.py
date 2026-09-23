import functools
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models import Emissao, OrigemEmissao, StatusEmissao
from tests.apoio import criar_empresa_e_token


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_dashboard_soma_valores_por_status(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    # criada_em precisa ser fixado dentro de agosto/2026 explicitamente -- o
    # default (_agora(), UTC no momento em que o teste roda) so cai nesse
    # range por coincidencia de calendario, e o filtro do dashboard usa
    # criada_em (nao competencia). Mesmo cuidado ja aplicado no teste de BRT
    # logo abaixo.
    agosto_meio = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
    db_session.add_all([
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
            serie="1", numero=1, descricao="Lavagem", valor=Decimal("50.00"), competencia=date(2026, 8, 1),
            criada_em=agosto_meio,
        ),
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
            serie="1", numero=2, descricao="Lavagem", valor=Decimal("30.00"), competencia=date(2026, 8, 1),
            criada_em=agosto_meio,
        ),
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.rejeitada,
            serie="1", numero=3, descricao="Lavagem", valor=Decimal("20.00"), competencia=date(2026, 8, 1),
            criada_em=agosto_meio,
        ),
    ])
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/dashboard", params={"inicio": "2026-08-01", "fim": "2026-08-31"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["totais_por_status"]["autorizada"] == "80.00"
        assert corpo["totais_por_status"]["rejeitada"] == "20.00"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dashboard_usa_limites_de_dia_em_brt(db_session):
    """Mesma armadilha da listagem: `criada_em` e timestamptz e o Postgres
    converte um `date` cru pelo TimeZone da sessao (UTC). A nota das 21:30 BRT
    do dia 31/08 (00:30 UTC de 01/09) tem que somar em AGOSTO."""
    empresa, token = await criar_empresa_e_token(db_session, email="op2@teste.com")
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("50.00"),
        competencia=date(2026, 8, 1),
        criada_em=datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc),  # 31/08 21:30 BRT
    )
    db_session.add(emissao)
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            agosto = await client.get(
                "/api/dashboard", params={"inicio": "2026-08-01", "fim": "2026-08-31"},
                headers={"Authorization": f"Bearer {token}"},
            )
            setembro = await client.get(
                "/api/dashboard", params={"inicio": "2026-09-01", "fim": "2026-09-30"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert agosto.json()["total_autorizado"] == "50.00"
        assert setembro.json()["total_autorizado"] == "0.00"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_resumo_agrupa_por_status_produto_bandeira_e_serie_diaria(db_session):
    empresa, token = await criar_empresa_e_token(db_session)
    db_session.add_all([
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.aguardando_emissao,
            serie="1", numero=1, descricao="Lavagem", valor=Decimal("30.00"), competencia=date(2026, 8, 1),
            data_vencimento=date(2026, 8, 5), produto="Credito", tipo_produto="Credito", bandeira="Visa",
        ),
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.autorizada,
            serie="1", numero=2, descricao="Lavagem", valor=Decimal("20.00"), competencia=date(2026, 8, 1),
            data_vencimento=date(2026, 8, 5), produto="Debito", tipo_produto="Debito", bandeira="Elo",
        ),
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.autorizada,
            serie="1", numero=3, descricao="Lavagem", valor=Decimal("10.00"), competencia=date(2026, 8, 1),
            data_vencimento=date(2026, 8, 6), produto="Pix QRcode", tipo_produto="PIX", bandeira=None,
        ),
        # fora da competencia de agosto -- nao deve entrar em nenhuma soma
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.autorizada,
            serie="1", numero=4, descricao="Lavagem", valor=Decimal("999.00"), competencia=date(2026, 7, 1),
            data_vencimento=date(2026, 7, 31), produto="Credito", tipo_produto="Credito", bandeira="Visa",
        ),
    ])
    await db_session.commit()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/dashboard/resumo", params={"competencia": "2026-08-15"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()

        assert corpo["competencia"] == "2026-08-01"
        assert corpo["total_notas"] == 3
        assert corpo["valor_total"] == "60.00"

        por_status = {linha["chave"]: linha for linha in corpo["por_status"]}
        assert por_status["aguardando_emissao"]["valor"] == "30.00"
        assert por_status["autorizada"]["quantidade"] == 2
        assert por_status["autorizada"]["valor"] == "30.00"

        por_tipo = {linha["chave"]: linha for linha in corpo["por_tipo_produto"]}
        assert por_tipo["Credito"]["valor"] == "30.00"
        assert por_tipo["Debito"]["valor"] == "20.00"
        assert por_tipo["PIX"]["valor"] == "10.00"

        por_bandeira = {linha["chave"]: linha for linha in corpo["por_bandeira"]}
        assert por_bandeira["Visa"]["valor"] == "30.00"
        assert por_bandeira["Elo"]["valor"] == "20.00"
        assert por_bandeira[None]["valor"] == "10.00"

        assert corpo["serie_diaria"] == [
            {"data": "2026-08-05", "quantidade": 2, "valor": "50.00"},
            {"data": "2026-08-06", "quantidade": 1, "valor": "10.00"},
        ]
    finally:
        app.dependency_overrides.clear()
