from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Emissao, StatusEmissao
from app.periodo import fim_do_dia_brt, inicio_do_dia_brt
from app.security import ContextoAutenticado, get_empresa_ativa

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(
    inicio: date = Query(...),
    fim: date = Query(...),
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(Emissao.status, func.coalesce(func.sum(Emissao.valor), 0))
        .where(
            Emissao.empresa_id == contexto.empresa_id,
            # Limites em BRT, nao no TimeZone da sessao do Postgres (UTC):
            # sem isso, a nota das 21:30 BRT do dia 31 cai no mes seguinte.
            # Ver app/periodo.py.
            Emissao.criada_em >= inicio_do_dia_brt(inicio),
            Emissao.criada_em < fim_do_dia_brt(fim),
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
