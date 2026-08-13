"""Helpers compartilhados de fixture para os testes de multiempresa.

Centraliza a criacao de "empresa com um titular vinculado" — sem isto, o
mesmo bloco de ~15 linhas se repetiria em quase todo arquivo de teste que
precisa de uma empresa autenticavel.
"""
from datetime import datetime, timezone

from app.crypto import hash_senha
from app.models import AmbienteEnum, Empresa, PapelUsuario, Usuario, UsuarioEmpresa
from app.security import criar_token


async def criar_empresa_titular(
    db_session,
    *,
    cnpj: str = "12345678000199",
    email_titular: str = "titular@teste.com",
    papel_vinculo: PapelUsuario = PapelUsuario.admin,
    **overrides_empresa,
) -> tuple[Empresa, Usuario]:
    titular = Usuario(email=email_titular, senha_hash=hash_senha("senha-forte-123"))
    db_session.add(titular)
    await db_session.flush()

    dados_empresa = dict(
        cnpj=cnpj, inscricao_municipal="1", municipio_ibge="3550308",
        op_simp_nac=3, codigo_tributacao="140106", descricao_servico_padrao="Lavagem de roupa",
        ambiente=AmbienteEnum.homologacao, certificado_pfx_cifrado="x",
        certificado_senha_cifrada="x", certificado_valido_ate=datetime.now(timezone.utc),
        webhook_token_hash="x", titular_id=titular.id,
    )
    dados_empresa.update(overrides_empresa)
    empresa = Empresa(**dados_empresa)
    db_session.add(empresa)
    await db_session.flush()

    db_session.add(UsuarioEmpresa(usuario_id=titular.id, empresa_id=empresa.id, papel=papel_vinculo))
    await db_session.commit()
    await db_session.refresh(titular)
    await db_session.refresh(empresa)
    return empresa, titular


async def criar_empresa_e_token(
    db_session,
    *,
    papel: PapelUsuario = PapelUsuario.operador,
    email: str = "op@teste.com",
    **overrides_empresa,
) -> tuple[Empresa, str]:
    empresa, usuario = await criar_empresa_titular(
        db_session, email_titular=email, papel_vinculo=papel, **overrides_empresa
    )
    token = criar_token(usuario, empresa_id=empresa.id, papel=papel)
    return empresa, token
