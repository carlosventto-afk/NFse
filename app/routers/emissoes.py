import logging
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.stone_csv import CabecalhoInvalidoError, NotaCandidata, parsear_relatorio_stone
from app.config import Settings, get_settings
from app.crypto import decifrar
from app.danfe import gerar_danfse_fallback
from app.db import get_db
from app.models import AmbienteEnum, Cliente, Emissao, Empresa, OrigemEmissao, StatusEmissao
from app.numeracao import reservar_proximo_numero
from app.periodo import fim_do_dia_brt, inicio_do_dia_brt
from app.schemas import CancelarEmissaoIn, EmissaoManualIn, EmissaoOut
from app.security import ContextoAutenticado, exigir_admin_empresa, get_empresa_ativa
from nfse_core import SefinClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emissoes", tags=["emissoes"])


@router.post("/manual", response_model=EmissaoOut, status_code=201)
async def emitir_manual(
    dados: EmissaoManualIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Emissao:
    serie, numero = await reservar_proximo_numero(session, contexto.empresa_id)
    emissao = Emissao(
        empresa_id=contexto.empresa_id,
        origem=OrigemEmissao.manual,
        status=StatusEmissao.pendente,
        serie=serie,
        numero=numero,
        tomador_cpf_cnpj=dados.cpf_cnpj,
        tomador_nome=dados.nome,
        tomador_email=dados.email,
        descricao=dados.descricao,
        valor=dados.valor,
        competencia=dados.competencia,
        criada_por_usuario_id=contexto.usuario.id,
    )
    session.add(emissao)
    await session.commit()
    await session.refresh(emissao)
    return emissao


@router.get("", response_model=list[EmissaoOut])
async def listar_emissoes(
    status: StatusEmissao | None = Query(default=None),
    inicio: date | None = Query(default=None),
    fim: date | None = Query(default=None),
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> list[Emissao]:
    stmt = select(Emissao).where(Emissao.empresa_id == contexto.empresa_id)
    if status is not None:
        stmt = stmt.where(Emissao.status == status)
    # Limites ancorados em BRT: `criada_em` e timestamptz e comparar com um
    # `date` cru deixaria o Postgres converter pelo TimeZone da sessao (UTC),
    # jogando as notas do fim da noite para o dia/mes seguinte. Ver app/periodo.py.
    if inicio is not None:
        stmt = stmt.where(Emissao.criada_em >= inicio_do_dia_brt(inicio))
    if fim is not None:
        stmt = stmt.where(Emissao.criada_em < fim_do_dia_brt(fim))
    stmt = stmt.order_by(Emissao.criada_em.desc())
    return list((await session.execute(stmt)).scalars().all())


@router.get("/{emissao_id}/xml")
async def baixar_xml(
    emissao_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Response:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    if emissao.status != StatusEmissao.autorizada or not emissao.xml_nfse:
        raise HTTPException(status_code=404, detail="XML autorizado nao disponivel")
    return Response(
        content=emissao.xml_nfse, media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{emissao.chave_acesso}.xml"'},
    )


@router.get("/{emissao_id}/pdf")
async def baixar_pdf(
    emissao_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    if emissao.status != StatusEmissao.autorizada:
        raise HTTPException(status_code=404, detail="Nota nao autorizada")

    empresa = await session.get(Empresa, emissao.empresa_id)

    # AmbienteEnum(...) normaliza o valor recem-carregado do banco — ver
    # comentario equivalente no worker.py (Task 10) e o bug original na Task 5.
    #
    # `fetch_danfse_pdf` promete devolver None em vez de levantar quando o ADN
    # nao responde, mas antes disso ela chama load_pfx_pem, que levanta
    # CertificateError com certificado vencido/senha errada — e `decifrar`
    # levanta InvalidToken se a FERNET_KEY nao bater. O except e
    # deliberadamente amplo: QUALQUER falha em alcancar o PDF oficial deve cair
    # no fallback local, que nem precisa do certificado — a razao de existir do
    # fallback e o usuario sempre receber um PDF, nunca um 500
    # (ARMADILHAS.md item 10).
    try:
        pfx_base64 = decifrar(empresa.certificado_pfx_cifrado, settings.fernet_key)
        senha = (
            decifrar(empresa.certificado_senha_cifrada, settings.fernet_key)
            if empresa.certificado_senha_cifrada
            else None
        )
        pdf = await SefinClient.fetch_danfse_pdf(
            AmbienteEnum(empresa.ambiente).value, pfx_base64, senha, emissao.chave_acesso
        )
    except Exception:
        logger.warning(
            "falha ao buscar o DANFSe oficial da emissao %s; usando o fallback local",
            emissao.id, exc_info=True,
        )
        pdf = None
    if pdf is None:
        pdf = gerar_danfse_fallback(emissao, empresa)
    return Response(content=pdf, media_type="application/pdf")


async def _obter_ou_criar_cliente_padrao_csv(session: AsyncSession, empresa_id: uuid.UUID) -> Cliente:
    cliente = (
        await session.execute(
            select(Cliente).where(Cliente.empresa_id == empresa_id, Cliente.eh_padrao_csv.is_(True))
        )
    ).scalar_one_or_none()
    if cliente is None:
        cliente = Cliente(
            empresa_id=empresa_id, nome="Cliente nao identificado (importacao CSV)",
            eh_padrao_csv=True,
        )
        session.add(cliente)
        await session.flush()
    return cliente


async def _processar_csv(
    conteudo: bytes, contexto: ContextoAutenticado, session: AsyncSession, *, confirmar: bool,
) -> dict:
    try:
        resultado = parsear_relatorio_stone(conteudo)
    except CabecalhoInvalidoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ignoradas = dict(resultado.ignoradas)
    ignoradas["ja_emitida_anteriormente"] = 0

    stone_ids = [nota.stone_charge_id for nota in resultado.notas]
    existentes: set[str] = set()
    if stone_ids:
        linhas = await session.execute(
            select(Emissao.stone_charge_id).where(
                Emissao.empresa_id == contexto.empresa_id,
                Emissao.stone_charge_id.in_(stone_ids),
            )
        )
        existentes = {linha[0] for linha in linhas}

    notas_validas: list[NotaCandidata] = []
    for nota in resultado.notas:
        if nota.stone_charge_id in existentes:
            ignoradas["ja_emitida_anteriormente"] += 1
            continue
        notas_validas.append(nota)

    if confirmar and notas_validas:
        empresa = await session.get(Empresa, contexto.empresa_id)
        cliente_padrao = await _obter_ou_criar_cliente_padrao_csv(session, contexto.empresa_id)
        for nota in notas_validas:
            serie, numero = await reservar_proximo_numero(session, contexto.empresa_id)
            emissao = Emissao(
                empresa_id=contexto.empresa_id,
                origem=OrigemEmissao.csv,
                stone_charge_id=nota.stone_charge_id,
                status=StatusEmissao.pendente,
                serie=serie,
                numero=numero,
                cliente_id=cliente_padrao.id,
                descricao=empresa.descricao_servico_padrao,
                valor=nota.valor,
                competencia=nota.data_da_venda.date().replace(day=1),
                criada_por_usuario_id=contexto.usuario.id,
            )
            session.add(emissao)
        await session.commit()

    valor_total = sum((nota.valor for nota in notas_validas), Decimal("0"))
    return {
        "total_notas": len(notas_validas),
        "valor_total": str(valor_total.quantize(Decimal("0.01"))),
        "ignoradas": ignoradas,
    }


@router.post("/csv/preview")
async def preview_csv(
    arquivo: UploadFile = File(...),
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> dict:
    conteudo = await arquivo.read()
    return await _processar_csv(conteudo, contexto, session, confirmar=False)


@router.post("/csv/confirmar")
async def confirmar_csv(
    arquivo: UploadFile = File(...),
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> dict:
    conteudo = await arquivo.read()
    return await _processar_csv(conteudo, contexto, session, confirmar=True)


@router.post("/{emissao_id}/cancelar", response_model=EmissaoOut)
async def cancelar_emissao(
    emissao_id: uuid.UUID,
    dados: CancelarEmissaoIn,
    contexto: ContextoAutenticado = Depends(exigir_admin_empresa),
    session: AsyncSession = Depends(get_db),
) -> Emissao:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    if emissao.status != StatusEmissao.autorizada:
        raise HTTPException(
            status_code=409, detail=f"So e possivel cancelar uma emissao autorizada (status atual: {emissao.status})"
        )
    emissao.status = StatusEmissao.cancelamento_pendente
    emissao.motivo_cancelamento = dados.motivo
    await session.commit()
    await session.refresh(emissao)
    return emissao
