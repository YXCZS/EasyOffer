from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    def __init__(self, code: int, message: str, status_code: int = 400, data=None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.data = data
        super().__init__(message)


class LLMGenerationError(DomainError):
    def __init__(self, message: str = "AI 生成失败，请稍后重试"):
        super().__init__(5001, message, 502)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "data": exc.data},
        )
