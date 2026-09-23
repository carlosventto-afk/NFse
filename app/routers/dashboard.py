import calendar
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


def _linhas_agrupadas(linhas) -> list[dict]:
    return [
        {
            "chave": chave if isinstance(chave, str) or chave is None else chave.value,
            "quantidade": quantidade,
            "valor": str(Decimal(valor).quantize(Decimal("0.01"))),
        }
        for chave, quantidade, valor in linhas
    ]


@router.get("/resumo")
async def resumo(
    competencia: date = Query(..., description="Qualquer dia dentro do mes desejado"),
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> dict:
    inicio_mes = competencia.replace(day=1)
    ultimo_dia = calendar.monthrange(inicio_mes.year, inicio_mes.month)[1]
    fim_mes = inicio_mes.replace(day=ultimo_dia)

    filtro_competencia = (
        Emissao.empresa_id == contexto.empresa_id,
        Emissao.competencia >= inicio_mes,
        Emissao.competencia <= fim_mes,
    )

    total_notas, valor_total = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Emissao.valor), 0)).where(*filtro_competencia)
        )
    ).one()

    por_status = (
        await session.execute(
            select(Emissao.status, func.count(), func.coalesce(func.sum(Emissao.valor), 0))
            .where(*filtro_competencia)
            .group_by(Emissao.status)
        )
    ).all()

    por_tipo_produto = (
        await session.execute(
            select(Emissao.tipo_produto, func.count(), func.coalesce(func.sum(Emissao.valor), 0))
            .where(*filtro_competencia)
            .group_by(Emissao.tipo_produto)
        )
    ).all()

    por_bandeira = (
        await session.execute(
            select(Emissao.bandeira, func.count(), func.coalesce(func.sum(Emissao.valor), 0))
            .where(*filtro_competencia)
            .group_by(Emissao.bandeira)
        )
    ).all()

    # Serie diaria usa `data_vencimento` (= data da venda nas notas importadas
    # da Stone) -- notas manuais/webhook, sem essa data, ficam de fora do
    # grafico (nao tem "dia de venda").
    serie_diaria = (
        await session.execute(
            select(Emissao.data_vencimento, func.count(), func.coalesce(func.sum(Emissao.valor), 0))
            .where(*filtro_competencia, Emissao.data_vencimento.is_not(None))
            .group_by(Emissao.data_vencimento)
            .order_by(Emissao.data_vencimento)
        )
    ).all()

    return {
        "competencia": inicio_mes.isoformat(),
        "total_notas": total_notas,
        "valor_total": str(Decimal(valor_total).quantize(Decimal("0.01"))),
        "por_status": _linhas_agrupadas(por_status),
        "por_tipo_produto": _linhas_agrupadas(por_tipo_produto),
        "por_bandeira": _linhas_agrupadas(por_bandeira),
        "serie_diaria": [
            {
                "data": data.isoformat(),
                "quantidade": quantidade,
                "valor": str(Decimal(valor).quantize(Decimal("0.01"))),
            }
            for data, quantidade, valor in serie_diaria
        ],
    }


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
