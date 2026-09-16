import asyncio
import subprocess

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings


def test_alembic_upgrade_cria_todas_as_tabelas():
    settings = get_settings()

    async def _resetar_schema_publico():
        # Reseta o schema inteiro (tabelas + alembic_version) antes de migrar:
        # os outros testes do arquivo criam tabelas direto via
        # Base.metadata.create_all, sem passar pelo alembic. Sem isso, rodar a
        # suite inteira faz o `upgrade head` colidir com tabela ja existente
        # (ordem alfabetica dos arquivos de teste roda outros antes deste).
        #
        # Engine descartavel e propria pra essa chamada: reaproveitar a mesma
        # engine assincrona entre dois `asyncio.run()` diferentes quebra no
        # Windows (ProactorEventLoop) — a pool fica presa ao loop que ja
        # fechou (AttributeError: 'NoneType' object has no attribute 'send').
        engine = create_async_engine(settings.database_url_test)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DROP SCHEMA public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
        finally:
            await engine.dispose()

    asyncio.run(_resetar_schema_publico())

    subprocess.run(
        ["alembic", "-x", f"db_url={settings.database_url_test}", "upgrade", "head"],
        check=True,
        env={**__import__("os").environ, "DATABASE_URL": settings.database_url_test},
    )
    engine = create_async_engine(settings.database_url_test)

    async def _tabelas():
        async with engine.connect() as conn:
            return await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    nomes = asyncio.run(_tabelas())
    assert {"empresas", "usuarios", "emissoes"}.issubset(set(nomes))
