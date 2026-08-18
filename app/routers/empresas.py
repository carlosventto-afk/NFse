import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crypto import cifrar
from app.db import get_db
from app.models import Emissao, Empresa
from app.schemas import EmpresaDetalheOut, NumeracaoIn, NumeracaoOut
from app.security import ContextoAutenticado, exigir_admin_empresa, get_contexto_autenticado
from nfse_core import CertificateError, conferir_titularidade, inspecionar
from scripts.criar_empresa import criar_empresa

router = APIRouter(prefix="/empresas", tags=["empresas"])


@router.post("", status_code=201)
async def criar_empresa_via_api(
    cnpj: str = Form(...),
    inscricao_municipal: str | None = Form(None),
    municipio_ibge: str = Form(...),
    local_prestacao_ibge: str | None = Form(None),
    op_simp_nac: int = Form(...),
    regime_apuracao_sn: str | None = Form(None),
    codigo_tributacao: str = Form(...),
    codigo_tributacao_municipal: str | None = Form(None),
    descricao_servico_padrao: str = Form(...),
    ambiente: str = Form(...),
    senha_certificado: str = Form(...),
    titular_email: str = Form(...),
    pfx: UploadFile = File(...),
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
    session: AsyncSession = Depends(get_db),
) -> dict:
    if not contexto.eh_admin_plataforma and titular_email != contexto.usuario.email:
        raise HTTPException(status_code=403, detail="So e possivel criar empresa para si mesmo")

    cnpj = "".join(filter(str.isdigit, cnpj))
    if len(cnpj) != 14:
        raise HTTPException(status_code=422, detail="CNPJ deve ter 14 digitos")
    inscricao_municipal = (inscricao_municipal or "").strip() or None
    local_prestacao_ibge = (local_prestacao_ibge or "").strip() or None
    codigo_tributacao_municipal = (codigo_tributacao_municipal or "").strip() or None
    regime_apuracao_sn_int = int(regime_apuracao_sn) if (regime_apuracao_sn or "").strip() else None

    pfx_bytes = await pfx.read()
    pfx_base64 = base64.b64encode(pfx_bytes).decode()

    try:
        empresa = await criar_empresa(
            session,
            cnpj=cnpj,
            inscricao_municipal=inscricao_municipal,
            municipio_ibge=municipio_ibge,
            local_prestacao_ibge=local_prestacao_ibge,
            op_simp_nac=op_simp_nac,
            regime_apuracao_sn=regime_apuracao_sn_int,
            codigo_tributacao=codigo_tributacao,
            codigo_tributacao_municipal=codigo_tributacao_municipal,
            descricao_servico_padrao=descricao_servico_padrao,
            ambiente=ambiente,
            pfx_base64=pfx_base64,
            senha_certificado=senha_certificado,
            webhook_token=base64.urlsafe_b64encode(cnpj.encode()).decode(),
            titular_email=titular_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "id": str(empresa.id), "cnpj": empresa.cnpj,
        "ambiente": empresa.ambiente if isinstance(empresa.ambiente, str) else empresa.ambiente.value,
    }


@router.get("/mim", response_model=EmpresaDetalheOut)
async def obter_minha_empresa(
    contexto: ContextoAutenticado = Depends(exigir_admin_empresa),
    session: AsyncSession = Depends(get_db),
) -> Empresa:
    return await session.get(Empresa, contexto.empresa_id)


@router.put("/mim", response_model=EmpresaDetalheOut)
async def editar_minha_empresa(
    cnpj: str = Form(...),
    inscricao_municipal: str | None = Form(None),
    municipio_ibge: str = Form(...),
    local_prestacao_ibge: str | None = Form(None),
    op_simp_nac: int = Form(...),
    regime_apuracao_sn: str | None = Form(None),
    codigo_tributacao: str = Form(...),
    codigo_tributacao_municipal: str | None = Form(None),
    descricao_servico_padrao: str = Form(...),
    ambiente: str = Form(...),
    senha_certificado: str | None = Form(None),
    pfx: UploadFile | None = File(None),
    contexto: ContextoAutenticado = Depends(exigir_admin_empresa),
    session: AsyncSession = Depends(get_db),
) -> Empresa:
    cnpj = "".join(filter(str.isdigit, cnpj))
    if len(cnpj) != 14:
        raise HTTPException(status_code=422, detail="CNPJ deve ter 14 digitos")
    if ambiente not in ("homologacao", "producao"):
        raise HTTPException(status_code=422, detail="Ambiente deve ser homologacao ou producao")
    inscricao_municipal = (inscricao_municipal or "").strip() or None
    local_prestacao_ibge = (local_prestacao_ibge or "").strip() or None
    codigo_tributacao_municipal = (codigo_tributacao_municipal or "").strip() or None
    regime_apuracao_sn_int = int(regime_apuracao_sn) if (regime_apuracao_sn or "").strip() else None

    empresa = await session.get(Empresa, contexto.empresa_id)

    if pfx is not None:
        if not senha_certificado:
            raise HTTPException(status_code=422, detail="senha_certificado e obrigatoria ao trocar o certificado")
        pfx_bytes = await pfx.read()
        pfx_base64 = base64.b64encode(pfx_bytes).decode()
        try:
            info = inspecionar(pfx_base64, senha_certificado)
        except CertificateError as exc:
            raise HTTPException(status_code=422, detail=f"Certificado invalido: {exc}")
        aviso_titularidade = conferir_titularidade(info, cnpj)
        if aviso_titularidade:
            raise HTTPException(status_code=422, detail=aviso_titularidade)
        if info.expirado:
            raise HTTPException(
                status_code=422, detail=f"Certificado ja esta vencido em {info.valido_ate:%d/%m/%Y}"
            )
        fernet_key = get_settings().fernet_key
        empresa.certificado_pfx_cifrado = cifrar(pfx_base64, fernet_key)
        empresa.certificado_senha_cifrada = cifrar(senha_certificado, fernet_key)
        empresa.certificado_valido_ate = info.valido_ate

    empresa.cnpj = cnpj
    empresa.inscricao_municipal = inscricao_municipal
    empresa.municipio_ibge = municipio_ibge
    empresa.local_prestacao_ibge = local_prestacao_ibge
    empresa.op_simp_nac = op_simp_nac
    empresa.regime_apuracao_sn = regime_apuracao_sn_int
    empresa.codigo_tributacao = codigo_tributacao
    empresa.codigo_tributacao_municipal = codigo_tributacao_municipal
    empresa.descricao_servico_padrao = descricao_servico_padrao
    empresa.ambiente = ambiente

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=422, detail="Ja existe uma empresa cadastrada com esse CNPJ")
    await session.refresh(empresa)
    return empresa


@router.get("/numeracao", response_model=NumeracaoOut)
async def obter_numeracao(
    contexto: ContextoAutenticado = Depends(exigir_admin_empresa),
    session: AsyncSession = Depends(get_db),
) -> Empresa:
    empresa = await session.get(Empresa, contexto.empresa_id)
    return empresa


@router.put("/numeracao", response_model=NumeracaoOut)
async def definir_numeracao(
    dados: NumeracaoIn,
    contexto: ContextoAutenticado = Depends(exigir_admin_empresa),
    session: AsyncSession = Depends(get_db),
) -> Empresa:
    maior_numero_usado = (
        await session.execute(
            select(func.max(Emissao.numero)).where(
                Emissao.empresa_id == contexto.empresa_id, Emissao.serie == dados.serie,
            )
        )
    ).scalar_one_or_none()
    if maior_numero_usado is not None and dados.proximo_numero <= maior_numero_usado:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Ja existe emissao com numero {maior_numero_usado} na serie {dados.serie}; "
                f"o proximo numero precisa ser maior que isso"
            ),
        )

    empresa = await session.get(Empresa, contexto.empresa_id)
    empresa.serie = dados.serie
    empresa.proximo_numero = dados.proximo_numero
    await session.commit()
    await session.refresh(empresa)
    return empresa
