import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Cliente, ModeloDescricao
from app.schemas import ModeloDescricaoCriarIn, ModeloDescricaoOut
from app.security import ContextoAutenticado, get_empresa_ativa

router = APIRouter(prefix="/modelos-descricao", tags=["modelos-descricao"])


async def _validar_cliente(cliente_id: uuid.UUID | None, empresa_id: uuid.UUID, session: AsyncSession) -> None:
    if cliente_id is None:
        return
    cliente = await session.get(Cliente, cliente_id)
    if cliente is None or cliente.empresa_id != empresa_id:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")


@router.post("", response_model=ModeloDescricaoOut, status_code=201)
async def criar_modelo_descricao(
    dados: ModeloDescricaoCriarIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> ModeloDescricao:
    await _validar_cliente(dados.cliente_id, contexto.empresa_id, session)
    modelo = ModeloDescricao(empresa_id=contexto.empresa_id, **dados.model_dump())
    session.add(modelo)
    await session.commit()
    await session.refresh(modelo)
    return modelo


@router.get("", response_model=list[ModeloDescricaoOut])
async def listar_modelos_descricao(
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> list[ModeloDescricao]:
    stmt = (
        select(ModeloDescricao)
        .where(ModeloDescricao.empresa_id == contexto.empresa_id)
        .order_by(ModeloDescricao.titulo)
    )
    return list((await session.execute(stmt)).scalars().all())


@router.put("/{modelo_id}", response_model=ModeloDescricaoOut)
async def atualizar_modelo_descricao(
    modelo_id: uuid.UUID,
    dados: ModeloDescricaoCriarIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> ModeloDescricao:
    modelo = await session.get(ModeloDescricao, modelo_id)
    if modelo is None or modelo.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    await _validar_cliente(dados.cliente_id, contexto.empresa_id, session)
    for campo, valor in dados.model_dump().items():
        setattr(modelo, campo, valor)
    await session.commit()
    await session.refresh(modelo)
    return modelo


@router.delete("/{modelo_id}", status_code=204)
async def remover_modelo_descricao(
    modelo_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Response:
    modelo = await session.get(ModeloDescricao, modelo_id)
    if modelo is None or modelo.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    await session.delete(modelo)
    await session.commit()
    return Response(status_code=204)
