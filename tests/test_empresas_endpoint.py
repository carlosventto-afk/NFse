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

from app.crypto import hash_senha
from app.db import get_db
from app.main import app
from app.models import Plano, Usuario


def _pfx_teste_base64() -> str:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EMPRESA TESTE LTDA:12345678000199")])
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


def _form_padrao(titular_email: str) -> dict:
    return {
        "cnpj": "12345678000199", "inscricao_municipal": "123456", "municipio_ibge": "3550308",
        "op_simp_nac": "3", "codigo_tributacao": "140106",
        "descricao_servico_padrao": "Servicos de lavagem de roupa", "ambiente": "homologacao",
        "senha_certificado": "senha123", "titular_email": titular_email,
    }


@pytest.mark.asyncio
async def test_titular_cria_a_propria_empresa_dentro_do_limite(db_session):
    from app.security import criar_token

    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.flush()
    titular = Usuario(email="titular@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    db_session.add(titular)
    await db_session.commit()
    await db_session.refresh(titular)
    token = criar_token(titular)

    pfx_b64 = _pfx_teste_base64()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/empresas",
                data=_form_padrao("titular@teste.com"),
                files={"pfx": ("certificado.pfx", base64.b64decode(pfx_b64), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
        assert resposta.json()["cnpj"] == "12345678000199"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_usuario_comum_nao_pode_criar_empresa_para_outro_titular(db_session):
    from app.security import criar_token

    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.flush()
    usuario = Usuario(email="comum@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    outro_titular = Usuario(email="outro@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    db_session.add_all([usuario, outro_titular])
    await db_session.commit()
    await db_session.refresh(usuario)
    token = criar_token(usuario)

    pfx_b64 = _pfx_teste_base64()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/empresas",
                data=_form_padrao("outro@teste.com"),
                files={"pfx": ("certificado.pfx", base64.b64decode(pfx_b64), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_plataforma_cria_empresa_para_qualquer_titular(db_session):
    from app.security import criar_token

    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.flush()
    adm = Usuario(email="adm@plataforma.com", senha_hash=hash_senha("senha-forte-123"), eh_admin_plataforma=True)
    titular = Usuario(email="titular2@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    db_session.add_all([adm, titular])
    await db_session.commit()
    await db_session.refresh(adm)
    token = criar_token(adm)

    pfx_b64 = _pfx_teste_base64()

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/empresas",
                data=_form_padrao("titular2@teste.com"),
                files={"pfx": ("certificado.pfx", base64.b64decode(pfx_b64), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 201
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_titular_acima_do_limite_do_plano_devolve_422(db_session):
    from app.security import criar_token
    from scripts.criar_empresa import criar_empresa

    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.flush()
    titular = Usuario(email="no-limite@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    db_session.add(titular)
    await db_session.commit()
    await db_session.refresh(titular)

    await criar_empresa(
        db_session, cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Primeira",
        ambiente="homologacao", pfx_base64=_pfx_teste_base64(), senha_certificado="senha123",
        webhook_token="token-1", titular_email="no-limite@teste.com",
    )
    token = criar_token(titular)

    app.dependency_overrides[get_db] = functools.partial(_yield_session, db_session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resposta = await client.post(
                "/api/empresas",
                data=_form_padrao("no-limite@teste.com"),
                files={"pfx": ("certificado.pfx", base64.b64decode(_pfx_teste_base64()), "application/x-pkcs12")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resposta.status_code == 422
    finally:
        app.dependency_overrides.clear()
