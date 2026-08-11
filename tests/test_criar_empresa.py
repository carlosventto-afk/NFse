import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app.models import Empresa, PapelUsuario, Usuario
from scripts.criar_empresa import criar_empresa


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


@pytest.mark.asyncio
async def test_criar_empresa_grava_empresa_e_admin_cifrando_certificado(db_session):
    pfx_b64 = _pfx_teste_base64()

    empresa = await criar_empresa(
        db_session,
        cnpj="12345678000199",
        inscricao_municipal="123456",
        municipio_ibge="3550308",
        op_simp_nac=3,
        codigo_tributacao="140106",
        descricao_servico_padrao="Servicos de lavagem de roupa",
        ambiente="homologacao",
        pfx_base64=pfx_b64,
        senha_certificado="senha123",
        webhook_token="token-super-secreto",
        admin_email="admin@empresa-teste.com",
        admin_senha="senha-forte-123",
    )

    assert empresa.cnpj == "12345678000199"
    assert empresa.certificado_pfx_cifrado != pfx_b64  # nunca em claro
    assert empresa.certificado_valido_ate.date() > date.today()

    admin = (
        await db_session.execute(select(Usuario).where(Usuario.empresa_id == empresa.id))
    ).scalar_one()
    assert admin.email == "admin@empresa-teste.com"
    assert admin.papel == PapelUsuario.admin
    assert admin.senha_hash != "senha-forte-123"


@pytest.mark.asyncio
async def test_criar_empresa_rejeita_certificado_de_cnpj_diferente(db_session, capsys):
    pfx_b64 = _pfx_teste_base64()  # CNPJ 12345678000199

    with pytest.raises(ValueError, match="CNPJ"):
        await criar_empresa(
            db_session,
            cnpj="99999999000199",
            inscricao_municipal="123456",
            municipio_ibge="3550308",
            op_simp_nac=3,
            codigo_tributacao="140106",
            descricao_servico_padrao="Servicos de lavagem de roupa",
            ambiente="homologacao",
            pfx_base64=pfx_b64,
            senha_certificado="senha123",
            webhook_token="token-super-secreto",
            admin_email="admin@empresa-teste.com",
            admin_senha="senha-forte-123",
        )
