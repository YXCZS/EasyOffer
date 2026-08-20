from typing import Protocol

from app.core.errors import LLMGenerationError
from app.models.quiz import Quiz, QuizGenerateOutput, QuizGenerateRequest
from app.services.topic_service import validate_topic_scope


class QuizGenerator(Protocol):
    async def generate(self, request: QuizGenerateRequest) -> QuizGenerateOutput: ...


class QuizService:
    def __init__(self, generator: QuizGenerator, max_attempts: int = 2):
        self.generator = generator
        self.max_attempts = max_attempts

    async def generate(self, request: QuizGenerateRequest) -> Quiz:
        validate_topic_scope(request.user_input)
        last_error: Exception | None = None
        for _ in range(self.max_attempts):
            try:
                output = await self.generator.generate(request)
                if not output.supported:
                    raise LLMGenerationError(output.message or "当前主题暂不支持生成题组")
                if output.quiz is None:
                    raise LLMGenerationError("模型未返回完整题组")
                return output.quiz
            except Exception as exc:
                last_error = exc
        if isinstance(last_error, LLMGenerationError):
            raise last_error
        raise LLMGenerationError() from last_error
