import functools
import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.crypto import cifrar
from app.db import get_db
from app.main import app
from app.models import Emissao, OrigemEmissao, PapelUsuario, StatusEmissao
from app.security import criar_token
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


def _empresa_com_certificado(**overrides):
    fernet_key = get_settings().fernet_key
    return dict(
        certificado_pfx_cifrado=cifrar("pfx-fake", fernet_key),
        certificado_senha_cifrada=cifrar("senha-fake", fernet_key),
        **overrides,
    )


@pytest.mark.asyncio
async def test_baixar_xmls_em_lote_gera_zip_com_arquivos_disponiveis(db_session):
    empresa, usuario = await criar_empresa_titular(db_session)
    autorizada = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="chave-1", xml_nfse=b"<NFSe>ok</NFSe>",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    rejeitada = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.rejeitada,
        serie="1", numero=2, xml_dps=b"<DPS>rejeitada</DPS>", erros="E0008",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add_all([autorizada, rejeitada])
    await db_session.commit()
    await db_session.refresh(autorizada)
    await db_session.refresh(rejeitada)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/download-xmls",
                json={"ids": [str(autorizada.id), str(rejeitada.id)]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.headers["content-type"].startswith("application/zip")
        with zipfile.ZipFile(io.BytesIO(resposta.content)) as zip_arquivo:
            nomes = set(zip_arquivo.namelist())
            assert nomes == {"NFSe_1_1.xml", "DPS_1_2.xml"}
            assert zip_arquivo.read("NFSe_1_1.xml") == b"<NFSe>ok</NFSe>"
            assert zip_arquivo.read("DPS_1_2.xml") == b"<DPS>rejeitada</DPS>"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_xmls_em_lote_pula_itens_sem_xml_disponivel(db_session):
    empresa, usuario = await criar_empresa_titular(db_session)
    autorizada = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="chave-1", xml_nfse=b"<NFSe>ok</NFSe>",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    pendente = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=3, descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add_all([autorizada, pendente])
    await db_session.commit()
    await db_session.refresh(autorizada)
    await db_session.refresh(pendente)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/download-xmls",
                json={"ids": [str(autorizada.id), str(pendente.id)]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resposta.content)) as zip_arquivo:
            assert zip_arquivo.namelist() == ["NFSe_1_1.xml"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_xmls_em_lote_ignora_emissao_de_outra_empresa(db_session):
    empresa_a, usuario_a = await criar_empresa_titular(db_session, cnpj="11111111000191", email_titular="a@teste.com")
    empresa_b, _ = await criar_empresa_titular(db_session, cnpj="22222222000192", email_titular="b@teste.com")
    emissao_a = Emissao(
        empresa_id=empresa_a.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="chave-a", xml_nfse=b"<NFSe>a</NFSe>",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    emissao_b = Emissao(
        empresa_id=empresa_b.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="chave-b", xml_nfse=b"<NFSe>b</NFSe>",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add_all([emissao_a, emissao_b])
    await db_session.commit()
    await db_session.refresh(emissao_a)
    await db_session.refresh(emissao_b)
    token_a = criar_token(usuario_a, empresa_id=empresa_a.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/download-xmls",
                json={"ids": [str(emissao_a.id), str(emissao_b.id)]},
                headers={"Authorization": f"Bearer {token_a}"},
            )
        assert resposta.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resposta.content)) as zip_arquivo:
            assert zip_arquivo.namelist() == ["NFSe_1_1.xml"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_xmls_em_lote_devolve_404_quando_nenhum_arquivo_disponivel(db_session):
    empresa, usuario = await criar_empresa_titular(db_session)
    pendente = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.pendente,
        serie="1", numero=1, descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(pendente)
    await db_session.commit()
    await db_session.refresh(pendente)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/download-xmls",
                json={"ids": [str(pendente.id)]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_pdfs_em_lote_gera_zip_com_pdfs(db_session, monkeypatch):
    empresa, usuario = await criar_empresa_titular(db_session, **_empresa_com_certificado())
    e1 = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="chave-1",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    e2 = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=2, chave_acesso="chave-2",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add_all([e1, e2])
    await db_session.commit()
    await db_session.refresh(e1)
    await db_session.refresh(e2)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    import app.routers.emissoes as emissoes_router

    async def _fetch_danfse_pdf_falso(ambiente, pfx_base64, senha, chave_acesso):
        return f"%PDF-{chave_acesso}".encode()

    monkeypatch.setattr(
        emissoes_router.SefinClient, "fetch_danfse_pdf", staticmethod(_fetch_danfse_pdf_falso)
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/download-pdfs",
                json={"ids": [str(e1.id), str(e2.id)]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.headers["content-type"].startswith("application/zip")
        with zipfile.ZipFile(io.BytesIO(resposta.content)) as zip_arquivo:
            nomes = set(zip_arquivo.namelist())
            assert nomes == {"NFSe_1_1.pdf", "NFSe_1_2.pdf"}
            assert zip_arquivo.read("NFSe_1_1.pdf") == b"%PDF-chave-1"
            assert zip_arquivo.read("NFSe_1_2.pdf") == b"%PDF-chave-2"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_pdfs_em_lote_pula_emissoes_nao_autorizadas(db_session, monkeypatch):
    empresa, usuario = await criar_empresa_titular(db_session, **_empresa_com_certificado())
    autorizada = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="chave-1",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    rejeitada = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.rejeitada,
        serie="1", numero=2, erros="E0008",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add_all([autorizada, rejeitada])
    await db_session.commit()
    await db_session.refresh(autorizada)
    await db_session.refresh(rejeitada)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    import app.routers.emissoes as emissoes_router

    async def _fetch_danfse_pdf_falso(*args, **kwargs):
        return b"%PDF-conteudo"

    monkeypatch.setattr(
        emissoes_router.SefinClient, "fetch_danfse_pdf", staticmethod(_fetch_danfse_pdf_falso)
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/download-pdfs",
                json={"ids": [str(autorizada.id), str(rejeitada.id)]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resposta.content)) as zip_arquivo:
            assert zip_arquivo.namelist() == ["NFSe_1_1.pdf"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_baixar_pdfs_em_lote_devolve_404_quando_nenhum_pdf_disponivel(db_session):
    empresa, usuario = await criar_empresa_titular(db_session, **_empresa_com_certificado())
    rejeitada = Emissao(
        empresa_id=empresa.id, origem=OrigemEmissao.manual, status=StatusEmissao.rejeitada,
        serie="1", numero=2, erros="E0008",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(rejeitada)
    await db_session.commit()
    await db_session.refresh(rejeitada)
    token = criar_token(usuario, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/emissoes/download-pdfs",
                json={"ids": [str(rejeitada.id)]},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 404
    finally:
        app.dependency_overrides.clear()
