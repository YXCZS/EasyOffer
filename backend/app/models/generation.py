from typing import Literal

from pydantic import Field, model_validator

from app.models.common import StrictModel
from app.models.progress import AnswerRecord
from app.models.quiz import Difficulty, Question, Quiz, Role

GenerationTaskStatus = Literal["queued", "generating", "completed", "failed", "expired"]


class QuizGenerationTaskCreateRequest(StrictModel):
    user_input: str = Field(min_length=2, max_length=2000)
    role: Role = "general"
    difficulty: Difficulty = "medium"
    question_count: Literal[6] = 6
    document_id: str | None = Field(default=None, min_length=1, max_length=80)
    knowledge_only: bool = False
    use_personal_knowledge: bool = False
    generate_images: bool = False

    @model_validator(mode="after")
    def validate_document_mode(self) -> "QuizGenerationTaskCreateRequest":
        if self.knowledge_only and not self.document_id:
            raise ValueError("knowledge_only 模式必须提供 document_id")
        self.user_input = " ".join(self.user_input.split())
        return self

    def to_quiz_request(self):
        from app.models.quiz import QuizGenerateRequest

        return QuizGenerateRequest(
            user_input=self.user_input,
            role=self.role,
            difficulty=self.difficulty,
            question_count=self.question_count,
            document_id=self.document_id,
            knowledge_only=self.knowledge_only,
            use_personal_knowledge=self.use_personal_knowledge,
            generate_images=self.generate_images,
        )


class QuizGenerationTaskProgressRequest(StrictModel):
    current_index: int = Field(ge=0, le=6)
    answer_records: list[AnswerRecord] = Field(default_factory=list, max_length=6)
    progress_version: int = Field(default=1, ge=1)


class QuizGenerationTaskSnapshot(StrictModel):
    task_id: str
    status: GenerationTaskStatus
    generated_count: int = Field(ge=0, le=6)
    total_count: int = Field(ge=1, le=6)
    version: int = Field(ge=1)
    progress_version: int = Field(ge=1)
    current_index: int = Field(ge=0, le=6)
    questions: list[Question] = Field(default_factory=list, max_length=6)
    answer_records: list[AnswerRecord] = Field(default_factory=list, max_length=6)
    title: str = ""
    summary: str = ""
    quiz: Quiz | None = None
    error_message: str | None = None
    retryable: bool = False
    updated_at: str
