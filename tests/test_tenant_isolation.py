"""Regressao de isolamento multiempresa.

O plano exige que "todo endpoint autenticado escope dados pelo `empresa_id` do
usuario logado (nunca por um `empresa_id` recebido do cliente)". Cada task foi
revisada isoladamente por inspecao, mas nenhum teste provava a garantia
end-to-end com DUAS empresas de verdade no banco. Este arquivo faz isso: cria
empresa A e empresa B, cada uma com seu usuario, uma emissao autorizada em A, e
verifica que o usuario de B nao consegue ver nem baixar nada de A.

Se alguem trocar um `usuario.empresa_id` por um parametro vindo do cliente, ou
esquecer o filtro numa rota nova, estes testes quebram.
"""
import functools
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.crypto import cifrar
from app.db import get_db
from app.main import app
from app.models import Emissao, Empresa, OrigemEmissao, PapelUsuario, StatusEmissao, Usuario, UsuarioEmpresa
from app.security import criar_token
from tests.apoio import criar_empresa_titular


async def _yield_session(session):
    yield session


async def _empresa_com_usuario(db_session, *, cnpj: str, email: str) -> tuple[Empresa, Usuario]:
    fernet_key = get_settings().fernet_key
    return await criar_empresa_titular(
        db_session, cnpj=cnpj, email_titular=email,
        certificado_pfx_cifrado=cifrar("pfx-fake", fernet_key),
        certificado_senha_cifrada=cifrar("senha-fake", fernet_key),
    )


async def _duas_empresas(db_session):
    empresa_a, usuario_a = await _empresa_com_usuario(
        db_session, cnpj="11111111000111", email="admin@empresa-a.com"
    )
    empresa_b, usuario_b = await _empresa_com_usuario(
        db_session, cnpj="22222222000122", email="admin@empresa-b.com"
    )
    emissao_de_a = Emissao(
        empresa_id=empresa_a.id, origem=OrigemEmissao.manual,
        status=StatusEmissao.autorizada, serie="1", numero=1,
        chave_acesso="9" * 50, xml_nfse=b"<NFSe>segredo da empresa A</NFSe>",
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente da A",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao_de_a)
    await db_session.commit()
    await db_session.refresh(usuario_a)
    await db_session.refresh(usuario_b)
    await db_session.refresh(emissao_de_a)
    return emissao_de_a, empresa_a, usuario_a, empresa_b, usuario_b


@pytest.mark.asyncio
async def test_listagem_nao_mostra_emissao_de_outra_empresa(db_session):
    emissao_de_a, empresa_a, usuario_a, empresa_b, usuario_b = await _duas_empresas(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            de_b = await client.get(
                "/emissoes", headers={"Authorization": f"Bearer {criar_token(usuario_b, empresa_id=empresa_b.id, papel=PapelUsuario.admin)}"}
            )
            de_a = await client.get(
                "/emissoes", headers={"Authorization": f"Bearer {criar_token(usuario_a, empresa_id=empresa_a.id, papel=PapelUsuario.admin)}"}
            )
        assert de_b.status_code == 200
        assert de_b.json() == []  # a emissao existe no banco, mas nao e da B
        assert [item["id"] for item in de_a.json()] == [str(emissao_de_a.id)]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_download_de_xml_de_outra_empresa_devolve_404(db_session):
    emissao_de_a, empresa_a, usuario_a, empresa_b, usuario_b = await _duas_empresas(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            de_b = await client.get(
                f"/emissoes/{emissao_de_a.id}/xml",
                headers={"Authorization": f"Bearer {criar_token(usuario_b, empresa_id=empresa_b.id, papel=PapelUsuario.admin)}"},
            )
            de_a = await client.get(
                f"/emissoes/{emissao_de_a.id}/xml",
                headers={"Authorization": f"Bearer {criar_token(usuario_a, empresa_id=empresa_a.id, papel=PapelUsuario.admin)}"},
            )
        assert de_b.status_code == 404
        assert b"segredo da empresa A" not in de_b.content
        # o mesmo id, para o dono, continua funcionando — o 404 e por escopo,
        # nao porque a rota esta quebrada
        assert de_a.status_code == 200
        assert de_a.content == b"<NFSe>segredo da empresa A</NFSe>"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_download_de_pdf_de_outra_empresa_devolve_404(db_session, monkeypatch):
    emissao_de_a, empresa_a, usuario_a, empresa_b, usuario_b = await _duas_empresas(db_session)

    import app.routers.emissoes as emissoes_router

    async def _sem_adn(*args, **kwargs):
        return None  # forca o fallback local, sem rede

    monkeypatch.setattr(
        emissoes_router.SefinClient, "fetch_danfse_pdf", staticmethod(_sem_adn)
    )

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            de_b = await client.get(
                f"/emissoes/{emissao_de_a.id}/pdf",
                headers={"Authorization": f"Bearer {criar_token(usuario_b, empresa_id=empresa_b.id, papel=PapelUsuario.admin)}"},
            )
            de_a = await client.get(
                f"/emissoes/{emissao_de_a.id}/pdf",
                headers={"Authorization": f"Bearer {criar_token(usuario_a, empresa_id=empresa_a.id, papel=PapelUsuario.admin)}"},
            )
        assert de_b.status_code == 404
        assert not de_b.content.startswith(b"%PDF")
        assert de_a.status_code == 200
        assert de_a.content.startswith(b"%PDF")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dashboard_nao_soma_valores_de_outra_empresa(db_session):
    """Nao esta na lista original do achado, mas e a mesma garantia e a rota
    agrega valores — vazamento aqui seria silencioso (numero errado, sem erro)."""
    emissao_de_a, empresa_a, usuario_a, empresa_b, usuario_b = await _duas_empresas(db_session)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            periodo = {"inicio": "2020-01-01", "fim": "2030-12-31"}
            de_b = await client.get(
                "/dashboard", params=periodo,
                headers={"Authorization": f"Bearer {criar_token(usuario_b, empresa_id=empresa_b.id, papel=PapelUsuario.admin)}"},
            )
            de_a = await client.get(
                "/dashboard", params=periodo,
                headers={"Authorization": f"Bearer {criar_token(usuario_a, empresa_id=empresa_a.id, papel=PapelUsuario.admin)}"},
            )
        assert de_b.json()["total_autorizado"] == "0.00"
        assert de_a.json()["total_autorizado"] == "49.90"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_isolamento_atraves_de_troca_de_empresa_ativa(db_session):
    empresa_a, titular = await criar_empresa_titular(
        db_session, cnpj="77777777000177", email_titular="titular-duas-empresas@teste.com",
    )
    empresa_b = Empresa(
        cnpj="88888888000188", inscricao_municipal="2", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem B",
        ambiente=empresa_a.ambiente, certificado_pfx_cifrado="x", certificado_senha_cifrada="x",
        certificado_valido_ate=empresa_a.certificado_valido_ate, webhook_token_hash="x",
        titular_id=titular.id,
    )
    db_session.add(empresa_b)
    await db_session.flush()
    db_session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa_b.id, papel=PapelUsuario.admin))
    emissao_de_a = Emissao(
        empresa_id=empresa_a.id, origem=OrigemEmissao.manual, status=StatusEmissao.autorizada,
        serie="1", numero=1, chave_acesso="8" * 50, xml_nfse=b"<NFSe>segredo da empresa A</NFSe>",
        tomador_cpf_cnpj="98765432100", tomador_nome="Cliente da A",
        descricao="Lavagem", valor=Decimal("49.90"), competencia=date(2026, 8, 1),
    )
    db_session.add(emissao_de_a)
    await db_session.commit()
    await db_session.refresh(titular)

    token_ativo_em_b = criar_token(titular, empresa_id=empresa_b.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listagem = await client.get(
                "/emissoes", headers={"Authorization": f"Bearer {token_ativo_em_b}"}
            )
        assert listagem.status_code == 200
        # mesmo titular, mas com B como empresa ativa: nao ve a nota da empresa A
        assert listagem.json() == []
    finally:
        app.dependency_overrides.clear()
