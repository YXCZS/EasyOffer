from typing import Protocol

from app.core.errors import LLMGenerationError
from app.models.report import Report, ReportDraft, ReportGenerateRequest
from app.services.scoring_service import ScoreSummary, calculate_score


class ReportGenerator(Protocol):
    async def generate(
        self, request: ReportGenerateRequest, score_summary: ScoreSummary
    ) -> ReportDraft: ...


class ReportService:
    def __init__(self, generator: ReportGenerator, max_attempts: int = 2):
        self.generator = generator
        self.max_attempts = max_attempts

    async def generate(self, request: ReportGenerateRequest) -> Report:
        summary = calculate_score(request.questions, request.answer_records)
        last_error: Exception | None = None
        for _ in range(self.max_attempts):
            try:
                draft = await self.generator.generate(request, summary)
                return Report(
                    quiz_id=request.quiz_id,
                    topic=request.topic,
                    score=summary.score,
                    total=summary.total,
                    accuracy=summary.accuracy,
                    mastered_points=summary.mastered_points,
                    review_points=summary.review_points,
                    summary=draft.summary,
                    advice=draft.advice,
                    limitations=draft.limitations,
                )
            except Exception as exc:
                last_error = exc
        raise LLMGenerationError("复盘报告生成失败，请稍后重试") from last_error
