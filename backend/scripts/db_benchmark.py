"""Small repeatable benchmark for the SQLAlchemy database path.

Usage: python scripts/db_benchmark.py
The output is intentionally machine-readable so it can be compared with a
legacy-run baseline captured before a deployment.
"""

from __future__ import annotations

import asyncio
import json
import time

import aiomysql
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_engine_and_session


def percentile(samples: list[float]) -> dict[str, float]:
    samples.sort()
    index = max(0, min(len(samples) - 1, round(len(samples) * 0.95) - 1))
    return {"p50_ms": round(samples[len(samples) // 2], 2), "p95_ms": round(samples[index], 2)}


async def benchmark_sqlalchemy() -> dict[str, float]:
    engine, factory = create_engine_and_session(get_settings())
    samples: list[float] = []
    try:
        async with factory() as session:
            for _ in range(30):
                started = time.perf_counter()
                await session.execute(text("SELECT COUNT(*) FROM users"))
                samples.append((time.perf_counter() - started) * 1000)
    finally:
        await engine.dispose()
    return percentile(samples)


async def benchmark_legacy() -> dict[str, float]:
    settings = get_settings()
    pool = await aiomysql.create_pool(host=settings.mysql_host, port=settings.mysql_port, user=settings.mysql_user, password=settings.mysql_password, db=settings.mysql_database, charset="utf8mb4", autocommit=False, minsize=1, maxsize=5)
    samples: list[float] = []
    try:
        async with pool.acquire() as connection:
            for _ in range(30):
                started = time.perf_counter()
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT COUNT(*) FROM users")
                    await cursor.fetchone()
                await connection.commit()
                samples.append((time.perf_counter() - started) * 1000)
    finally:
        pool.close()
        await pool.wait_closed()
    return percentile(samples)


async def main() -> None:
    print(json.dumps({"samples": 30, "legacy_aiomysql": await benchmark_legacy(), "sqlalchemy_async": await benchmark_sqlalchemy()}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
