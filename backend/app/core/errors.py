from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
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


class TopicNotSupportedError(DomainError):
    def __init__(self, message: str = "当前主题不属于程序员技术面试内容，请换一个技术主题"):
        super().__init__(4001, message, 400, {"supported": False})


class KnowledgeDocumentAccessError(DomainError):
    def __init__(self, message: str = "请先登录并选择属于自己的知识库文档"):
        super().__init__(4003, message, 401)


class KnowledgeDocumentNotReadyError(DomainError):
    def __init__(self, message: str = "当前知识库文档尚未处理完成，请稍后重试"):
        super().__init__(4004, message, 409)


class KnowledgeDocumentInsufficientError(DomainError):
    def __init__(self, message: str = "当前文档内容不足，暂时无法生成完整题组"):
        super().__init__(4005, message, 422)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "data": exc.data},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(error.get("loc", [])), "msg": str(error.get("msg", "参数无效"))}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "code": 4220,
                "message": "请求参数校验失败，请检查答题数据后重试",
                "data": {"errors": errors},
            },
        )
