from functools import lru_cache

from app.llm.deepseek import DeepSeekQuizGenerator, DeepSeekReportGenerator
from app.services.quiz_service import QuizService
from app.services.incremental_quiz_service import IncrementalQuizService
from app.services.report_service import ReportService
from app.core.db import get_db
from app.db.session import session_dependency
from app.research.tavily_agent import TavilyResearchAgent
from app.services.visual_asset_service import VisualAssetService

__all__ = ["get_db", "get_db_session", "get_quiz_service", "get_report_service", "get_incremental_quiz_service", "get_visual_asset_service"]


async def get_db_session(request):
    factory = getattr(request.app.state, "db_session_factory", None)
    if factory is None:
        yield None
        return
    async for session in session_dependency(factory):
        yield session


@lru_cache
def get_quiz_service() -> QuizService:
    # Evidence routing owns the single Tavily/Milvus retrieval path. Keeping the
    # provider out of the generator prevents duplicate web research per request.
    return QuizService(generator=DeepSeekQuizGenerator(research_provider=TavilyResearchAgent()))


@lru_cache
def get_visual_asset_service() -> VisualAssetService:
    return VisualAssetService()


@lru_cache
def get_report_service() -> ReportService:
    return ReportService(generator=DeepSeekReportGenerator())


@lru_cache
def get_incremental_quiz_service() -> IncrementalQuizService:
    return IncrementalQuizService(
        generator=DeepSeekQuizGenerator(research_provider=TavilyResearchAgent()),
        visual_assets=get_visual_asset_service(),
    )
