import base64
import functools
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from httpx import ASGITransport, AsyncClient

from app.crypto import decifrar
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import PapelUsuario
from app.security import criar_token
from tests.apoio import criar_empresa_titular


def _pfx_teste_base64(cnpj: str = "99988877000155") -> str:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"EMPRESA TESTE LTDA:{cnpj}")])
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    pfx_bytes = pkcs12.serialize_key_and_certificates(
        name=b"teste", key=chave, cert=certificado, cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(b"senha123"),
    )
    return base64.b64encode(pfx_bytes).decode()


async def _yield_session(session):
    yield session


def _form_edicao(**overrides) -> dict:
    base = {
        "cnpj": "12345678000199", "inscricao_municipal": "1", "municipio_ibge": "3550308",
        "op_simp_nac": "3", "codigo_tributacao": "140106",
        "descricao_servico_padrao": "Lavagem de roupa", "ambiente": "homologacao",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_admin_le_dados_atuais_da_empresa(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.get(
                "/api/empresas/mim", headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["cnpj"] == "12345678000199"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_edita_campos_simples_sem_trocar_certificado(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)
    certificado_original = empresa.certificado_pfx_cifrado

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(
                    descricao_servico_padrao="Lavagem e passagem de roupa", ambiente="producao",
                ),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["descricao_servico_padrao"] == "Lavagem e passagem de roupa"
        assert corpo["ambiente"] == "producao"
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    assert empresa.certificado_pfx_cifrado == certificado_original


@pytest.mark.asyncio
async def test_admin_troca_cnpj(db_session):
    empresa, titular = await criar_empresa_titular(db_session)
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(cnpj="99.988.877/0001-55"),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
        assert resposta.json()["cnpj"] == "99988877000155"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_editar_com_cnpj_ja_usado_por_outra_empresa_devolve_422(db_session):
    empresa, titular = await criar_empresa_titular(db_session, cnpj="12345678000199")
    await criar_empresa_titular(
        db_session, cnpj="99988877000155", email_titular="outro-titular@teste.com",
    )
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(cnpj="99988877000155"),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_troca_o_certificado(db_session):
    empresa, titular = await criar_empresa_titular(db_session, cnpj="99988877000155")
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)
    pfx_b64 = _pfx_teste_base64(cnpj="99988877000155")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data={**_form_edicao(cnpj="99988877000155"), "senha_certificado": "senha123"},
                files={"pfx": ("novo.pfx", base64.b64decode(pfx_b64), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 200
    finally:
        app.dependency_overrides.clear()

    await db_session.refresh(empresa)
    settings = get_settings()
    assert decifrar(empresa.certificado_senha_cifrada, settings.fernet_key) == "senha123"


@pytest.mark.asyncio
async def test_trocar_certificado_sem_senha_devolve_422(db_session):
    empresa, titular = await criar_empresa_titular(db_session, cnpj="99988877000155")
    token = criar_token(titular, empresa_id=empresa.id, papel=PapelUsuario.admin)
    pfx_b64 = _pfx_teste_base64(cnpj="99988877000155")

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(cnpj="99988877000155"),
                files={"pfx": ("novo.pfx", base64.b64decode(pfx_b64), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_operador_nao_pode_editar_empresa(db_session):
    empresa, operador = await criar_empresa_titular(
        db_session, email_titular="operador-editar@teste.com", papel_vinculo=PapelUsuario.operador,
    )
    token = criar_token(operador, empresa_id=empresa.id, papel=PapelUsuario.operador)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.put(
                "/api/empresas/mim",
                data=_form_edicao(),
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()
