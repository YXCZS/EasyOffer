import logging
from typing import Any
from typing import Protocol

from app.core.errors import (
    DomainError,
    KnowledgeDocumentAccessError,
    KnowledgeDocumentNotReadyError,
    LLMGenerationError,
    TopicNotSupportedError,
)
from app.models.quiz import Quiz, QuizGenerateOutput, QuizGenerateRequest
from app.repositories import knowledge_repository
from app.services.topic_service import validate_topic_scope
from app.services.question_types import validate_quiz_type_quota

logger = logging.getLogger(__name__)


class QuizGenerator(Protocol):
    async def generate(self, request: QuizGenerateRequest) -> QuizGenerateOutput: ...


class QuizService:
    def __init__(self, generator: QuizGenerator, max_attempts: int = 2):
        self.generator = generator
        self.max_attempts = max_attempts

    async def generate(
        self,
        request: QuizGenerateRequest,
        user_id: int | None = None,
        connection: Any | None = None,
    ) -> Quiz:
        validate_topic_scope(request.user_input)
        if request.document_id:
            if user_id is None:
                raise KnowledgeDocumentAccessError()
            if connection is None:
                raise KnowledgeDocumentNotReadyError("知识库服务暂时不可用，请稍后重试")
            document = await knowledge_repository.get_document(connection, user_id, request.document_id)
            if document is None:
                raise KnowledgeDocumentAccessError()
            if document.get("status") != "ready":
                raise KnowledgeDocumentNotReadyError()
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                try:
                    output = await self.generator.generate(request, user_id=user_id)
                except TypeError:
                    output = await self.generator.generate(request)
                if not output.supported:
                    raise TopicNotSupportedError(output.message or "当前主题不属于程序员技术面试内容，请换一个技术主题")
                if output.quiz is None:
                    raise LLMGenerationError("模型未返回完整题组")
                validate_quiz_type_quota(output.quiz.questions)
                return output.quiz
            except TopicNotSupportedError:
                raise
            except DomainError:
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "quiz_generation_attempt_failed",
                    extra={
                        "attempt": attempt,
                        "max_attempts": self.max_attempts,
                        "failure_type": type(exc).__name__,
                        "topic_length": len(request.user_input),
                    },
                    exc_info=True,
                )
        if isinstance(last_error, LLMGenerationError):
            raise last_error
        raise LLMGenerationError() from last_error
