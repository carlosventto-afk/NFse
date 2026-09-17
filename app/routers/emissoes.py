import io
import logging
import uuid
import zipfile
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.spedy_client import SpedyClient
from app.adapters.stone_csv import CabecalhoInvalidoError, NotaCandidata, parsear_relatorio_stone
from app.config import Settings, get_settings
from app.crypto import decifrar
from app.danfe import gerar_danfse_fallback
from app.db import get_db
from app.models import AmbienteEnum, Cliente, Emissao, Empresa, OrigemEmissao, ProvedorEmissao, StatusEmissao
from app.numeracao import reservar_proximo_numero
from app.periodo import FUSO_BRT, fim_do_dia_brt, inicio_do_dia_brt
from app.schemas import (
    CancelarEmissaoIn, EmissaoLoteOut, EmissaoManualIn, EmissaoOut, EmissoesIdsIn, ExclusaoLoteOut,
)
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


async def _obter_xml(emissao: Emissao, empresa: Empresa, settings: Settings) -> tuple[bytes, str] | None:
    # Autorizada: devolve o XML oficial da NFS-e. No provedor Spedy esse XML
    # nunca fica guardado no nosso banco — a Spedy assina do lado dela —
    # entao busca sob demanda em /service-invicoes/{id}/xml (mesmo padrao do
    # PDF). No provedor direto o worker ja grava o XML da SEFIN na emissao.
    if emissao.status == StatusEmissao.autorizada:
        nome_arquivo = f"NFSe_{emissao.serie}_{emissao.numero}.xml"
        if ProvedorEmissao(empresa.provedor_emissao) == ProvedorEmissao.spedy:
            api_key = decifrar(empresa.spedy_api_key_cifrada, settings.fernet_key)
            cliente_spedy = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
            try:
                xml = await cliente_spedy.baixar_xml(emissao.spedy_nota_id)
            except Exception:
                logger.warning(
                    "falha ao buscar o XML da NFS-e na Spedy para a emissao %s", emissao.id, exc_info=True,
                )
                return None
            finally:
                await cliente_spedy.close()
            return xml, nome_arquivo
        if emissao.xml_nfse:
            return emissao.xml_nfse, nome_arquivo
        return None
    # Rejeitada: nao existe NFS-e — devolve o XML da DPS que foi assinado e
    # submetido, util pra conferir o que exatamente foi enviado/recusado. So
    # existe no provedor direto (a Spedy nunca expoe a DPS pro cliente).
    if emissao.status == StatusEmissao.rejeitada and emissao.xml_dps:
        return emissao.xml_dps, f"DPS_{emissao.serie}_{emissao.numero}.xml"
    return None


@router.get("/{emissao_id}/xml")
async def baixar_xml(
    emissao_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)

    empresa = await session.get(Empresa, emissao.empresa_id)
    resultado = await _obter_xml(emissao, empresa, settings)
    if resultado is None:
        raise HTTPException(status_code=404, detail="XML nao disponivel para esta emissao")
    conteudo, nome_arquivo = resultado

    return Response(
        content=conteudo, media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@router.post("/download-xmls")
async def baixar_xmls_em_lote(
    dados: EmissoesIdsIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    stmt = select(Emissao).where(Emissao.id.in_(dados.ids), Emissao.empresa_id == contexto.empresa_id)
    emissoes = list((await session.execute(stmt)).scalars().all())

    buffer = io.BytesIO()
    adicionados = 0
    if emissoes:
        empresa = await session.get(Empresa, contexto.empresa_id)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_arquivo:
            for emissao in emissoes:
                resultado = await _obter_xml(emissao, empresa, settings)
                if resultado is None:
                    continue
                conteudo, nome_arquivo = resultado
                zip_arquivo.writestr(nome_arquivo, conteudo)
                adicionados += 1

    if adicionados == 0:
        raise HTTPException(status_code=404, detail="Nenhum XML disponivel para os itens selecionados")

    return Response(
        content=buffer.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="notas_xml.zip"'},
    )


@router.get("/{emissao_id}/resposta-bruta")
async def baixar_resposta_bruta(
    emissao_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Response:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != contexto.empresa_id or not emissao.resposta_bruta:
        raise HTTPException(status_code=404, detail="Resposta bruta nao disponivel para esta emissao")

    return Response(
        content=emissao.resposta_bruta, media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="RESPOSTA_{emissao.serie}_{emissao.numero}.json"'
        },
    )


async def _gerar_pdf_bytes(emissao: Emissao, empresa: Empresa, settings: Settings) -> bytes:
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
        if ProvedorEmissao(empresa.provedor_emissao) == ProvedorEmissao.spedy:
            api_key = decifrar(empresa.spedy_api_key_cifrada, settings.fernet_key)
            cliente_spedy = SpedyClient(AmbienteEnum(empresa.ambiente).value, api_key)
            try:
                pdf = await cliente_spedy.baixar_pdf(emissao.spedy_nota_id)
            finally:
                await cliente_spedy.close()
        else:
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
    return pdf


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
    pdf = await _gerar_pdf_bytes(emissao, empresa, settings)
    return Response(content=pdf, media_type="application/pdf")


@router.post("/download-pdfs")
async def baixar_pdfs_em_lote(
    dados: EmissoesIdsIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    stmt = select(Emissao).where(
        Emissao.id.in_(dados.ids),
        Emissao.empresa_id == contexto.empresa_id,
        Emissao.status == StatusEmissao.autorizada,
    )
    emissoes = list((await session.execute(stmt)).scalars().all())

    buffer = io.BytesIO()
    adicionados = 0
    if emissoes:
        empresa = await session.get(Empresa, contexto.empresa_id)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_arquivo:
            for emissao in emissoes:
                pdf = await _gerar_pdf_bytes(emissao, empresa, settings)
                zip_arquivo.writestr(f"NFSe_{emissao.serie}_{emissao.numero}.pdf", pdf)
                adicionados += 1

    if adicionados == 0:
        raise HTTPException(status_code=404, detail="Nenhum PDF disponivel para os itens selecionados")

    return Response(
        content=buffer.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="notas_pdf.zip"'},
    )


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
                status=StatusEmissao.aguardando_emissao,
                serie=serie,
                numero=numero,
                cliente_id=cliente_padrao.id,
                descricao=(
                    f"{empresa.descricao_servico_padrao} - "
                    f"Vencimento: {nota.data_vencimento:%d/%m/%Y}"
                ),
                valor=nota.valor,
                competencia=nota.data_vencimento.replace(day=1),
                dh_emi_original=nota.data_ultimo_status.replace(tzinfo=FUSO_BRT),
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


def _pode_excluir(emissao: Emissao, empresa: Empresa) -> bool:
    # Autorizada so pode ser excluida em homologacao — la e so nota de teste,
    # sem efeito fiscal real. Em producao a nota autorizada e um documento
    # fiscal de verdade: so pode ser cancelada (/cancelar), nunca apagada.
    if emissao.status == StatusEmissao.autorizada:
        return AmbienteEnum(empresa.ambiente) == AmbienteEnum.homologacao
    return emissao.status in (
        StatusEmissao.pendente, StatusEmissao.rejeitada, StatusEmissao.aguardando_emissao,
    )


@router.delete("/{emissao_id}", status_code=204)
async def excluir_emissao(
    emissao_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(exigir_admin_empresa),
    session: AsyncSession = Depends(get_db),
) -> None:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)

    empresa = await session.get(Empresa, emissao.empresa_id)
    if not _pode_excluir(emissao, empresa):
        detalhe = (
            "Nota autorizada em producao so pode ser cancelada, nao excluida"
            if emissao.status == StatusEmissao.autorizada
            else (
                "So e possivel excluir emissao aguardando emissao, pendente, rejeitada, ou "
                f"autorizada em homologacao (status atual: {emissao.status})"
            )
        )
        raise HTTPException(status_code=409, detail=detalhe)
    await session.delete(emissao)
    await session.commit()


@router.post("/excluir-lote", response_model=ExclusaoLoteOut)
async def excluir_emissoes_em_lote(
    dados: EmissoesIdsIn,
    contexto: ContextoAutenticado = Depends(exigir_admin_empresa),
    session: AsyncSession = Depends(get_db),
) -> ExclusaoLoteOut:
    stmt = select(Emissao).where(Emissao.id.in_(dados.ids), Emissao.empresa_id == contexto.empresa_id)
    emissoes = list((await session.execute(stmt)).scalars().all())
    empresa = await session.get(Empresa, contexto.empresa_id)

    excluidas = 0
    for emissao in emissoes:
        if not _pode_excluir(emissao, empresa):
            continue
        await session.delete(emissao)
        excluidas += 1
    await session.commit()
    return ExclusaoLoteOut(excluidas=excluidas, puladas=len(dados.ids) - excluidas)


@router.post("/{emissao_id}/emitir", response_model=EmissaoOut)
async def emitir_emissao(
    emissao_id: uuid.UUID,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> Emissao:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != contexto.empresa_id:
        raise HTTPException(status_code=404)
    if emissao.status not in (StatusEmissao.aguardando_emissao, StatusEmissao.rejeitada):
        raise HTTPException(
            status_code=409,
            detail=(
                "So e possivel emitir/reemitir nota aguardando emissao ou rejeitada "
                f"(status atual: {emissao.status})"
            ),
        )
    # So muda o status pra "pendente" -- o worker (loop_worker) e quem de
    # fato processa, do mesmo jeito que ja faz pra emissao manual/webhook.
    # Evita duplicar a logica de emissao aqui e mantem o request rapido (nao
    # bloqueia esperando a SEFIN/Spedy responder).
    emissao.status = StatusEmissao.pendente
    await session.commit()
    await session.refresh(emissao)
    return emissao


@router.post("/emitir-lote", response_model=EmissaoLoteOut)
async def emitir_emissoes_em_lote(
    dados: EmissoesIdsIn,
    contexto: ContextoAutenticado = Depends(get_empresa_ativa),
    session: AsyncSession = Depends(get_db),
) -> EmissaoLoteOut:
    stmt = select(Emissao).where(Emissao.id.in_(dados.ids), Emissao.empresa_id == contexto.empresa_id)
    emissoes = list((await session.execute(stmt)).scalars().all())

    emitidas = 0
    for emissao in emissoes:
        if emissao.status not in (StatusEmissao.aguardando_emissao, StatusEmissao.rejeitada):
            continue
        emissao.status = StatusEmissao.pendente
        emitidas += 1
    await session.commit()
    return EmissaoLoteOut(emitidas=emitidas, puladas=len(dados.ids) - emitidas)
