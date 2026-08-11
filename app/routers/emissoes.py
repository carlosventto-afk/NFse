from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Emissao, OrigemEmissao, StatusEmissao, Usuario
from app.numeracao import reservar_proximo_numero
from app.schemas import EmissaoManualIn, EmissaoOut
from app.security import get_current_user

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
