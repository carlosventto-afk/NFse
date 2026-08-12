import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import PapelUsuario, Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def criar_token(usuario: Usuario, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    payload = {
        "sub": str(usuario.id),
        "empresa_id": str(usuario.empresa_id),
        # papel pode chegar como PapelUsuario (recem-atribuido em memoria) ou
        # como str puro (coluna mapeada como String, sem coercao automatica ao
        # ler do banco) - PapelUsuario(...) normaliza os dois casos.
        "papel": PapelUsuario(usuario.papel).value,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_horas),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Usuario:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        usuario_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Token invalido ou expirado")
    usuario = await session.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Usuario nao encontrado")
    return usuario


async def exigir_admin(usuario: Usuario = Depends(get_current_user)) -> Usuario:
    if usuario.papel != PapelUsuario.admin:
        raise HTTPException(status_code=403, detail="Somente administradores")
    return usuario
