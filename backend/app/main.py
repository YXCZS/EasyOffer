from fastapi import FastAPI

from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.quiz import router as quiz_router
from app.api.v1.routes.report import router as report_router
from app.core.errors import register_exception_handlers


def create_app() -> FastAPI:
    app = FastAPI(title="EasyOffer API", version="0.1.0")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(quiz_router, prefix="/api/v1")
    app.include_router(report_router, prefix="/api/v1")
    register_exception_handlers(app)
    return app


app = create_app()
