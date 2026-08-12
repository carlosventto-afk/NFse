from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import verificar_senha
from app.db import get_db
from app.models import Usuario
from app.schemas import TokenOut
from app.security import criar_token

router = APIRouter(prefix="/auth", tags=["auth"])


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
    return TokenOut(access_token=criar_token(usuario))
