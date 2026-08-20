from pydantic import Field, model_validator

from app.models.common import StrictModel
from app.models.quiz import Question, Role


class AnswerRecord(StrictModel):
    question_id: str = Field(min_length=1, max_length=50)
    selected_answers: list[str] = Field(min_length=1, max_length=4)
    is_correct: bool | None = None
    duration_ms: int = Field(default=0, ge=0, le=3600000)


class ReportGenerateRequest(StrictModel):
    quiz_id: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=2000)
    role: Role
    questions: list[Question] = Field(min_length=1, max_length=6)
    answer_records: list[AnswerRecord] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_records(self) -> "ReportGenerateRequest":
        question_ids = {question.id for question in self.questions}
        record_ids = [record.question_id for record in self.answer_records]
        if any(question_id not in question_ids for question_id in record_ids):
            raise ValueError("答题记录包含未知题目")
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("答题记录不能重复")
        return self


class ReportDraft(StrictModel):
    summary: list[str] = Field(min_length=3, max_length=3)
    advice: list[str] = Field(min_length=1, max_length=5)
    limitations: str = Field(min_length=1, max_length=300)


class Report(StrictModel):
    quiz_id: str
    topic: str
    score: int = Field(ge=0)
    total: int = Field(gt=0)
    accuracy: float = Field(ge=0, le=100)
    mastered_points: list[str]
    review_points: list[str]
    summary: list[str] = Field(min_length=3, max_length=3)
    advice: list[str] = Field(min_length=1)
    limitations: str
