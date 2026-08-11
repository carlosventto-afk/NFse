from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Emissao, StatusEmissao, Usuario
from app.security import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(
    inicio: date = Query(...),
    fim: date = Query(...),
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(Emissao.status, func.coalesce(func.sum(Emissao.valor), 0))
        .where(
            Emissao.empresa_id == usuario.empresa_id,
            Emissao.criada_em >= inicio,
            Emissao.criada_em < fim + timedelta(days=1),
        )
        .group_by(Emissao.status)
    )
    linhas = (await session.execute(stmt)).all()

    totais: dict[str, Decimal] = {status.value: Decimal("0.00") for status in StatusEmissao}
    for status, soma in linhas:
        totais[status if isinstance(status, str) else status.value] = Decimal(soma).quantize(Decimal("0.01"))

    return {
        "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
        "totais_por_status": {chave: str(valor) for chave, valor in totais.items()},
        "total_autorizado": str(totais[StatusEmissao.autorizada.value]),
    }
