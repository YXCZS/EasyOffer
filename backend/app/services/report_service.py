import logging
from typing import Protocol

from app.models.report import QuestionResult, Report, ReportDraft, ReportGenerateRequest
from app.services.scoring_service import ScoreSummary, calculate_score

logger = logging.getLogger(__name__)


class ReportGenerator(Protocol):
    async def generate(
        self, request: ReportGenerateRequest, score_summary: ScoreSummary
    ) -> ReportDraft: ...


class ReportService:
    def __init__(self, generator: ReportGenerator, max_attempts: int = 2):
        self.generator = generator
        self.max_attempts = max_attempts

    async def generate(self, request: ReportGenerateRequest, user_id: int | None = None) -> Report:
        summary = calculate_score(request.questions, request.answer_records)
        question_results = self._build_question_results(request)
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                try:
                    draft = await self.generator.generate(request, summary, user_id=user_id)
                except TypeError:
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
                    question_results=question_results,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "report_generation_attempt_failed",
                    extra={
                        "attempt": attempt,
                        "max_attempts": self.max_attempts,
                        "failure_type": type(exc).__name__,
                    },
                    exc_info=True,
                )

        logger.warning(
            "report_generation_fallback",
            extra={"failure_type": type(last_error).__name__ if last_error else "unknown"},
        )
        return Report(
            quiz_id=request.quiz_id,
            topic=request.topic,
            score=summary.score,
            total=summary.total,
            accuracy=summary.accuracy,
            mastered_points=summary.mastered_points,
            review_points=summary.review_points,
            summary=[
                f"本轮共完成 {summary.total} 道题，答对 {summary.score} 道，正确率 {summary.accuracy:.1f}%。",
                "已根据答题结果整理出掌握与待巩固知识点。",
                "建议结合每道题的解析复习，再进行一轮针对性练习。",
            ],
            advice=[
                f"优先复习：{'、'.join(summary.review_points[:5])}"
                if summary.review_points else "继续保持当前知识点的练习节奏。"
            ],
            limitations="AI 复盘服务暂时不可用，本报告已使用本轮答题数据生成基础复盘。",
            question_results=question_results,
        )

    @staticmethod
    def _build_question_results(request: ReportGenerateRequest) -> list[QuestionResult]:
        records = {record.question_id: record for record in request.answer_records}
        results: list[QuestionResult] = []
        for index, question in enumerate(request.questions, start=1):
            record = records.get(question.id)
            options = {option.key: option.text for option in question.options}
            selected = record.selected_answers if record else []
            is_correct = record is not None and set(selected) == set(question.answer)
            results.append(
                QuestionResult(
                    question_id=question.id,
                    question_number=index,
                    stem=question.stem,
                    knowledge_point=question.knowledge_point,
                    status="correct" if is_correct else "incorrect" if record else "unanswered",
                    selected_answers=selected,
                    selected_answer_texts=[options[key] for key in selected if key in options],
                    correct_answers=question.answer,
                    correct_answer_texts=[options[key] for key in question.answer if key in options],
                    duration_ms=record.duration_ms if record else 0,
                    explanation=question.explanation,
                )
            )
        return results
