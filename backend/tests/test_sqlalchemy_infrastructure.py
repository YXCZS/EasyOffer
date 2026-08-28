import asyncio

from app.core.config import Settings
from app.db import Base, models
from app.db.session import build_database_url, create_engine_and_session
from app.core import db as database
from app.db.compat import _statement


def test_database_url_uses_aiomysql_and_utf8mb4():
    settings = Settings()
    settings.mysql_user = "root"
    settings.mysql_password = "p@ss"
    settings.mysql_host = "db"
    settings.mysql_database = "easyoffer"
    settings.database_url = None
    url = build_database_url(settings)
    rendered = url.render_as_string(hide_password=False) if hasattr(url, "render_as_string") else str(url)
    assert rendered.startswith("mysql+aiomysql://root:p%40ss@db")
    assert "charset=utf8mb4" in rendered


def test_all_existing_tables_are_mapped_once():
    expected = {
        "users", "quiz_sessions", "answer_records", "reports", "quiz_progress",
        "quiz_generation_tasks", "guest_generation_usage", "knowledge_documents", "quiz_visual_assets",
    }
    assert set(Base.metadata.tables) == expected
    assert models.User.__tablename__ == "users"


def test_async_engine_can_be_created_and_disposed_without_connecting():
    async def run():
        engine, factory = create_engine_and_session(Settings(mysql_password="test"))
        assert factory.kw["expire_on_commit"] is False
        await engine.dispose()

    asyncio.run(run())


def test_legacy_backend_switch_remains_available(monkeypatch):
    calls = []

    async def fake_pool(**kwargs):
        calls.append(kwargs)
        return "legacy-pool"

    monkeypatch.setattr(database.aiomysql, "create_pool", fake_pool)
    settings = Settings()
    settings.database_backend = "legacy"
    assert asyncio.run(database.create_pool(settings)) == "legacy-pool"
    assert calls and calls[0]["db"] == settings.mysql_database


def test_positional_parameters_are_bound_not_interpolated():
    statement, params = _statement("SELECT * FROM users WHERE nickname = %s", ("' OR 1=1 --",))
    assert ":p0" in str(statement)
    assert "OR 1=1" not in str(statement)
    assert params == {"p0": "' OR 1=1 --"}
