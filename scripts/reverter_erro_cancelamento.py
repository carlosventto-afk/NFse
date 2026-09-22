"""Reverte uma emissao presa em "erro_cancelamento" de volta para
"autorizada" -- caso: a nota fiscal continua valida e autorizada, so o
CANCELAMENTO em si foi recusado definitivamente pela prefeitura/Spedy (ex.:
prazo de cancelamento expirado, ver interpretar_status_cancelamento). Nesse
cenario a nota fiscal nunca deixou de existir; o status "erro_cancelamento"
so serve pra sinalizar que a tentativa de cancelar falhou, nao que a nota
esta com problema.

De proposito sem endpoint HTTP: reverter um cancelamento e uma decisao
consciente do titular apos confirmar (fora do sistema, com a prefeitura) que
a nota realmente permanece valida -- nao algo pra expor como botao clicavel
sem essa confirmacao previa. Roda direto contra o banco (local ou producao,
via DATABASE_URL).

Uso:
    python -m scripts.reverter_erro_cancelamento --emissao-id <uuid>
"""
from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Emissao, StatusEmissao


async def reverter_erro_cancelamento(session: AsyncSession, emissao_id: uuid.UUID) -> Emissao:
    emissao = await session.get(Emissao, emissao_id)
    if emissao is None:
        raise ValueError(f"emissao {emissao_id} nao encontrada")
    if emissao.status != StatusEmissao.erro_cancelamento:
        raise ValueError(
            f"emissao {emissao_id} nao esta em erro_cancelamento (status atual: {emissao.status})"
        )
    emissao.status = StatusEmissao.autorizada
    emissao.erros = None
    emissao.motivo_cancelamento = None
    await session.commit()
    await session.refresh(emissao)
    return emissao


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emissao-id", required=True, type=uuid.UUID)
    args = parser.parse_args()

    async with SessionLocal() as session:
        emissao = await reverter_erro_cancelamento(session, args.emissao_id)
    print(f"Emissao {emissao.id} revertida para autorizada (serie {emissao.serie}/{emissao.numero}).")


if __name__ == "__main__":
    asyncio.run(_main())
