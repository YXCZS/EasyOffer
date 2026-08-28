from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.models.common import StrictModel
from app.services.question_types import (
    normalize_judge_option_text,
    uses_strict_question_type_quota,
    validate_quiz_type_quota,
)
from app.services.topic_service import normalize_learning_topic

Role = Literal[
    "general",
    "java-backend",
    "backend",
    "frontend",
    "ai",
    "data-algorithm",
    "testing-devops",
    "mobile",
    "security",
]
Difficulty = Literal["easy", "medium", "hard"]
QuestionType = Literal["single", "multiple", "judge"]
ResearchMode = Literal["agent", "none"]
ResearchTool = Literal["tavily_search", "tavily_extract"]
VisualizationMode = Literal["image"]
VisualizationType = Literal["conceptual", "flowchart", "sequence", "er", "mindmap", "state"]
VisualizationStatus = Literal["none", "pending", "ready", "failed"]


class QuizGenerateRequest(StrictModel):
    user_input: str = Field(min_length=2, max_length=2000)
    role: Role = "general"
    difficulty: Difficulty = "medium"
    question_count: Literal[6] = 6
    document_id: str | None = Field(default=None, min_length=1, max_length=80)
    knowledge_only: bool = False
    use_personal_knowledge: bool = False
    generate_images: bool = False

    @field_validator("user_input")
    @classmethod
    def normalize_input(cls, value: str) -> str:
        value = " ".join(value.split())
        value = normalize_learning_topic(value)
        if len(value) < 2:
            raise ValueError("输入内容不能为空")
        return value

    @model_validator(mode="after")
    def validate_document_mode(self) -> "QuizGenerateRequest":
        if self.knowledge_only and not self.document_id:
            raise ValueError("knowledge_only 模式必须提供 document_id")
        return self


class QuestionOption(StrictModel):
    key: str = Field(pattern=r"^[A-F]$")
    text: str = Field(min_length=1, max_length=500)


class QuestionVisualization(StrictModel):
    enabled: bool = False
    mode: VisualizationMode | None = None
    type: VisualizationType | None = None
    image_prompt: str | None = Field(default=None, max_length=1200)
    alt_text: str | None = Field(default=None, max_length=200)
    asset_id: str | None = Field(default=None, max_length=80)
    image_url: str | None = Field(default=None, max_length=2000)
    status: VisualizationStatus = "none"


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
    visualization: QuestionVisualization | None = None

    @model_validator(mode="after")
    def validate_answer(self) -> "Question":
        keys = {option.key for option in self.options}
        if any(answer not in keys for answer in self.answer):
            raise ValueError("正确答案必须存在于选项中")
        if len(set(self.answer)) != len(self.answer):
            raise ValueError("正确答案不能重复")
        if self.type in ("single", "judge") and len(self.answer) != 1:
            raise ValueError("单选题和判断题只能有一个正确答案")
        if self.type == "multiple" and len(self.answer) < 2:
            raise ValueError("多选题至少需要两个正确答案")
        if self.type == "judge":
            if len(self.options) != 2:
                raise ValueError("判断题只能包含‘正确’和‘错误’两个选项")
            for option in self.options:
                option.text = normalize_judge_option_text(option.text)
            if {option.text for option in self.options} != {"正确", "错误"}:
                raise ValueError("判断题选项必须恰好包含‘正确’和‘错误’")
        if any(key not in self.option_explanations for key in keys):
            raise ValueError("每个选项都必须有解释")
        return self


class QuizSource(StrictModel):
    source_id: str = Field(min_length=1, max_length=80)
    title: str = Field(default="", max_length=300)
    url: str = Field(min_length=1, max_length=2000)
    site: str = Field(default="", max_length=200)
    excerpt: str = Field(default="", max_length=12000)
    retrieved_at: str = Field(min_length=1, max_length=80)


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
    research_used: bool = False
    research_mode: ResearchMode = "none"
    research_tools: list[ResearchTool] = Field(default_factory=list)
    research_fallback_reason: str | None = Field(default=None, max_length=100)
    sources: list[QuizSource] = Field(default_factory=list, max_length=20)
    retrieved_at: str | None = Field(default=None, max_length=80)
    evidence_meta: dict[str, object] = Field(default_factory=dict)
    generate_images: bool = False

    @model_validator(mode="after")
    def validate_unique_questions(self) -> "Quiz":
        ids = [question.id for question in self.questions]
        if len(set(ids)) != len(ids):
            raise ValueError("题目 ID 不能重复")
        stems = [" ".join(question.stem.lower().split()) for question in self.questions]
        if len(set(stems)) != len(stems):
            raise ValueError("题目不能重复")
        if uses_strict_question_type_quota(self.prompt_version):
            validate_quiz_type_quota(self.questions)
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
