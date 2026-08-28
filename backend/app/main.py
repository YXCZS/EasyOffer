from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.quiz import router as quiz_router
from app.api.v1.routes.report import router as report_router
from app.api.v1.routes.progress import router as progress_router
from app.api.v1.routes.user import router as user_router
from app.api.v1.routes.knowledge import router as knowledge_router
from app.api.v1.routes.generation import router as generation_router
from app.core.errors import register_exception_handlers
from app.core.config import get_settings
from app.core.db import create_pool
from app.repositories.generation_repository import recover_interrupted_tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.db_pool = await create_pool(get_settings())
        app.state.db_engine = getattr(app.state.db_pool, "engine", None)
        app.state.db_session_factory = getattr(app.state.db_pool, "session_factory", None)
        async with app.state.db_pool.acquire() as connection:
            await recover_interrupted_tasks(connection)
    except Exception:
        app.state.db_pool = None
    try:
        yield
    finally:
        pool = getattr(app.state, "db_pool", None)
        if pool is not None:
            pool.close()
            await pool.wait_closed()
        engine = getattr(app.state, "db_engine", None)
        if engine is not None and pool is None:
            await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="EasyOffer API", version="0.1.0", lifespan=lifespan)
    upload_root = Path(get_settings().upload_dir).resolve()
    (upload_root / "avatars").mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(upload_root)), name="uploads")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(quiz_router, prefix="/api/v1")
    app.include_router(report_router, prefix="/api/v1")
    app.include_router(progress_router, prefix="/api/v1")
    app.include_router(user_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(generation_router, prefix="/api/v1")
    register_exception_handlers(app)
    return app


app = create_app()
