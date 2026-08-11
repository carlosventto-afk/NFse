from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.stone import parse_stone_charge_paid
from app.crypto import verificar_senha
from app.db import get_db
from app.models import Emissao, Empresa, OrigemEmissao, StatusEmissao
from app.numeracao import reservar_proximo_numero

router = APIRouter(prefix="/webhooks/stone", tags=["webhook-stone"])


@router.post("/{empresa_id}")
async def receber_webhook_stone(
    empresa_id: str,
    request: Request,
    x_webhook_token: str = Header(...),
    session: AsyncSession = Depends(get_db),
) -> dict:
    empresa = await session.get(Empresa, empresa_id)
    if empresa is None or not verificar_senha(x_webhook_token, empresa.webhook_token_hash):
        raise HTTPException(status_code=404)

    payload = await request.json()
    if payload.get("type") != "charge.paid":
        return {"ignorado": True}

    evento = parse_stone_charge_paid(payload)

    existente = (
        await session.execute(
            select(Emissao).where(
                Emissao.empresa_id == empresa.id, Emissao.stone_charge_id == evento.charge_id
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        return {"duplicado": True, "emissao_id": str(existente.id)}

    serie, numero = await reservar_proximo_numero(session, empresa.id)
    emissao = Emissao(
        empresa_id=empresa.id,
        origem=OrigemEmissao.webhook,
        stone_charge_id=evento.charge_id,
        status=StatusEmissao.pendente,
        serie=serie,
        numero=numero,
        tomador_nome=evento.customer_name,
        descricao=empresa.descricao_servico_padrao,
        valor=evento.valor,
        competencia=date.today().replace(day=1),
    )
    session.add(emissao)
    await session.commit()
    await session.refresh(emissao)
    return {"criado": True, "emissao_id": str(emissao.id)}
