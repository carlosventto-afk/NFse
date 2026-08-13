import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crypto import hash_senha
from app.db import get_db
from app.email import enviar_convite
from app.models import Convite, PapelUsuario, Usuario, UsuarioEmpresa
from app.schemas import ConviteAceitarIn, ConviteCriarIn, ConviteOut
from app.security import ContextoAutenticado, get_contexto_autenticado

router = APIRouter(prefix="/convites", tags=["convites"])


@router.post("", response_model=ConviteOut, status_code=201)
async def criar_convite(
    dados: ConviteCriarIn,
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
    session: AsyncSession = Depends(get_db),
) -> Convite:
    if contexto.eh_admin_plataforma:
        if dados.plano_id is None:
            raise HTTPException(status_code=422, detail="plano_id e obrigatorio para convite de titular")
        empresa_id = None
        papel = None
    elif contexto.papel == PapelUsuario.admin and contexto.empresa_id is not None:
        if dados.papel is None:
            raise HTTPException(status_code=422, detail="papel e obrigatorio para convite de operador")
        empresa_id = contexto.empresa_id
        papel = PapelUsuario(dados.papel)
    else:
        raise HTTPException(status_code=403, detail="Sem permissao para convidar")

    agora = datetime.now(timezone.utc)
    pendentes = (
        await session.execute(
            select(Convite).where(
                Convite.email == dados.email,
                Convite.empresa_id == empresa_id,
                Convite.aceito_em.is_(None),
                Convite.expira_em > agora,
            )
        )
    ).scalars().all()
    for pendente in pendentes:
        pendente.expira_em = agora

    convite = Convite(
        email=dados.email,
        empresa_id=empresa_id,
        papel=papel,
        plano_id=dados.plano_id,
        token=secrets.token_urlsafe(32),
        expira_em=agora + timedelta(days=7),
        criado_por_usuario_id=contexto.usuario.id,
    )
    session.add(convite)
    await session.commit()
    await session.refresh(convite)

    settings = get_settings()
    link = f"{settings.app_base_url}/aceitar-convite?token={convite.token}"
    await enviar_convite(convite.email, link)

    return convite


@router.post("/aceitar", response_model=ConviteOut)
async def aceitar_convite(
    dados: ConviteAceitarIn,
    session: AsyncSession = Depends(get_db),
) -> Convite:
    convite = (
        await session.execute(select(Convite).where(Convite.token == dados.token))
    ).scalar_one_or_none()
    if convite is None:
        raise HTTPException(status_code=400, detail="Convite invalido")
    if convite.aceito_em is not None:
        raise HTTPException(status_code=400, detail="Convite ja foi aceito")
    if convite.expira_em <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Convite expirado")

    usuario = (
        await session.execute(select(Usuario).where(Usuario.email == convite.email))
    ).scalar_one_or_none()

    if usuario is None:
        if not dados.senha:
            raise HTTPException(status_code=422, detail="senha e obrigatoria para um novo usuario")
        usuario = Usuario(
            email=convite.email, senha_hash=hash_senha(dados.senha), plano_id=convite.plano_id,
        )
        session.add(usuario)
        await session.flush()
    elif convite.plano_id is not None:
        usuario.plano_id = convite.plano_id

    if convite.empresa_id is not None:
        vinculo_existente = (
            await session.execute(
                select(UsuarioEmpresa).where(
                    UsuarioEmpresa.usuario_id == usuario.id,
                    UsuarioEmpresa.empresa_id == convite.empresa_id,
                )
            )
        ).scalar_one_or_none()
        if vinculo_existente is not None:
            raise HTTPException(status_code=409, detail="Usuario ja tem acesso a essa empresa")
        session.add(
            UsuarioEmpresa(usuario_id=usuario.id, empresa_id=convite.empresa_id, papel=convite.papel)
        )

    convite.aceito_em = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(convite)
    return convite
