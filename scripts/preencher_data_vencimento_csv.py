"""Preenche `data_vencimento` de emissoes ja importadas de um relatorio da
Stone, casando cada linha pelo STONE ID (mesma chave usada pra dedupe na
importacao normal -- ver app/routers/emissoes.py:_processar_csv).

O campo `data_vencimento` foi adicionado depois que emissoes via CSV ja
vinham sendo criadas, entao essas emissoes antigas ficaram com o campo nulo.
Esse script reprocessa o relatorio original pra recuperar a data.

Uso:
    python -m scripts.preencher_data_vencimento_csv --cnpj 49055093000140 \
        --csv "Relatorio Stone/relatorio-recebimentos-....csv"
"""
from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.stone_csv import CabecalhoInvalidoError, parsear_relatorio_stone
from app.db import SessionLocal
from app.models import Emissao, Empresa


async def preencher_data_vencimento(
    session: AsyncSession, empresa_id, conteudo: bytes,
) -> dict[str, int]:
    resultado = parsear_relatorio_stone(conteudo)

    contagem = {"preenchidas": 0, "ja_preenchidas": 0, "nao_encontradas": 0}
    for nota in resultado.notas:
        emissao = (
            await session.execute(
                select(Emissao).where(
                    Emissao.empresa_id == empresa_id,
                    Emissao.stone_charge_id == nota.stone_charge_id,
                )
            )
        ).scalar_one_or_none()
        if emissao is None:
            contagem["nao_encontradas"] += 1
            continue
        if emissao.data_vencimento is not None:
            contagem["ja_preenchidas"] += 1
            continue
        emissao.data_vencimento = nota.data_vencimento
        contagem["preenchidas"] += 1

    await session.commit()
    return contagem


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cnpj", required=True, help="CNPJ da empresa, so digitos")
    parser.add_argument("--csv", required=True, type=Path, help="caminho do relatorio da Stone")
    args = parser.parse_args()

    cnpj = "".join(c for c in args.cnpj if c.isdigit())
    conteudo = args.csv.read_bytes()

    async with SessionLocal() as session:
        empresa = (
            await session.execute(select(Empresa).where(Empresa.cnpj == cnpj))
        ).scalar_one_or_none()
        if empresa is None:
            raise SystemExit(f"empresa com cnpj {cnpj} nao encontrada")

        try:
            contagem = await preencher_data_vencimento(session, empresa.id, conteudo)
        except CabecalhoInvalidoError as exc:
            raise SystemExit(f"csv invalido: {exc}")

    print(
        f"Preenchidas: {contagem['preenchidas']} | "
        f"Ja preenchidas: {contagem['ja_preenchidas']} | "
        f"Nao encontradas (nunca importadas): {contagem['nao_encontradas']}"
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
