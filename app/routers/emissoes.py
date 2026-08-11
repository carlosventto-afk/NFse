import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.crypto import decifrar
from app.danfe import gerar_danfse_fallback
from app.db import get_db
from app.models import AmbienteEnum, Emissao, Empresa, OrigemEmissao, StatusEmissao, Usuario
from app.numeracao import reservar_proximo_numero
from app.schemas import EmissaoManualIn, EmissaoOut
from app.security import get_current_user
from nfse_core import SefinClient

router = APIRouter(prefix="/emissoes", tags=["emissoes"])


@router.post("/manual", response_model=EmissaoOut, status_code=201)
async def emitir_manual(
    dados: EmissaoManualIn,
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Emissao:
    serie, numero = await reservar_proximo_numero(session, usuario.empresa_id)
    emissao = Emissao(
        empresa_id=usuario.empresa_id,
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
        criada_por_usuario_id=usuario.id,
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
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[Emissao]:
    stmt = select(Emissao).where(Emissao.empresa_id == usuario.empresa_id)
    if status is not None:
        stmt = stmt.where(Emissao.status == status)
    if inicio is not None:
        stmt = stmt.where(Emissao.criada_em >= inicio)
    if fim is not None:
        stmt = stmt.where(Emissao.criada_em < fim + timedelta(days=1))
    stmt = stmt.order_by(Emissao.criada_em.desc())
    return list((await session.execute(stmt)).scalars().all())


@router.get("/{emissao_id}/xml")
async def baixar_xml(
    emissao_id: uuid.UUID,
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != usuario.empresa_id:
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
    usuario: Usuario = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None or emissao.empresa_id != usuario.empresa_id:
        raise HTTPException(status_code=404)
    if emissao.status != StatusEmissao.autorizada:
        raise HTTPException(status_code=404, detail="Nota nao autorizada")

    empresa = await session.get(Empresa, emissao.empresa_id)
    pfx_base64 = decifrar(empresa.certificado_pfx_cifrado, settings.fernet_key)
    senha = decifrar(empresa.certificado_senha_cifrada, settings.fernet_key) if empresa.certificado_senha_cifrada else None

    # AmbienteEnum(...) normaliza o valor recem-carregado do banco — ver
    # comentario equivalente no worker.py (Task 10) e o bug original na Task 5.
    pdf = await SefinClient.fetch_danfse_pdf(
        AmbienteEnum(empresa.ambiente).value, pfx_base64, senha, emissao.chave_acesso
    )
    if pdf is None:
        pdf = gerar_danfse_fallback(emissao, empresa)
    return Response(content=pdf, media_type="application/pdf")
