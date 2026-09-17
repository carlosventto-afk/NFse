from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Plano
from app.schemas import PlanoOut
from app.security import ContextoAutenticado, exigir_admin_plataforma

router = APIRouter(prefix="/planos", tags=["planos"])


@router.get("", response_model=list[PlanoOut])
async def listar_planos(
    contexto: ContextoAutenticado = Depends(exigir_admin_plataforma),
    session: AsyncSession = Depends(get_db),
) -> list[Plano]:
    return list((await session.execute(select(Plano).order_by(Plano.nome))).scalars().all())
