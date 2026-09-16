import asyncio
import os
import socket
import uuid
from collections.abc import AsyncGenerator
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nfse:nfse@localhost:5433/nfse")
os.environ.setdefault("DATABASE_URL_TEST", "postgresql+asyncpg://nfse:nfse@localhost:5433/nfse_test")
os.environ.setdefault("FERNET_KEY", "zH9m1yv3xVvV8v0T6t3s9m2m9m2m9m2m9m2m9m2m9m0=")
os.environ.setdefault("JWT_SECRET", "test-secret-nao-use-em-producao")


def _postgres_alcancavel(url: str) -> bool:
    partes = urlsplit(url)
    try:
        with socket.create_connection((partes.hostname, partes.port or 5432), timeout=0.5):
            return True
    except OSError:
        return False


if not _postgres_alcancavel(os.environ["DATABASE_URL_TEST"]):
    # `docker compose up -d db` nao esta no ar (ambiente sem Docker/WSL
    # funcionando). Sobe um Postgres 16 embarcado via pgserver — pip-installable,
    # sem admin, isolado em tests/.pgserver-data — so pra rodar a suite local.
    # Quem tiver o Docker do README no ar nunca cai aqui.
    import pgserver

    _diretorio_pgdata = os.path.join(os.path.dirname(__file__), ".pgserver-data")
    # cleanup_mode=None: nao para o servidor ao fim do processo pytest. Reiniciar
    # a cada execucao e lento demais nesse tipo de ambiente (o `pg_ctl start`
    # interno tem timeout fixo de 10s, e o disco pode facilmente estourar isso
    # numa maquina sob carga) — melhor deixar rodando em segundo plano, do
    # mesmo jeito que o Postgres do `docker compose up -d db` ficaria.
    _servidor_embarcado = pgserver.get_server(_diretorio_pgdata, cleanup_mode=None)
    os.environ["DATABASE_URL_TEST"] = _servidor_embarcado.get_uri().replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )

from app.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url_test)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory():
    settings = get_settings()
    engine = create_async_engine(settings.database_url_test)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()
