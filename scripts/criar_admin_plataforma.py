"""Cria (ou promove) um usuario administrador da plataforma -- acesso total,
sem vinculo fixo a nenhuma empresa (entra em qualquer uma pela tela
/admin-plataforma, que cria o vinculo na hora). De proposito sem endpoint
HTTP pra isso: e um poder alto demais pra expor via API sem um admin ja
existente pra autorizar. Roda direto contra o banco (local ou producao,
via DATABASE_URL).

Uso:
    python scripts/criar_admin_plataforma.py --email admin@exemplo.com --senha "..."
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import hash_senha
from app.db import SessionLocal
from app.models import Usuario


async def criar_ou_promover_admin_plataforma(session: AsyncSession, email: str, senha: str) -> Usuario:
    usuario = (
        await session.execute(select(Usuario).where(Usuario.email == email))
    ).scalar_one_or_none()
    if usuario is None:
        usuario = Usuario(email=email, senha_hash=hash_senha(senha), eh_admin_plataforma=True)
        session.add(usuario)
    else:
        usuario.senha_hash = hash_senha(senha)
        usuario.eh_admin_plataforma = True
    await session.commit()
    await session.refresh(usuario)
    return usuario


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--senha", required=True)
    args = parser.parse_args()

    async with SessionLocal() as session:
        usuario = await criar_ou_promover_admin_plataforma(session, args.email, args.senha)
    print(f"Administrador da plataforma pronto: {usuario.email} (id {usuario.id})")


if __name__ == "__main__":
    asyncio.run(_main())
