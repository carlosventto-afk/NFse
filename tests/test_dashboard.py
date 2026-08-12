import functools
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, PapelUsuario, StatusEmissao, Usuario
from app.security import criar_token


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_dashboard_soma_valores_por_status(db_session):
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
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
    db_session.add_all([
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
            serie="1", numero=1, descricao="Lavagem", valor=Decimal("50.00"), competencia=date(2026, 8, 1),
        ),
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
            serie="1", numero=2, descricao="Lavagem", valor=Decimal("30.00"), competencia=date(2026, 8, 1),
        ),
        Emissao(
            empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.rejeitada,
            serie="1", numero=3, descricao="Lavagem", valor=Decimal("20.00"), competencia=date(2026, 8, 1),
        ),
    ])
    await db_session.commit()
    await db_session.refresh(usuario)
    token = criar_token(usuario)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/dashboard", params={"inicio": "2026-08-01", "fim": "2026-08-31"},
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
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x",
    )
    db_session.add(empresa)
    await db_session.flush()
    usuario = Usuario(
        empresa_id=empresa.id, email="op2@teste.com",
        senha_hash=hash_senha("senha-forte-123"), papel=PapelUsuario.operador,
    )
    db_session.add(usuario)
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("50.00"),
        competencia=date(2026, 8, 1),
        criada_em=datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc),  # 31/08 21:30 BRT
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(usuario)
    token = criar_token(usuario)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            agosto = await client.get(
                "/dashboard", params={"inicio": "2026-08-01", "fim": "2026-08-31"},
                headers={"Authorization": f"Bearer {token}"},
            )
            setembro = await client.get(
                "/dashboard", params={"inicio": "2026-09-01", "fim": "2026-09-30"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert agosto.json()["total_autorizado"] == "50.00"
        assert setembro.json()["total_autorizado"] == "0.00"
    finally:
        app.dependency_overrides.clear()
