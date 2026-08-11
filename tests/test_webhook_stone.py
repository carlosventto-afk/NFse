import functools
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, StatusEmissao


async def _empresa_com_token(db_session) -> Empresa:
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem de roupa",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash=hash_senha("token-secreto"),
    )
    db_session.add(empresa)
    await db_session.commit()
    return empresa


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_webhook_stone_cria_emissao_pendente_sem_documento_do_tomador(db_session):
    empresa = await _empresa_com_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/webhooks/stone/{empresa.id}",
                json={
                    "type": "charge.paid",
                    "id": "ch_abc123",
                    "amount": 4990,
                    "customer": {"id": "cus_1", "name": "Cliente Stone"},
                },
                headers={"X-Webhook-Token": "token-secreto"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["criado"] is True
    finally:
        app.dependency_overrides.clear()

    emissao = (
        await db_session.execute(select(Emissao).where(Emissao.empresa_id == empresa.id))
    ).scalar_one()
    assert emissao.status == StatusEmissao.pendente
    assert emissao.stone_charge_id == "ch_abc123"
    assert emissao.numero == 1  # reservado na hora, sem esperar documento
    assert emissao.tomador_cpf_cnpj is None
    assert emissao.tomador_nome == "Cliente Stone"


@pytest.mark.asyncio
async def test_webhook_stone_e_idempotente(db_session):
    empresa = await _empresa_com_token(db_session)
    payload = {
        "type": "charge.paid", "id": "ch_repetido", "amount": 1000,
        "customer": {"id": "cus_2", "name": "Cliente Repetido"},
    }

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            primeira = await client.post(
                f"/webhooks/stone/{empresa.id}", json=payload,
                headers={"X-Webhook-Token": "token-secreto"},
            )
            segunda = await client.post(
                f"/webhooks/stone/{empresa.id}", json=payload,
                headers={"X-Webhook-Token": "token-secreto"},
            )
        assert primeira.status_code == 200
        assert segunda.status_code == 200
        assert segunda.json().get("duplicado") is True
    finally:
        app.dependency_overrides.clear()

    total = (
        await db_session.execute(
            select(Emissao).where(
                Emissao.empresa_id == empresa.id, Emissao.stone_charge_id == "ch_repetido"
            )
        )
    ).scalars().all()
    assert len(total) == 1


@pytest.mark.asyncio
async def test_indice_unico_rejeita_stone_charge_id_duplicado_na_mesma_empresa(db_session):
    """Garante a idempotencia no nivel do banco, nao so na checagem da aplicacao.

    Insere duas Emissao com o mesmo (empresa_id, stone_charge_id) diretamente
    via session.add()/flush(), sem passar pelo router — contornando de
    proposito a checagem de "ja existe" que o endpoint faz antes de inserir.
    Se o indice parcial unico ix_emissoes_empresa_stone_charge_id (definido em
    app/models.py) for removido ou alterado por engano no futuro, este teste
    quebra.
    """
    empresa = await _empresa_com_token(db_session)

    primeira = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.webhook, stone_charge_id="ch_dup",
        status=StatusEmissao.pendente, serie="1", numero=1,
        descricao="Lavagem", valor=Decimal("10.00"), competencia=date.today().replace(day=1),
    )
    db_session.add(primeira)
    await db_session.flush()

    segunda = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.webhook, stone_charge_id="ch_dup",
        status=StatusEmissao.pendente, serie="1", numero=2,
        descricao="Lavagem", valor=Decimal("10.00"), competencia=date.today().replace(day=1),
    )
    db_session.add(segunda)
    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_webhook_stone_rejeita_token_errado(db_session):
    empresa = await _empresa_com_token(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                f"/webhooks/stone/{empresa.id}",
                json={"type": "charge.paid", "id": "x", "amount": 100, "customer": {"id": "1", "name": "A"}},
                headers={"X-Webhook-Token": "token-errado"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()
