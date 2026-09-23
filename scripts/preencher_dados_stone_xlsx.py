"""Preenche data_vencimento/produto/tipo_produto/bandeira/codigo_autorizacao
de emissoes ja importadas de um relatorio de vendas da Stone, casando cada
linha pelo STONE ID (mesma chave usada pra dedupe na importacao normal --
ver app/routers/emissoes.py:_processar_csv).

Esses campos foram adicionados depois que emissoes via planilha ja vinham
sendo criadas (e depois que o formato de origem mudou do relatorio de
recebimentos, CSV, pro relatorio de vendas, XLSX), entao emissoes antigas
podem ter ficado com eles nulos. Esse script reprocessa a planilha original
pra recuperar os valores.

Uso:
    python -m scripts.preencher_dados_stone_xlsx --cnpj 49055093000140 \
        --xlsx "Relatorio Stone/vendas julho 2026.xlsx"
"""
from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.stone_xlsx import CabecalhoInvalidoError, parsear_relatorio_stone
from app.db import SessionLocal
from app.models import Emissao, Empresa

CAMPOS = ("data_vencimento", "produto", "tipo_produto", "bandeira", "codigo_autorizacao")


async def preencher_dados_stone(
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
        for campo in CAMPOS:
            setattr(emissao, campo, getattr(nota, campo))
        contagem["preenchidas"] += 1

    await session.commit()
    return contagem


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cnpj", required=True, help="CNPJ da empresa, so digitos")
    parser.add_argument("--xlsx", required=True, type=Path, help="caminho do relatorio de vendas da Stone")
    args = parser.parse_args()

    cnpj = "".join(c for c in args.cnpj if c.isdigit())
    conteudo = args.xlsx.read_bytes()

    async with SessionLocal() as session:
        empresa = (
            await session.execute(select(Empresa).where(Empresa.cnpj == cnpj))
        ).scalar_one_or_none()
        if empresa is None:
            raise SystemExit(f"empresa com cnpj {cnpj} nao encontrada")

        try:
            contagem = await preencher_dados_stone(session, empresa.id, conteudo)
        except CabecalhoInvalidoError as exc:
            raise SystemExit(f"xlsx invalido: {exc}")

    print(
        f"Preenchidas: {contagem['preenchidas']} | "
        f"Ja preenchidas: {contagem['ja_preenchidas']} | "
        f"Nao encontradas (nunca importadas): {contagem['nao_encontradas']}"
    )


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
