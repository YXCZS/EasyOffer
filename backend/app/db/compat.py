"""Temporary aiomysql-shaped adapter backed by SQLAlchemy AsyncSession.

It lets existing repositories migrate independently. New code should use
AsyncSession directly; this adapter is removed after all repositories switch.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

try:
    import aiomysql
except ImportError:  # pragma: no cover
    aiomysql = None


_POSITIONAL = re.compile(r"(?<!%)%s")


def _statement(sql: str, params: Any) -> tuple[Any, dict[str, Any]]:
    if params is None:
        return text(sql), {}
    if isinstance(params, dict):
        return text(sql), params
    values = tuple(params) if isinstance(params, (tuple, list)) else (params,)
    index = 0

    def replace(_match: re.Match[str]) -> str:
        nonlocal index
        name = f"p{index}"
        index += 1
        return f":{name}"

    converted = _POSITIONAL.sub(replace, sql)
    if index != len(values):
        raise ValueError(f"parameter count mismatch: expected {index}, got {len(values)}")
    return text(converted), {f"p{i}": value for i, value in enumerate(values)}


class SQLAlchemyCursor:
    def __init__(self, session: AsyncSession, dict_mode: bool = False):
        self.session = session
        self.dict_mode = dict_mode
        self.rowcount = -1
        self._rows: list[Any] = []
        self._index = 0

    async def __aenter__(self) -> "SQLAlchemyCursor":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def execute(self, sql: str, params: Any = None) -> None:
        statement, values = _statement(sql, params)
        result = await self.session.execute(statement, values)
        self.rowcount = result.rowcount
        if result.returns_rows:
            self._rows = [dict(row) for row in result.mappings().all()] if self.dict_mode else [tuple(row) for row in result.fetchall()]
        else:
            self._rows = []
        self._index = 0

    async def fetchone(self) -> Any:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    async def fetchall(self) -> list[Any]:
        rows = self._rows[self._index :]
        self._index = len(self._rows)
        return rows


class SQLAlchemyConnection:
    def __init__(self, session: AsyncSession):
        self.session = session

    def cursor(self, cursor_cls: Any = None) -> SQLAlchemyCursor:
        dict_mode = aiomysql is not None and cursor_cls is aiomysql.DictCursor
        return SQLAlchemyCursor(self.session, dict_mode=dict_mode)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def begin(self) -> None:
        await self.session.begin()


class SQLAlchemyPool:
    def __init__(self, engine: AsyncEngine, factory: async_sessionmaker[AsyncSession]):
        self.engine = engine
        self.session_factory = factory

    def acquire(self) -> Any:
        pool = self

        class Acquisition:
            session: AsyncSession
            connection: SQLAlchemyConnection

            async def __aenter__(self) -> SQLAlchemyConnection:
                self.session = pool.session_factory()
                self.connection = SQLAlchemyConnection(self.session)
                return self.connection

            async def __aexit__(self, *_exc: Any) -> None:
                await self.session.close()

        return Acquisition()

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        await self.engine.dispose()
