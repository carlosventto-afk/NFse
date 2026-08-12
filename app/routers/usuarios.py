from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import hash_senha
from app.db import get_db
from app.models import PapelUsuario, Usuario
from app.schemas import UsuarioCriarIn, UsuarioOut
from app.security import exigir_admin

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


@router.post("", response_model=UsuarioOut, status_code=201)
async def criar_usuario(
    dados: UsuarioCriarIn,
    admin: Usuario = Depends(exigir_admin),
    session: AsyncSession = Depends(get_db),
) -> Usuario:
    usuario = Usuario(
        empresa_id=admin.empresa_id,
        email=dados.email,
        senha_hash=hash_senha(dados.senha),
        papel=PapelUsuario(dados.papel),
    )
    session.add(usuario)
    await session.commit()
    await session.refresh(usuario)
    return usuario
