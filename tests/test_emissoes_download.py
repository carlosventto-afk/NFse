import functools
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.crypto import cifrar
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import Emissao, OrigemEmissao, PapelUsuario, StatusEmissao
from app.security import criar_token
from nfse_core import CertificateError
from tests.apoio import criar_empresa_titular


async def _empresa_usuario_emissao_autorizada(db_session):
    fernet_key = get_settings().fernet_key
    empresa, usuario = await criar_empresa_titular(
        db_session,
        certificado_pfx_cifrado=cifrar("pfx-fake", fernet_key),
        certificado_senha_cifrada=cifrar("senha-fake", fernet_key),
    )
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="1" * 50, xml_nfse=b"<NFSe>ok</NFSe>",
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(usuario)
    await db_session.refresh(emissao)
    return empresa, usuario, emissao


async def _yield_session(session):
    yield session


@pytest.mark.asyncio
async def test_listar_emissoes_filtra_por_status(db_session):
    empresa, usuario, emissao = await _empresa_usuario_emissao_autorizada(db_session)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/emissoes", params={"status": "autorizada"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert len(corpo) == 1
        assert corpo[0]["id"] == str(emissao.id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_xml_devolve_documento_autorizado(db_session):
    empresa, usuario, emissao = await _empresa_usuario_emissao_autorizada(db_session)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/api/emissoes/{emissao.id}/xml", headers={"Authorization": f"Bearer {token}"}
            )
        assert resposta.status_code == 200
        assert resposta.content == b"<NFSe>ok</NFSe>"
        assert resposta.headers["content-type"].startswith("application/xml")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_xml_devolve_dps_de_emissao_rejeitada(db_session):
    empresa, usuario = await criar_empresa_titular(db_session)
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.rejeitada,
        serie="1", numero=2, xml_dps=b"<DPS>rejeitada</DPS>", erros="E0008",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/api/emissoes/{emissao.id}/xml", headers={"Authorization": f"Bearer {token}"}
            )
        assert resposta.status_code == 200
        assert resposta.content == b"<DPS>rejeitada</DPS>"
        assert resposta.headers["content-type"].startswith("application/xml")
        assert "DPS_1_2.xml" in resposta.headers["content-disposition"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_xml_de_emissao_pendente_devolve_404(db_session):
    empresa, usuario = await criar_empresa_titular(db_session)
    emissao = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao)
    await db_session.commit()
    await db_session.refresh(emissao)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/api/emissoes/{emissao.id}/xml", headers={"Authorization": f"Bearer {token}"}
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "excecao",
    [
        # fetch_danfse_pdf chama load_pfx_pem antes de qualquer rede: com o
        # certificado vencido/senha errada ela LEVANTA, nao devolve None.
        CertificateError("Certificado A1 invalido ou senha incorreta"),
        # E qualquer outra falha inesperada tambem nao pode virar 500: o
        # fallback existe justamente para o usuario sempre receber um PDF.
        RuntimeError("falha inesperada ao falar com o ADN"),
    ],
)
async def test_baixar_pdf_cai_no_fallback_quando_a_busca_oficial_levanta(
    db_session, monkeypatch, excecao
):
    empresa, usuario, emissao = await _empresa_usuario_emissao_autorizada(db_session)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    import app.routers.emissoes as emissoes_router

    async def _fetch_danfse_pdf_explodindo(*args, **kwargs):
        raise excecao

    monkeypatch.setattr(
        emissoes_router.SefinClient, "fetch_danfse_pdf", staticmethod(_fetch_danfse_pdf_explodindo)
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/api/emissoes/{emissao.id}/pdf", headers={"Authorization": f"Bearer {token}"}
            )
        assert resposta.status_code == 200
        assert resposta.content.startswith(b"%PDF")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_listar_emissoes_usa_limites_de_dia_em_brt(db_session):
    """Nota emitida as 21:30 BRT do dia 31/08 fica gravada como 00:30 UTC de
    01/09. Comparando `date` cru contra timestamptz (Postgres em UTC) ela
    sumiria do filtro de agosto — e apareceria no de setembro."""
    empresa, usuario, emissao = await _empresa_usuario_emissao_autorizada(db_session)
    emissao.criada_em = datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc)  # 31/08 21:30 BRT
    await db_session.commit()
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            agosto = await client.get(
                "/api/emissoes", params={"inicio": "2026-08-01", "fim": "2026-08-31"},
                headers={"Authorization": f"Bearer {token}"},
            )
            setembro = await client.get(
                "/api/emissoes", params={"inicio": "2026-09-01", "fim": "2026-09-30"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert [item["id"] for item in agosto.json()] == [str(emissao.id)]
        assert setembro.json() == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_pdf_usa_fallback_quando_adn_nao_responde(db_session, monkeypatch):
    empresa, usuario, emissao = await _empresa_usuario_emissao_autorizada(db_session)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    import app.routers.emissoes as emissoes_router

    async def _fetch_danfse_pdf_falso(*args, **kwargs):
        return None

    monkeypatch.setattr(
        emissoes_router.SefinClient, "fetch_danfse_pdf", staticmethod(_fetch_danfse_pdf_falso)
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                f"/api/emissoes/{emissao.id}/pdf", headers={"Authorization": f"Bearer {token}"}
            )
        assert resposta.status_code == 200
        assert resposta.content.startswith(b"%PDF")
    finally:
        app.dependency_overrides.clear()
