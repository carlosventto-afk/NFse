import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crypto import hash_senha, verificar_senha
from app.db import get_db
from app.email import enviar_redefinicao_senha
from app.models import Empresa, PapelUsuario, RedefinicaoSenha, Usuario, UsuarioEmpresa
from app.schemas import (
    EmpresaVinculadaOut, EsqueciSenhaIn, RedefinirSenhaIn, TokenOut, TrocarEmpresaIn,
)
from app.security import ContextoAutenticado, criar_token, get_contexto_autenticado

router = APIRouter(prefix="/auth", tags=["auth"])

TEMPO_EXPIRACAO_REDEFINICAO = timedelta(hours=1)


@router.post("/login", response_model=TokenOut)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db),
) -> TokenOut:
    usuario = (
        await session.execute(select(Usuario).where(Usuario.email == form.username))
    ).scalar_one_or_none()
    if usuario is None or not verificar_senha(form.password, usuario.senha_hash):
        raise HTTPException(status_code=401, detail="Credenciais invalidas")

    vinculos = (
        await session.execute(select(UsuarioEmpresa).where(UsuarioEmpresa.usuario_id == usuario.id))
    ).scalars().all()

    empresa_id = None
    papel = None
    if len(vinculos) == 1:
        empresa_id = vinculos[0].empresa_id
        papel = PapelUsuario(vinculos[0].papel)

    return TokenOut(access_token=criar_token(usuario, empresa_id=empresa_id, papel=papel))


@router.get("/empresas", response_model=list[EmpresaVinculadaOut])
async def listar_minhas_empresas(
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    linhas = (
        await session.execute(
            select(UsuarioEmpresa, Empresa)
            .join(Empresa, Empresa.id == UsuarioEmpresa.empresa_id)
            .where(UsuarioEmpresa.usuario_id == contexto.usuario.id)
        )
    ).all()
    return [
        {"empresa_id": vinculo.empresa_id, "cnpj": empresa.cnpj, "papel": vinculo.papel}
        for vinculo, empresa in linhas
    ]


@router.post("/trocar-empresa", response_model=TokenOut)
async def trocar_empresa(
    dados: TrocarEmpresaIn,
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
    session: AsyncSession = Depends(get_db),
) -> TokenOut:
    vinculo = (
        await session.execute(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == contexto.usuario.id,
                UsuarioEmpresa.empresa_id == dados.empresa_id,
            )
        )
    ).scalar_one_or_none()
    if vinculo is None:
        if not contexto.eh_admin_plataforma:
            raise HTTPException(status_code=403, detail="Sem acesso a essa empresa")
        # Admin da plataforma pode entrar em qualquer empresa mesmo sem
        # vinculo previo -- cria o vinculo (papel admin) na hora, na
        # primeira vez que ele pede pra entrar nela.
        empresa = await session.get(Empresa, dados.empresa_id)
        if empresa is None:
            raise HTTPException(status_code=404, detail="Empresa nao encontrada")
        vinculo = UsuarioEmpresa(
            usuario_id=contexto.usuario.id, empresa_id=dados.empresa_id, papel=PapelUsuario.admin,
        )
        session.add(vinculo)
        await session.commit()
        await session.refresh(vinculo)
    return TokenOut(
        access_token=criar_token(
            contexto.usuario, empresa_id=vinculo.empresa_id, papel=PapelUsuario(vinculo.papel)
        )
    )


@router.post("/esqueci-senha", status_code=status.HTTP_204_NO_CONTENT)
async def esqueci_senha(
    dados: EsqueciSenhaIn,
    session: AsyncSession = Depends(get_db),
) -> None:
    # Sempre responde 204, exista ou nao o e-mail -- nao da pra deixar esse
    # endpoint publico revelar quais e-mails tem conta no sistema.
    usuario = (
        await session.execute(select(Usuario).where(Usuario.email == dados.email))
    ).scalar_one_or_none()
    if usuario is None:
        return None

    agora = datetime.now(timezone.utc)
    pendentes = (
        await session.execute(
            select(RedefinicaoSenha).where(
                RedefinicaoSenha.usuario_id == usuario.id,
                RedefinicaoSenha.usado_em.is_(None),
                RedefinicaoSenha.expira_em > agora,
            )
        )
    ).scalars().all()
    for pendente in pendentes:
        pendente.expira_em = agora

    redefinicao = RedefinicaoSenha(
        usuario_id=usuario.id,
        token=secrets.token_urlsafe(32),
        expira_em=agora + TEMPO_EXPIRACAO_REDEFINICAO,
    )
    session.add(redefinicao)
    await session.commit()

    settings = get_settings()
    link = f"{settings.app_base_url}/redefinir-senha?token={redefinicao.token}"
    await enviar_redefinicao_senha(usuario.email, link)
    return None


@router.post("/redefinir-senha", status_code=status.HTTP_204_NO_CONTENT)
async def redefinir_senha(
    dados: RedefinirSenhaIn,
    session: AsyncSession = Depends(get_db),
) -> None:
    redefinicao = (
        await session.execute(select(RedefinicaoSenha).where(RedefinicaoSenha.token == dados.token))
    ).scalar_one_or_none()
    if redefinicao is None:
        raise HTTPException(status_code=400, detail="Link invalido ou expirado")
    if redefinicao.usado_em is not None:
        raise HTTPException(status_code=400, detail="Link invalido ou expirado")
    if redefinicao.expira_em <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Link invalido ou expirado")

    usuario = await session.get(Usuario, redefinicao.usuario_id)
    if usuario is None:
        raise HTTPException(status_code=400, detail="Link invalido ou expirado")

    usuario.senha_hash = hash_senha(dados.nova_senha)
    redefinicao.usado_em = datetime.now(timezone.utc)
    await session.commit()
    return None
