import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Cliente
from app.schemas import ClienteAtualizarIn, ClienteCriarIn, ClienteOut
from app.security import ContextoAutenticado, get_empresa_ativa

router = APIRouter(prefix="/clientes", tags=["clientes"])


@router.post("", response_model=ClienteOut, status_code=201)
async def criar_cliente(
    dados: ClienteCriarIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Cliente:
    cliente = Cliente(empresa_id=contexto.empresa_id, **dados.model_dump())
    session.add(cliente)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Ja existe um cliente com esse CPF/CNPJ")
    await session.refresh(cliente)
    return cliente


@router.get("", response_model=list[ClienteOut])
async def listar_clientes(
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> list[Cliente]:
    stmt = (
        select(Cliente)
        .where(Cliente.empresa_id == contexto.empresa_id, Cliente.eh_padrao_csv.is_(False))
        .order_by(Cliente.nome)
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("/{cliente_id}", response_model=ClienteOut)
async def obter_cliente(
    cliente_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Cliente:
    cliente = await session.get(Cliente, cliente_id)
    if cliente is None or cliente.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    return cliente


@router.put("/{cliente_id}", response_model=ClienteOut)
async def atualizar_cliente(
    cliente_id: uuid.UUID,
    dados: ClienteAtualizarIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Cliente:
    cliente = await session.get(Cliente, cliente_id)
    if cliente is None or cliente.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    for campo, valor in dados.model_dump().items():
        setattr(cliente, campo, valor)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Ja existe um cliente com esse CPF/CNPJ")
    await session.refresh(cliente)
    return cliente
