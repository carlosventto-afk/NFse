import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app.crypto import hash_senha
from app.models import Empresa, PapelUsuario, Plano, Usuario, UsuarioEmpresa
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


async def _titular_com_plano(db_session, *, limite_empresas: int, email: str) -> Usuario:
    plano = Plano(nome="Teste", limite_empresas=limite_empresas)
    db_session.add(plano)
    await db_session.flush()
    titular = Usuario(email=email, senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id)
    db_session.add(titular)
    await db_session.commit()
    await db_session.refresh(titular)
    return titular


@pytest.mark.asyncio
async def test_criar_empresa_grava_empresa_e_vincula_titular_como_admin(db_session):
    titular = await _titular_com_plano(db_session, limite_empresas=2, email="titular@empresa-teste.com")
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
        titular_email="titular@empresa-teste.com",
    )

    assert empresa.cnpj == "12345678000199"
    assert empresa.titular_id == titular.id
    assert empresa.certificado_pfx_cifrado != pfx_b64  # nunca em claro
    assert empresa.certificado_valido_ate.date() > date.today()

    vinculo = (
        await db_session.execute(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == titular.id, UsuarioEmpresa.empresa_id == empresa.id,
            )
        )
    ).scalar_one()
    assert vinculo.papel == PapelUsuario.admin


@pytest.mark.asyncio
async def test_criar_empresa_rejeita_certificado_de_cnpj_diferente(db_session):
    await _titular_com_plano(db_session, limite_empresas=2, email="titular2@empresa-teste.com")
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
            titular_email="titular2@empresa-teste.com",
        )


@pytest.mark.asyncio
async def test_criar_empresa_recusa_titular_sem_plano(db_session):
    titular = Usuario(email="sem-plano@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.commit()
    pfx_b64 = _pfx_teste_base64()

    with pytest.raises(ValueError, match="plano"):
        await criar_empresa(
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
            titular_email="sem-plano@teste.com",
        )


@pytest.mark.asyncio
async def test_criar_empresa_recusa_acima_do_limite_do_plano(db_session):
    await _titular_com_plano(db_session, limite_empresas=1, email="no-limite@teste.com")
    pfx_b64 = _pfx_teste_base64()

    await criar_empresa(
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
        webhook_token="token-super-secreto-1",
        titular_email="no-limite@teste.com",
    )

    with pytest.raises(ValueError, match="limite"):
        await criar_empresa(
            db_session,
            cnpj="98765432000199",
            inscricao_municipal="654321",
            municipio_ibge="3550308",
            op_simp_nac=3,
            codigo_tributacao="140106",
            descricao_servico_padrao="Segunda empresa",
            ambiente="homologacao",
            pfx_base64=_pfx_teste_base64(),
            senha_certificado="senha123",
            webhook_token="token-super-secreto-2",
            titular_email="no-limite@teste.com",
        )
