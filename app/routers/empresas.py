import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.security import ContextoAutenticado, get_contexto_autenticado
from scripts.criar_empresa import criar_empresa

router = APIRouter(prefix="/empresas", tags=["empresas"])


@router.post("", status_code=201)
async def criar_empresa_via_api(
    cnpj: str = Form(...),
    inscricao_municipal: str = Form(...),
    municipio_ibge: str = Form(...),
    op_simp_nac: int = Form(...),
    codigo_tributacao: str = Form(...),
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

    pfx_bytes = await pfx.read()
    pfx_base64 = base64.b64encode(pfx_bytes).decode()

    try:
        empresa = await criar_empresa(
            session,
            cnpj=cnpj,
            inscricao_municipal=inscricao_municipal,
            municipio_ibge=municipio_ibge,
            op_simp_nac=op_simp_nac,
            codigo_tributacao=codigo_tributacao,
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
