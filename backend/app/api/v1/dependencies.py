from functools import lru_cache

from app.llm.deepseek import DeepSeekQuizGenerator, DeepSeekReportGenerator
from app.services.quiz_service import QuizService
from app.services.report_service import ReportService


@lru_cache
def get_quiz_service() -> QuizService:
    return QuizService(generator=DeepSeekQuizGenerator())


@lru_cache
def get_report_service() -> ReportService:
    return ReportService(generator=DeepSeekReportGenerator())
