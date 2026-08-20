from app.models.report import ReportDraft
from app.models.quiz import QuizGenerateOutput, QuizGenerateRequest
from tests.sample_data import make_quiz


class FakeQuizGenerator:
    def __init__(self, failures: int = 0):
        self.failures = failures
        self.calls = 0

    async def generate(self, request: QuizGenerateRequest) -> QuizGenerateOutput:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary failure")
        return QuizGenerateOutput(quiz=make_quiz(request))


class FakeReportGenerator:
    async def generate(self, request, score_summary) -> ReportDraft:
        return ReportDraft(
            summary=[
                "核心概念已完成一轮检查。",
                "需要回看错题对应的工程边界。",
                "下一轮应优先复习待巩固知识点。",
            ],
            advice=["复习后重新练习待巩固知识点。"],
            limitations="本报告仅反映本轮题目表现，不代表真实面试通过概率。",
        )
