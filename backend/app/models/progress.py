from typing import Literal

from pydantic import Field

from app.models.common import StrictModel
from app.models.report import AnswerRecord
from app.models.quiz import Difficulty, Quiz, Role

ProgressStatus = Literal["in_progress", "ready_for_report", "completed", "abandoned"]
ActiveProgressStatus = Literal["in_progress", "ready_for_report"]


class ProgressSaveRequest(StrictModel):
    current_index: int = Field(ge=0, le=6)
    answer_records: list[AnswerRecord] = Field(default_factory=list, max_length=6)
    version: int = Field(ge=1)


class IncompleteQuizItem(StrictModel):
    quiz_id: str
    title: str
    topic: str
    role: Role
    difficulty: Difficulty
    status: ActiveProgressStatus
    answered_count: int = Field(ge=0)
    total_questions: int = Field(gt=0)
    current_index: int = Field(ge=0)
    updated_at: str


class IncompleteQuizList(StrictModel):
    items: list[IncompleteQuizItem]


class QuizProgressDetail(StrictModel):
    quiz: Quiz
    status: ProgressStatus
    current_index: int = Field(ge=0)
    answered_count: int = Field(ge=0)
    total_questions: int = Field(gt=0)
    answer_records: list[AnswerRecord]
    version: int = Field(ge=1)
    updated_at: str
    last_error: str | None = None
