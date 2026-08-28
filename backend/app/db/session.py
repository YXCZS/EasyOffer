from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings


def build_database_url(settings: Settings) -> str | URL:
    if settings.database_url:
        return settings.database_url
    return URL.create(
        "mysql+aiomysql",
        username=settings.mysql_user,
        password=settings.mysql_password,
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_database,
        query={"charset": "utf8mb4"},
    )


def create_engine_and_session(settings: Settings) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        build_database_url(settings),
        # aiomysql's async ping signature is incompatible with SQLAlchemy's
        # generic pool_pre_ping hook in the supported driver versions.
        # pool_recycle plus connection-level error handling provides the
        # compatible liveness strategy without breaking pool checkout.
        pool_pre_ping=False,
        pool_recycle=1800,
        pool_timeout=10,
        pool_size=5,
        max_overflow=5,
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def session_dependency(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
