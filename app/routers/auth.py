from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import verificar_senha
from app.db import get_db
from app.models import Empresa, PapelUsuario, Usuario, UsuarioEmpresa
from app.schemas import EmpresaVinculadaOut, TokenOut, TrocarEmpresaIn
from app.security import ContextoAutenticado, criar_token, get_contexto_autenticado

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db),
) -> TokenOut:
    usuario = (
        await session.execute(select(Usuario).where(Usuario.email == form.username))
    ).scalar_one_or_none()
    if usuario is None or not verificar_senha(form.password, usuario.senha_hash):
        raise HTTPException(status_code=401, detail="Credenciais invalidas")

    vinculos = (
        await session.execute(select(UsuarioEmpresa).where(UsuarioEmpresa.usuario_id == usuario.id))
    ).scalars().all()

    empresa_id = None
    papel = None
    if len(vinculos) == 1:
        empresa_id = vinculos[0].empresa_id
        papel = PapelUsuario(vinculos[0].papel)

    return TokenOut(access_token=criar_token(usuario, empresa_id=empresa_id, papel=papel))


@router.get("/empresas", response_model=list[EmpresaVinculadaOut])
async def listar_minhas_empresas(
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    linhas = (
        await session.execute(
            select(UsuarioEmpresa, Empresa)
            .join(Empresa, Empresa.id == UsuarioEmpresa.empresa_id)
            .where(UsuarioEmpresa.usuario_id == contexto.usuario.id)
        )
    ).all()
    return [
        {"empresa_id": vinculo.empresa_id, "cnpj": empresa.cnpj, "papel": vinculo.papel}
        for vinculo, empresa in linhas
    ]


@router.post("/trocar-empresa", response_model=TokenOut)
async def trocar_empresa(
    dados: TrocarEmpresaIn,
    contexto: ContextoAutenticado = Depends(get_contexto_autenticado),
    session: AsyncSession = Depends(get_db),
) -> TokenOut:
    vinculo = (
        await session.execute(
            select(UsuarioEmpresa).where(
                UsuarioEmpresa.usuario_id == contexto.usuario.id,
                UsuarioEmpresa.empresa_id == dados.empresa_id,
            )
        )
    ).scalar_one_or_none()
    if vinculo is None:
        raise HTTPException(status_code=403, detail="Sem acesso a essa empresa")
    return TokenOut(
        access_token=criar_token(
            contexto.usuario, empresa_id=vinculo.empresa_id, papel=PapelUsuario(vinculo.papel)
        )
    )
