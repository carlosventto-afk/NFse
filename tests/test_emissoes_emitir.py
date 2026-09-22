import functools
import json
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
async def test_operador_emite_nota_aguardando_emissao(db_session):
    empresa, operador = await criar_empresa_titular(
        db_session, email_titular="operador-emitir@teste.com", papel_vinculo=PapelUsuario.operador,
    )
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.aguardando_emissao,
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
            resposta = await client.post(
                f"/api/emissoes/{emissao.id}/emitir",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["status"] == "pendente"
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.pendente


@pytest.mark.asyncio
async def test_emitir_nota_que_nao_esta_aguardando_emissao_devolve_409(db_session):
    empresa, titular, emissao = await _empresa_titular_e_emissao(db_session, StatusEmissao.pendente)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/emissoes/{emissao.id}/emitir",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 409
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.pendente


@pytest.mark.asyncio
async def test_emitir_emissao_de_outra_empresa_devolve_404(db_session):
    empresa_a, titular_a, emissao_a = await _empresa_titular_e_emissao(
        db_session, StatusEmissao.aguardando_emissao,
    )
    empresa_b, titular_b = await criar_empresa_titular(
        db_session, cnpj="22222222000192", email_titular="b-emitir@teste.com",
    )
    token_b = criar_token(titular_b, empresa_id=empresa_b.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/emissoes/{emissao_a.id}/emitir",
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_emitir_lote_transiciona_as_elegiveis_e_pula_as_outras(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    aguardando1 = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.aguardando_emissao,
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    aguardando2 = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.aguardando_emissao,
        serie="1", numero=2, descricao="Lavagem", valor=Decimal("13.99"), competencia=date(2026, 8, 1),
    )
    ja_autorizada = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.autorizada,
        serie="1", numero=3, chave_acesso="chave-1", descricao="Lavagem",
        valor=Decimal("15.99"), competencia=date(2026, 8, 1),
    )
    db_session.add_all([aguardando1, aguardando2, ja_autorizada])
    await db_session.commit()
    for emissao in (aguardando1, aguardando2, ja_autorizada):
        await db_session.refresh(emissao)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/emitir-lote",
                json={"ids": [str(aguardando1.id), str(aguardando2.id), str(ja_autorizada.id)]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json() == {"emitidas": 2, "puladas": 1}
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(aguardando1)
    await db_session.refresh(aguardando2)
    await db_session.refresh(ja_autorizada)
    assert aguardando1.status == StatusEmissao.pendente
    assert aguardando2.status == StatusEmissao.pendente
    assert ja_autorizada.status == StatusEmissao.autorizada


@pytest.mark.asyncio
async def test_emitir_lote_ignora_emissao_de_outra_empresa(db_session):
    empresa_a, titular_a = await criar_empresa_titular(
        db_session, cnpj="11111111000191", email_titular="a-emitir-lote@teste.com",
    )
    empresa_b, _ = await criar_empresa_titular(
        db_session, cnpj="22222222000192", email_titular="b-emitir-lote@teste.com",
    )
    aguardando_a = Emissao(
        empresa_id=empresa_a.id, origem=OrigemEmissao.csv, status=StatusEmissao.aguardando_emissao,
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    aguardando_b = Emissao(
        empresa_id=empresa_b.id, origem=OrigemEmissao.csv, status=StatusEmissao.aguardando_emissao,
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add_all([aguardando_a, aguardando_b])
    await db_session.commit()
    await db_session.refresh(aguardando_a)
    await db_session.refresh(aguardando_b)
    token_a = criar_token(titular_a, empresa_id=empresa_a.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/emitir-lote",
                json={"ids": [str(aguardando_a.id), str(aguardando_b.id)]},
                headers={"Authorization": f"Bearer {token_a}"},
            )
        assert resposta.status_code == 200
        assert resposta.json() == {"emitidas": 1, "puladas": 1}
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(aguardando_b)
    assert aguardando_b.status == StatusEmissao.aguardando_emissao


@pytest.mark.asyncio
async def test_excluir_emissao_aguardando_emissao_funciona(db_session):
    empresa, titular, emissao = await _empresa_titular_e_emissao(db_session, StatusEmissao.aguardando_emissao)
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
async def test_reemitir_nota_rejeitada_individual(db_session):
    empresa, titular, emissao = await _empresa_titular_e_emissao(db_session, StatusEmissao.rejeitada)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/emissoes/{emissao.id}/emitir",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["status"] == "pendente"
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(emissao)
    assert emissao.status == StatusEmissao.pendente


@pytest.mark.asyncio
async def test_reemitir_nota_rejeitada_limpa_erro_da_tentativa_anterior(db_session):
    # Sem isso o erro antigo (ex.: E188) fica preso na coluna mesmo depois
    # do usuario clicar Reemitir, dando a falsa impressao de que a nota
    # ainda esta com problema enquanto o worker reprocessa.
    empresa, titular, emissao = await _empresa_titular_e_emissao(db_session, StatusEmissao.rejeitada)
    emissao.erros = json.dumps([{"codigo": "E188", "titulo": "Opcao simples nacional conflita..."}])
    await db_session.commit()
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/api/emissoes/{emissao.id}/emitir",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(emissao)
    assert emissao.erros is None


@pytest.mark.asyncio
async def test_reemitir_lote_inclui_rejeitadas_e_aguardando_emissao(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    rejeitada = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.rejeitada,
        serie="1", numero=1, erros="E0008", descricao="Lavagem",
        valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    aguardando = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.aguardando_emissao,
        serie="1", numero=2, descricao="Lavagem", valor=Decimal("13.99"), competencia=date(2026, 8, 1),
    )
    ja_autorizada = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.csv, status=StatusEmissao.autorizada,
        serie="1", numero=3, chave_acesso="chave-1", descricao="Lavagem",
        valor=Decimal("15.99"), competencia=date(2026, 8, 1),
    )
    db_session.add_all([rejeitada, aguardando, ja_autorizada])
    await db_session.commit()
    for emissao in (rejeitada, aguardando, ja_autorizada):
        await db_session.refresh(emissao)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/emitir-lote",
                json={"ids": [str(rejeitada.id), str(aguardando.id), str(ja_autorizada.id)]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json() == {"emitidas": 2, "puladas": 1}
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(rejeitada)
    await db_session.refresh(aguardando)
    await db_session.refresh(ja_autorizada)
    assert rejeitada.status == StatusEmissao.pendente
    assert aguardando.status == StatusEmissao.pendente
    assert ja_autorizada.status == StatusEmissao.autorizada
