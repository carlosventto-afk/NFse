from datetime import datetime, timezone
from decimal import Decimal

import functools

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import (
    AmbienteEnum, Emissao, Empresa, OrigemEmissao, PapelUsuario, StatusEmissao, Usuario,
)
from app.security import criar_token

CABECALHO = "CATEGORIA;DATA DA VENDA;STONE ID;QTD DE PARCELAS;Nº DA PARCELA;VALOR BRUTO;ÚLTIMO STATUS"


def _csv(*linhas: str) -> bytes:
    conteudo = "﻿" + "\n".join([CABECALHO, *linhas]) + "\n"
    return conteudo.encode("utf-8")


async def _yield_session(session):
    yield session


async def _empresa_e_usuario(db_session) -> tuple[Empresa, str]:
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="1501402",
        op_simp_nac=3, codigo_tributacao="141001", descricao_servico_padrao="Lavagem de roupa",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    db_session.add(empresa)
    await db_session.flush()
    usuario = Usuario(
        empresa_id=empresa.id, email="op@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.operador,
    )
    db_session.add(usuario)
    await db_session.commit()
    await db_session.refresh(usuario)
    return empresa, criar_token(usuario)


@pytest.mark.asyncio
async def test_preview_csv_nao_grava_nada_e_devolve_resumo_correto(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _csv(
        "Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago",
        "Venda;30/07/2026 17:00:47;31163341016913;1;1;13,990000;Pago",
        "Ajuste Financeiro;30/07/2026 10:00:00;31163300000000;1;1;5,000000;Pago",
        "Venda;30/07/2026 10:00:00;31163300000001;1;1;5,000000;Estornado",
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/emissoes/csv/preview",
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
        "Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago",
        "Venda;30/07/2026 17:00:47;31163341016913;1;1;13,990000;Pago",
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/emissoes/csv/confirmar",
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


@pytest.mark.asyncio
async def test_confirmar_csv_duas_vezes_nao_duplica_nem_reserva_numero_de_novo(db_session):
    empresa, token = await _empresa_e_usuario(db_session)
    conteudo = _csv("Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.post(
                "/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token}"},
            )
            segunda = await client.post(
                "/emissoes/csv/confirmar",
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
    empresa_b = Empresa(
        cnpj="99999999000199", inscricao_municipal="2", municipio_ibge="1501402",
        op_simp_nac=3, codigo_tributacao="141001", descricao_servico_padrao="Lavagem de roupa B",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    db_session.add(empresa_b)
    await db_session.flush()
    usuario_b = Usuario(
        empresa_id=empresa_b.id, email="op-b@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.operador,
    )
    db_session.add(usuario_b)
    await db_session.commit()
    await db_session.refresh(usuario_b)
    token_b = criar_token(usuario_b)

    # mesmo STONE ID em ambas as empresas — nao deveria haver colisao de dedupe
    conteudo = _csv("Venda;30/07/2026 14:30:04;31163337249888;1;1;27,980000;Pago")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta_a = await client.post(
                "/emissoes/csv/confirmar",
                files={"arquivo": ("relatorio.csv", conteudo, "text/csv")},
                headers={"Authorization": f"Bearer {token_a}"},
            )
            resposta_b = await client.post(
                "/emissoes/csv/confirmar",
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
                "/emissoes/csv/confirmar",
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
