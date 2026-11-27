import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Produto
from app.schemas import ProdutoAtualizarIn, ProdutoCriarIn, ProdutoOut
from app.security import ContextoAutenticado, get_empresa_ativa

router = APIRouter(prefix="/produtos", tags=["produtos"])


@router.post("", response_model=ProdutoOut, status_code=201)
async def criar_produto(
    dados: ProdutoCriarIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Produto:
    produto = Produto(empresa_id=contexto.empresa_id, **dados.model_dump())
    session.add(produto)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Produto viola uma restricao de integridade")
    await session.refresh(produto)
    return produto


@router.get("", response_model=list[ProdutoOut])
async def listar_produtos(
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> list[Produto]:
    stmt = (
        select(Produto)
        .where(Produto.empresa_id == contexto.empresa_id)
        .order_by(Produto.descricao)
    )
    return list((await session.execute(stmt)).scalars().all())


@router.get("/{produto_id}", response_model=ProdutoOut)
async def obter_produto(
    produto_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Produto:
    produto = await session.get(Produto, produto_id)
    if produto is None or produto.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    return produto


@router.put("/{produto_id}", response_model=ProdutoOut)
async def atualizar_produto(
    produto_id: uuid.UUID,
    dados: ProdutoAtualizarIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Produto:
    produto = await session.get(Produto, produto_id)
    if produto is None or produto.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    for campo, valor in dados.model_dump().items():
        setattr(produto, campo, valor)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Produto viola uma restricao de integridade")
    await session.refresh(produto)
    return produto


@router.delete("/{produto_id}", status_code=204)
async def deletar_produto(
    produto_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Response:
    produto = await session.get(Produto, produto_id)
    if produto is None or produto.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    produto.ativo = False
    await session.commit()
    return Response(status_code=204)
