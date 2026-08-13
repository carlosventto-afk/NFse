from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.crypto import hash_senha
from app.models import AmbienteEnum, Empresa, PapelUsuario, Plano, Usuario, UsuarioEmpresa


async def _empresa_minima(db_session, titular_id=None) -> Empresa:
    empresa = Empresa(
        cnpj="12345678000199", inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular_id,
    )
    db_session.add(empresa)
    await db_session.flush()
    return empresa


@pytest.mark.asyncio
async def test_usuario_nao_tem_mais_empresa_id_nem_papel_fixos(db_session):
    usuario = Usuario(email="titular@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(usuario)
    await db_session.commit()
    await db_session.refresh(usuario)

    assert not hasattr(usuario, "empresa_id")
    assert not hasattr(usuario, "papel")
    assert usuario.eh_admin_plataforma is False
    assert usuario.plano_id is None


@pytest.mark.asyncio
async def test_plano_limita_empresas_e_e_reaproveitavel(db_session):
    plano = Plano(nome="Basico", limite_empresas=2)
    db_session.add(plano)
    await db_session.flush()
    titular = Usuario(
        email="titular2@teste.com", senha_hash=hash_senha("senha-forte-123"), plano_id=plano.id,
    )
    db_session.add(titular)
    await db_session.commit()
    await db_session.refresh(titular)

    assert titular.plano_id == plano.id


@pytest.mark.asyncio
async def test_usuario_empresa_vincula_usuario_a_varias_empresas_com_papel_por_vinculo(db_session):
    titular = Usuario(email="dono@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    empresa_a = await _empresa_minima(db_session, titular_id=titular.id)
    empresa_b = Empresa(
        cnpj="98765432000199", inscricao_municipal="2", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem B",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular.id,
    )
    db_session.add(empresa_b)
    await db_session.flush()

    db_session.add_all([
        UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa_a.id, papel=PapelUsuario.admin),
        UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa_b.id, papel=PapelUsuario.operador),
    ])
    await db_session.commit()

    from sqlalchemy import select
    vinculos = (
        await db_session.execute(
            select(UsuarioEmpresa).where(UsuarioEmpresa.usuario_id == titular.id)
        )
    ).scalars().all()
    assert len(vinculos) == 2
    papeis = {v.empresa_id: v.papel for v in vinculos}
    assert papeis[empresa_a.id] == PapelUsuario.admin
    assert papeis[empresa_b.id] == PapelUsuario.operador


@pytest.mark.asyncio
async def test_usuario_empresa_rejeita_vinculo_duplicado(db_session):
    titular = Usuario(email="dup@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    empresa = await _empresa_minima(db_session, titular_id=titular.id)
    db_session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa.id, papel=PapelUsuario.admin))
    await db_session.commit()

    db_session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa.id, papel=PapelUsuario.operador))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_convite_grava_email_papel_plano_e_token(db_session):
    from app.models import Convite

    titular = Usuario(email="quemconvida@teste.com", senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()
    plano = Plano(nome="Basico", limite_empresas=1)
    db_session.add(plano)
    await db_session.flush()

    convite = Convite(
        email="novo@teste.com", plano_id=plano.id, token="token-unico-123",
        expira_em=datetime.now(timezone.utc), criado_por_usuario_id=titular.id,
    )
    db_session.add(convite)
    await db_session.commit()
    await db_session.refresh(convite)

    assert convite.aceito_em is None
    assert convite.empresa_id is None
    assert convite.plano_id == plano.id
