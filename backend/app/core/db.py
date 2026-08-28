from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
import aiomysql

from app.core.config import Settings
from app.db.compat import SQLAlchemyPool
from app.db.session import create_engine_and_session


async def create_pool(settings: Settings) -> Any:
    if settings.database_backend.lower() in {"aiomysql", "legacy"}:
        return await aiomysql.create_pool(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            db=settings.mysql_database,
            charset="utf8mb4",
            autocommit=False,
            minsize=1,
            maxsize=5,
        )
    engine, factory = create_engine_and_session(settings)
    return SQLAlchemyPool(engine, factory)


async def get_db(request: Request) -> AsyncIterator[Any | None]:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        yield None
        return
    async with pool.acquire() as connection:
        yield connection
