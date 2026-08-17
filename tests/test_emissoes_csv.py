from datetime import datetime
from decimal import Decimal

import functools

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.models import Emissao, Empresa, OrigemEmissao, StatusEmissao
from app.periodo import FUSO_BRT
from tests.apoio import criar_empresa_e_token

CABECALHO = (
    "CATEGORIA;DATA DA VENDA;STONE ID;QTD DE PARCELAS;Nº DA PARCELA;VALOR BRUTO;"
    "ÚLTIMO STATUS;DATA DO ÚLTIMO STATUS"
)


def _csv(*linhas: str) -> bytes:
    conteudo = "﻿" + "\n".join([CABECALHO, *linhas]) + "\n"
    return conteudo.encode("utf-8")


async def _yield_session(session):
    yield session


async def _empresa_e_usuario(db_session) -> tuple[Empresa, str]:
    return await criar_empresa_e_token(
        db_session, municipio_ibge="1501402", codigo_tributacao="141001",
        descricao_servico_padrao="Lavagem de roupa",
    )


@pytest.mark.asyncio
async def test_preview_csv_nao_grava_nada_e_devolve_resumo_correto(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago;30/07/2026 14:30:04",
        "Venda;30/07/2026 17:00:47;31163341016913;1;1;13,990000;Pago;30/07/2026 17:00:47",
        "Ajuste Financeiro;30/07/2026 10:00:00;31163300000000;1;1;5,000000;Pago;30/07/2026 10:00:00",
        "Venda;30/07/2026 10:00:00;31163300000001;1;1;5,000000;Estornado;30/07/2026 10:00:00",
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/csv/preview",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["total_notas"] == 2
        assert corpo["valor_total"] == "41.97"
        assert corpo["ignoradas"] == {
            "status_nao_pago": 1, "categoria_nao_venda": 1,
            "linha_invalida": 0, "ja_emitida_anteriormente": 0,
        }
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalars().all()
    assert total == []
    await db_session.refresh(empresa)
    assert empresa.proximo_numero == 1


@pytest.mark.asyncio
async def test_confirmar_csv_cria_emissoes_pendentes_com_numero_reservado(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago;05/08/2026 09:15:00",
        "Venda;30/07/2026 17:00:47;31163341016913;1;1;13,990000;Pago;06/08/2026 11:20:00",
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["total_notas"] == 2
        assert corpo["valor_total"] == "41.97"
    finally:
        app.dependency_overrides.clear()

    emissoes = (
        await db_session.execute(
            select(Emissao)
            .where(Emissao.empresa_id == empresa.id)
            .order_by(Emissao.numero)
        )
    ).scalars().all()
    assert len(emissoes) == 2
    assert [e.numero for e in emissoes] == [1, 2]
    assert [e.serie for e in emissoes] == ["1", "1"]
    assert {e.origem for e in emissoes} == {OrigemEmissao.csv}
    assert {e.status for e in emissoes} == {StatusEmissao.pendente}
    assert {e.stone_charge_id for e in emissoes} == {"31163337249888", "31163341016913"}
    assert {e.descricao for e in emissoes} == {"Lavagem de roupa"}
    assert {e.valor for e in emissoes} == {Decimal("27.98"), Decimal("13.99")}
    assert {e.competencia.isoformat() for e in emissoes} == {"2026-07-01"}
    # dh_emi_original vem da coluna DATA DO ULTIMO STATUS (pagamento real,
    # nao a data em que a importacao rodou) — permite competencia retroativa.
    assert {e.dh_emi_original.astimezone(FUSO_BRT).replace(tzinfo=None) for e in emissoes} == {
        datetime(2026, 8, 5, 9, 15, 0), datetime(2026, 8, 6, 11, 20, 0),
    }


@pytest.mark.asyncio
async def test_confirmar_csv_duas_vezes_nao_duplica_nem_reserva_numero_de_novo(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _csv("Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago;30/07/2026 14:30:04")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.post(
                "/api/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
            segunda = await client.post(
                "/api/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert primeira.json()["total_notas"] == 1
        assert segunda.json()["total_notas"] == 0
        assert segunda.json()["ignoradas"]["ja_emitida_anteriormente"] == 1
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(
            select(Emissao).where(
                Emissao.empresa_id == empresa.id, Emissao.stone_charge_id == "31163337249888"
            )
        )
    ).scalars().all()
    assert len(total) == 1


@pytest.mark.asyncio
async def test_confirmar_csv_nao_cruza_dedupe_nem_visibilidade_entre_empresas(db_session):
    empresa_a, token_a = await _empresa_e_usuario(db_session)
    empresa_b, token_b = await criar_empresa_e_token(
        db_session, cnpj="99999999000199", email="op-b@teste.com",
        municipio_ibge="1501402", codigo_tributacao="141001",
        descricao_servico_padrao="Lavagem de roupa B",
    )

    # mesmo STONE ID em ambas as empresas — nao deveria haver colisao de dedupe
    conteudo = _csv("Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago;30/07/2026 14:30:04")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta_a = await client.post(
                "/api/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token_a}"},
            )
            resposta_b = await client.post(
                "/api/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert resposta_a.json()["total_notas"] == 1
        # empresa B nao e afetada pelo STONE ID ja usado pela empresa A
        assert resposta_b.json()["total_notas"] == 1
        assert resposta_b.json()["ignoradas"]["ja_emitida_anteriormente"] == 0
    finally:
        app.dependency_overrides.clear()

    emissoes_b = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa_b.id))
    ).scalars().all()
    assert len(emissoes_b) == 1
    assert emissoes_b[0].descricao == "Lavagem de roupa B"


@pytest.mark.asyncio
async def test_csv_com_cabecalho_invalido_devolve_400_sem_gravar_nada(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = "﻿COLUNA_ERRADA;OUTRA\nx;y\n".encode("utf-8")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 400
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalars().all()
    assert total == []


@pytest.mark.asyncio
async def test_confirmar_csv_vincula_cliente_padrao_e_reutiliza_entre_importacoes(db_session):
    from app.models import Cliente

    empresa, token = await _empresa_e_usuario(db_session)
    primeira = _csv("Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago;30/07/2026 14:30:04")
    segunda = _csv("Venda;30/07/2026 15:00:00;31163337249999;1;1;15,000000;Pago;30/07/2026 15:00:00")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio1.csv", primeira, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
            await client.post(
                "/api/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio2.csv", segunda, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.clear()

    clientes_padrao = (
        await db_session.execute(
            select(Cliente).where(Cliente.empresa_id == empresa.id, Cliente.eh_padrao_csv.is_(True))
        )
    ).scalars().all()
    assert len(clientes_padrao) == 1

    emissoes = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalars().all()
    assert len(emissoes) == 2
    assert {e.cliente_id for e in emissoes} == {clientes_padrao[0].id}
