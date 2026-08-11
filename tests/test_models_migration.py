import subprocess

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings


def test_alembic_upgrade_cria_todas_as_tabelas():
    settings = get_settings()
    subprocess.run(
        ["alembic", "-x", f"db_url={settings.database_url_test}", "upgrade", "head"],
        check=True,
        env={**__import__("os").environ, "DATABASE_URL": settings.database_url_test},
    )
    engine = create_async_engine(settings.database_url_test)

    async def _tabelas():
        async with engine.connect() as conn:
            return await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    import asyncio

    nomes = asyncio.run(_tabelas())
    assert {"empresas", "usuarios", "emissoes"}.issubset(set(nomes))
