from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import hash_senha
from app.db import get_db
from app.models import Usuario
from app.schemas import UsuarioCriarIn, UsuarioOut
from app.security import ContextoAutenticado, exigir_admin_plataforma

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.post("", response_model=UsuarioOut, status_code=201)
async def criar_usuario(
    dados: UsuarioCriarIn,
    contexto: ContextoAutenticado = Depends(exigir_admin_plataforma),
    session: AsyncSession = Depends(get_db),
) -> Usuario:
    existente = (
        await session.execute(select(Usuario).where(Usuario.email == dados.email))
    ).scalar_one_or_none()
    if existente is not None:
        raise HTTPException(status_code=409, detail="Ja existe um usuario com esse e-mail")

    usuario = Usuario(
        email=dados.email, senha_hash=hash_senha(dados.senha), plano_id=dados.plano_id,
    )
    session.add(usuario)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=422, detail="Nao foi possivel criar o usuario (e-mail ja usado ou plano invalido)"
        )
    await session.refresh(usuario)
    return usuario
