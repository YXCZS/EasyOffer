import asyncio

from app.models.quiz import QuizGenerateRequest
from app.services.report_service import ReportService
from tests.fakes import FakeReportGenerator
from tests.sample_data import make_quiz
from app.models.report import ReportGenerateRequest


def _request():
    quiz = make_quiz(QuizGenerateRequest(user_input="Redis", role="backend"))
    return ReportGenerateRequest(
        quiz_id=quiz.quiz_id,
        topic=quiz.topic,
        role=quiz.role,
        questions=quiz.questions,
        answer_records=[{"question_id": q.id, "selected_answers": ["A"]} for q in quiz.questions],
    )


def test_report_service_returns_deterministic_fallback_after_generator_failures():
    class AlwaysFail:
        async def generate(self, request, summary):
            raise RuntimeError("model unavailable")

    report = asyncio.run(ReportService(AlwaysFail(), max_attempts=2).generate(_request()))
    assert len(report.summary) == 3
    assert report.total == 6
    assert "基础复盘" in report.limitations


def test_report_service_keeps_ai_draft_when_generator_succeeds():
    report = asyncio.run(ReportService(FakeReportGenerator()).generate(_request()))
    assert len(report.summary) == 3
    assert "复习" in report.advice[0]
