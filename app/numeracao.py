import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Empresa


async def reservar_proximo_numero(session: AsyncSession, empresa_id: uuid.UUID) -> tuple[str, int]:
    """Reserva o proximo numero de forma transacional (UPDATE ... RETURNING).

    O caller deve commitar a transacao logo em seguida. Duas chamadas
    concorrentes na mesma empresa serializam pela trava de linha que o
    UPDATE adquire — nunca leem o mesmo proximo_numero.
    """
    stmt = (
        update(Empresa)
        .where(Empresa.id == empresa_id)
        .values(proximo_numero=Empresa.proximo_numero + 1)
        .returning(Empresa.serie, Empresa.proximo_numero)
    )
    resultado = await session.execute(stmt)
    serie, proximo_numero_apos = resultado.one()
    return serie, proximo_numero_apos - 1


async def reservar_proximo_numero_nfe(session: AsyncSession, empresa_id: uuid.UUID) -> tuple[str, int]:
    """Mesmo mecanismo de reservar_proximo_numero, na sequencia PROPRIA da
    NF-e modelo 55 (serie_nfe/proximo_numero_nfe) -- documento fiscal
    distinto da NFS-e, nunca consome a numeracao dela."""
    stmt = (
        update(Empresa)
        .where(Empresa.id == empresa_id)
        .values(proximo_numero_nfe=Empresa.proximo_numero_nfe + 1)
        .returning(Empresa.serie_nfe, Empresa.proximo_numero_nfe)
    )
    resultado = await session.execute(stmt)
    serie, proximo_numero_apos = resultado.one()
    return serie, proximo_numero_apos - 1
