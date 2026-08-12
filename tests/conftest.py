import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nfse:nfse@localhost:5433/nfse")
os.environ.setdefault("DATABASE_URL_TEST", "postgresql+asyncpg://nfse:nfse@localhost:5433/nfse_test")
os.environ.setdefault("FERNET_KEY", "zH9m1yv3xVvV8v0T6t3s9m2m9m2m9m2m9m2m9m2m9m0=")
os.environ.setdefault("JWT_SECRET", "test-secret-nao-use-em-producao")

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
