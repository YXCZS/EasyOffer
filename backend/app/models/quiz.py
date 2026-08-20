from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.models.common import StrictModel

Role = Literal["general", "java-backend", "frontend"]
Difficulty = Literal["easy", "medium", "hard"]
QuestionType = Literal["single", "multiple", "judge"]


class QuizGenerateRequest(StrictModel):
    user_input: str = Field(min_length=2, max_length=2000)
    role: Role = "general"
    difficulty: Difficulty = "medium"
    question_count: Literal[6] = 6

    @field_validator("user_input")
    @classmethod
    def normalize_input(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("输入内容不能为空")
        return value


class QuestionOption(StrictModel):
    key: str = Field(pattern=r"^[A-F]$")
    text: str = Field(min_length=1, max_length=500)


class Question(StrictModel):
    id: str = Field(min_length=1, max_length=50)
    type: QuestionType
    stem: str = Field(min_length=1, max_length=1000)
    options: list[QuestionOption] = Field(min_length=2, max_length=4)
    answer: list[str] = Field(min_length=1, max_length=4)
    explanation: str = Field(min_length=1, max_length=2000)
    option_explanations: dict[str, str] = Field(min_length=1)
    knowledge_point: str = Field(min_length=1, max_length=100)
    misconception: str = Field(min_length=1, max_length=200)
    difficulty: Difficulty
    version_context: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_answer(self) -> "Question":
        keys = {option.key for option in self.options}
        if any(answer not in keys for answer in self.answer):
            raise ValueError("正确答案必须存在于选项中")
        if self.type in ("single", "judge") and len(self.answer) != 1:
            raise ValueError("单选题和判断题只能有一个正确答案")
        if self.type == "multiple" and len(self.answer) < 2:
            raise ValueError("多选题至少需要两个正确答案")
        if any(key not in self.option_explanations for key in keys):
            raise ValueError("每个选项都必须有解释")
        return self


class Quiz(StrictModel):
    quiz_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=500)
    topic: str = Field(min_length=1, max_length=2000)
    role: Role
    difficulty: Difficulty
    questions: list[Question] = Field(min_length=6, max_length=6)
    model_version: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_unique_questions(self) -> "Quiz":
        ids = [question.id for question in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("题目 ID 不能重复")
        stems = [" ".join(question.stem.lower().split()) for question in self.questions]
        if len(set(stems)) != len(stems):
            raise ValueError("题目不能重复")
        return self


class QuizGenerateOutput(StrictModel):
    supported: bool = True
    message: str | None = None
    quiz: Quiz | None = None

    @model_validator(mode="after")
    def validate_supported_output(self) -> "QuizGenerateOutput":
        if self.supported and self.quiz is None:
            raise ValueError("支持的主题必须返回题组")
        if not self.supported and not self.message:
            raise ValueError("不支持的主题必须返回提示")
        return self
