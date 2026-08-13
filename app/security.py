import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import PapelUsuario, Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


@dataclass
class ContextoAutenticado:
    usuario: Usuario
    empresa_id: uuid.UUID | None
    papel: PapelUsuario | None
    eh_admin_plataforma: bool


def criar_token(
    usuario: Usuario,
    *,
    empresa_id: uuid.UUID | None = None,
    papel: PapelUsuario | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    payload = {
        "sub": str(usuario.id),
        "eh_admin_plataforma": bool(usuario.eh_admin_plataforma),
        "empresa_id": str(empresa_id) if empresa_id else None,
        "papel": PapelUsuario(papel).value if papel else None,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_horas),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def get_contexto_autenticado(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ContextoAutenticado:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        usuario_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Token invalido ou expirado")
    usuario = await session.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Usuario nao encontrado")

    empresa_id_str = payload.get("empresa_id")
    papel_str = payload.get("papel")
    return ContextoAutenticado(
        usuario=usuario,
        empresa_id=uuid.UUID(empresa_id_str) if empresa_id_str else None,
        papel=PapelUsuario(papel_str) if papel_str else None,
        eh_admin_plataforma=bool(payload.get("eh_admin_plataforma", False)),
    )


async def get_current_user(
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
) -> Usuario:
    return contexto.usuario


async def get_empresa_ativa(
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
) -> ContextoAutenticado:
    if contexto.empresa_id is None:
        raise HTTPException(status_code=409, detail="Selecione uma empresa antes de continuar")
    return contexto


async def exigir_admin_empresa(
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
) -> ContextoAutenticado:
    if contexto.papel != PapelUsuario.admin:
        raise HTTPException(status_code=403, detail="Somente administradores da empresa")
    return contexto


async def exigir_admin_plataforma(
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
) -> ContextoAutenticado:
    if not contexto.eh_admin_plataforma:
        raise HTTPException(status_code=403, detail="Somente administradores da plataforma")
    return contexto
