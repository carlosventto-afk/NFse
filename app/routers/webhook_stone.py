import uuid
from datetime import date

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.stone import parse_stone_charge_paid
from app.crypto import verificar_senha
from app.db import get_db
from app.models import Emissao, Empresa, OrigemEmissao, StatusEmissao
from app.numeracao import reservar_proximo_numero

router = APIRouter(prefix="/webhooks/stone", tags=["webhook-stone"])

# Hash bcrypt "de mentira", calculado uma unica vez no import. Usado quando a
# empresa nao existe, para que `verificar_senha` sempre rode contra um hash
# de formato real — assim "empresa inexistente" e "token errado" respondem
# em tempo comparavel e nao viram um oraculo de timing para o 404 identico.
_HASH_FALSO = bcrypt.hashpw(b"dummy", bcrypt.gensalt()).decode()


@router.post("/{empresa_id}")
async def receber_webhook_stone(
    # uuid.UUID (e nao str): o FastAPI recusa um valor mal formado com 422
    # antes de chegar aqui. Com `str`, o valor ia cru para o session.get() e
    # virava asyncpg.DataError (500) — e antes da checagem do token, o que
    # tambem furava o 404 de tempo constante logo abaixo (dava para separar
    # "UUID mal formado" de "UUID valido porem inexistente").
    empresa_id: uuid.UUID,
    request: Request,
    x_webhook_token: str = Header(...),
    session: AsyncSession = Depends(get_db),
) -> dict:
    empresa = await session.get(Empresa, empresa_id)
    hash_para_comparar = empresa.webhook_token_hash if empresa is not None else _HASH_FALSO
    token_valido = verificar_senha(x_webhook_token, hash_para_comparar)
    if empresa is None or not token_valido:
        raise HTTPException(status_code=404)

    payload = await request.json()
    if payload.get("type") != "charge.paid":
        return {"ignorado": True}

    # parse_stone_charge_paid levanta ValueError quando falta um campo
    # documentado. Deixar escapar viraria 500 — e a Stone REENVIA 5xx, entao um
    # payload permanentemente malformado viraria retry infinito. 400 diz "nao
    # reenvie, o problema esta no corpo".
    try:
        evento = parse_stone_charge_paid(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        # Emissao.tomador_nome e String(300) e o nome vem de fora: sem o corte,
        # um nome maior estoura StringDataRightTruncationError (500) no insert.
        tomador_nome=evento.customer_name[:300],
        descricao=empresa.descricao_servico_padrao,
        valor=evento.valor,
        competencia=date.today().replace(day=1),
    )
    session.add(emissao)
    await session.commit()
    await session.refresh(emissao)
    return {"criado": True, "emissao_id": str(emissao.id)}
