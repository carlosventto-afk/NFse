"""Endpoints da NF-e modelo 55 (mercadorias).

Espelha app/routers/emissoes.py (NFS-e): a criacao so grava a linha em
`aguardando_emissao` -- quem monta, assina e envia a SEFAZ e o worker
(processar_uma_pendente_nfe em app/worker.py), do mesmo jeito que a NFS-e.
"""
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.nfe_builder import _arredondar
from app.danfe_nfe import gerar_danfe_fallback
from app.db import get_db
from app.models import Cliente, EmissaoNfe, Empresa, ItemEmissaoNfe, Produto, StatusEmissao
from app.numeracao import reservar_proximo_numero_nfe
from app.schemas import (
    VALOR_MAXIMO, CancelarEmissaoNfeIn, EmissaoNfeIn, EmissaoNfeOut, ItemEmissaoNfeOut,
)
from app.security import ContextoAutenticado, exigir_admin_empresa, get_empresa_ativa

router = APIRouter(prefix="/emissoes-nfe", tags=["emissoes-nfe"])


async def _obter_emissao_da_empresa(
    session: AsyncSession, emissao_id: uuid.UUID, empresa_id: uuid.UUID,
) -> EmissaoNfe:
    emissao = await session.get(EmissaoNfe, emissao_id)
    if emissao is None or emissao.empresa_id != empresa_id:
        raise HTTPException(status_code=404)
    return emissao


async def _serializar(session: AsyncSession, emissoes: list[EmissaoNfe]) -> list[EmissaoNfeOut]:
    # Sem relationship ORM entre EmissaoNfe e ItemEmissaoNfe (ver danfe_nfe.py):
    # uma unica consulta pros itens de todas as emissoes, agrupados aqui.
    itens_por_emissao: dict[uuid.UUID, list[ItemEmissaoNfe]] = defaultdict(list)
    if emissoes:
        itens = (await session.execute(
            select(ItemEmissaoNfe)
            .where(ItemEmissaoNfe.emissao_nfe_id.in_([e.id for e in emissoes]))
            .order_by(ItemEmissaoNfe.id)
        )).scalars().all()
        for item in itens:
            itens_por_emissao[item.emissao_nfe_id].append(item)

    saida = []
    for emissao in emissoes:
        out = EmissaoNfeOut.model_validate(emissao)
        out.itens = [ItemEmissaoNfeOut.model_validate(i) for i in itens_por_emissao[emissao.id]]
        saida.append(out)
    return saida


@router.post("", response_model=EmissaoNfeOut, status_code=201)
async def criar_emissao_nfe(
    dados: EmissaoNfeIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> EmissaoNfeOut:
    cliente = await session.get(Cliente, dados.cliente_id)
    if cliente is None or cliente.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado")
    if not cliente.ativo:
        raise HTTPException(status_code=422, detail="Cliente inativo")

    ids_produtos = {item.produto_id for item in dados.itens}
    produtos_por_id = {
        produto.id: produto
        for produto in (await session.execute(
            select(Produto).where(Produto.id.in_(ids_produtos), Produto.empresa_id == contexto.empresa_id)
        )).scalars().all()
    }
    if len(produtos_por_id) != len(ids_produtos):
        raise HTTPException(status_code=404, detail="Produto nao encontrado")

    # Resolve preco e CFOP AGORA, com exatamente a mesma regra de
    # app/adapters/nfe_builder.py:_montar_item. O worker (_montar_e_assinar_nfe)
    # le ItemEmissaoNfe.valor_unitario/.cfop de volta e os repassa ao builder
    # como overrides ja resolvidos -- nao reaplica fallback nenhum. Assim o
    # preco fica congelado no momento do pedido, mesmo que o cadastro do
    # produto mude depois.
    itens_resolvidos = []
    for n_item, item in enumerate(dados.itens, start=1):
        produto = produtos_por_id[item.produto_id]
        if not produto.ativo:
            raise HTTPException(status_code=422, detail=f"Item {n_item}: produto '{produto.descricao}' esta inativo")
        valor_unitario = item.valor_unitario_override
        if valor_unitario is None:
            valor_unitario = produto.valor_unitario_padrao
        if valor_unitario is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Item {n_item}: produto '{produto.descricao}' nao tem valor_unitario_padrao "
                    "cadastrado e o item nao informou valor_unitario_override"
                ),
            )
        valor_total = _arredondar(item.quantidade * valor_unitario)
        if valor_total > VALOR_MAXIMO:
            raise HTTPException(status_code=422, detail=f"Item {n_item}: valor_total excede o maximo permitido")
        itens_resolvidos.append(dict(
            produto_id=item.produto_id,
            quantidade=item.quantidade,
            valor_unitario=valor_unitario,
            valor_total=valor_total,
            cfop=item.cfop_override or produto.cfop_padrao,
            aliquota_interna_destino=item.aliquota_interna_destino,
        ))

    # So reserva o numero depois de validar tudo -- nada de queimar numero
    # numa requisicao que vai ser recusada.
    serie, numero = await reservar_proximo_numero_nfe(session, contexto.empresa_id)
    emissao = EmissaoNfe(
        empresa_id=contexto.empresa_id,
        cliente_id=cliente.id,
        serie=serie,
        numero=numero,
        status=StatusEmissao.aguardando_emissao,
    )
    session.add(emissao)
    await session.flush()

    # O worker ordena os itens por ItemEmissaoNfe.id pra numerar o nItem; com
    # uuid4 aleatorio a ordem do pedido se perderia. Ids gerados e ORDENADOS
    # (Python e Postgres comparam uuid pelos mesmos 16 bytes big-endian)
    # preservam a ordem do pedido sem coluna extra.
    ids_itens = sorted(uuid.uuid4() for _ in itens_resolvidos)
    for id_item, item in zip(ids_itens, itens_resolvidos):
        session.add(ItemEmissaoNfe(id=id_item, emissao_nfe_id=emissao.id, **item))
    await session.commit()
    await session.refresh(emissao)
    return (await _serializar(session, [emissao]))[0]


@router.get("", response_model=list[EmissaoNfeOut])
async def listar_emissoes_nfe(
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> list[EmissaoNfeOut]:
    stmt = (
        select(EmissaoNfe)
        .where(EmissaoNfe.empresa_id == contexto.empresa_id)
        .order_by(EmissaoNfe.criado_em.desc())
    )
    emissoes = list((await session.execute(stmt)).scalars().all())
    return await _serializar(session, emissoes)


@router.get("/{emissao_id}/xml")
async def baixar_xml_nfe(
    emissao_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Response:
    emissao = await _obter_emissao_da_empresa(session, emissao_id, contexto.empresa_id)
    # Sem restricao de status (mesma filosofia de _obter_xml da NFS-e): o XML
    # enviado vale como evidencia ate numa nota rejeitada. So nao existe
    # antes da primeira tentativa do worker.
    if emissao.xml_nfe is None:
        raise HTTPException(status_code=404, detail="XML nao disponivel para esta emissao")
    return Response(
        content=emissao.xml_nfe, media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="NFe_{emissao.serie}_{emissao.numero}.xml"'},
    )


@router.get("/{emissao_id}/pdf")
async def baixar_pdf_nfe(
    emissao_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Response:
    emissao = await _obter_emissao_da_empresa(session, emissao_id, contexto.empresa_id)
    if emissao.status != StatusEmissao.autorizada:
        raise HTTPException(status_code=404, detail="Nota nao autorizada")

    empresa = await session.get(Empresa, emissao.empresa_id)
    cliente = await session.get(Cliente, emissao.cliente_id)
    itens_db = (await session.execute(
        select(ItemEmissaoNfe).where(ItemEmissaoNfe.emissao_nfe_id == emissao.id).order_by(ItemEmissaoNfe.id)
    )).scalars().all()
    itens = [(item, await session.get(Produto, item.produto_id)) for item in itens_db]
    pdf = gerar_danfe_fallback(emissao, empresa, cliente, itens)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="NFe_{emissao.serie}_{emissao.numero}.pdf"'},
    )


@router.post("/{emissao_id}/cancelar", response_model=EmissaoNfeOut)
async def cancelar_emissao_nfe(
    emissao_id: uuid.UUID,
    dados: CancelarEmissaoNfeIn,
    contexto: ContextoAutenticado = Depends(exigir_admin_empresa),
    session: AsyncSession = Depends(get_db),
) -> EmissaoNfeOut:
    emissao = await _obter_emissao_da_empresa(session, emissao_id, contexto.empresa_id)
    if emissao.status != StatusEmissao.autorizada:
        raise HTTPException(
            status_code=409,
            detail=f"So e possivel cancelar uma NF-e autorizada (status atual: {emissao.status})",
        )
    # So registra o pedido: o envio do evento de cancelamento a SEFAZ
    # (nfe_core.evento.build_evento_cancelamento_nfe_xml) ainda nao tem
    # worker -- a linha fica em cancelamento_pendente ate isso existir.
    emissao.status = StatusEmissao.cancelamento_pendente
    emissao.justificativa_cancelamento = dados.justificativa
    await session.commit()
    await session.refresh(emissao)
    return (await _serializar(session, [emissao]))[0]
