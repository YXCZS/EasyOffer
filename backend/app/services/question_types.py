from collections import Counter
from collections.abc import Iterable
from typing import Literal, Protocol

QuestionType = Literal["single", "multiple", "judge"]

TARGET_QUESTION_TYPES: tuple[QuestionType, ...] = (
    "single",
    "single",
    "single",
    "single",
    "multiple",
    "judge",
)
STRICT_QUESTION_TYPE_PROMPT_VERSION = "question-types-v1"

_TYPE_LABELS: dict[QuestionType, str] = {
    "single": "单选题",
    "multiple": "多选题",
    "judge": "判断题",
}
_TYPE_INSTRUCTIONS: dict[QuestionType, str] = {
    "single": "必须为单选题，提供 4 个互斥选项，answer 恰好包含 1 个选项 key。",
    "multiple": "必须为多选题，提供 4 个选项，answer 至少包含 2 个正确选项 key。",
    "judge": "必须为判断题，只提供‘正确’和‘错误’两个选项，answer 恰好包含 1 个选项 key。",
}
_TRUE_SYNONYMS = {"正确", "对", "是", "true", "correct", "yes"}
_FALSE_SYNONYMS = {"错误", "错", "否", "false", "incorrect", "no"}


class TypedQuestion(Protocol):
    type: str


def target_question_type(question_number: int) -> QuestionType:
    if not 1 <= question_number <= len(TARGET_QUESTION_TYPES):
        raise ValueError(f"题号必须在 1-{len(TARGET_QUESTION_TYPES)} 之间")
    return TARGET_QUESTION_TYPES[question_number - 1]


def question_type_label(question_type: str) -> str:
    try:
        return _TYPE_LABELS[question_type]  # type: ignore[index]
    except KeyError as exc:
        raise ValueError(f"不支持的题型：{question_type}") from exc


def question_type_prompt_instruction(question_type: str) -> str:
    try:
        return _TYPE_INSTRUCTIONS[question_type]  # type: ignore[index]
    except KeyError as exc:
        raise ValueError(f"不支持的题型：{question_type}") from exc


def validate_question_target_type(question: TypedQuestion, question_number: int) -> None:
    target = target_question_type(question_number)
    if question.type != target:
        raise ValueError(
            f"第 {question_number} 题目标题型为 {target}，模型实际返回 {question.type}"
        )


def validate_quiz_type_quota(questions: Iterable[TypedQuestion]) -> None:
    counts = Counter(question.type for question in questions)
    expected = Counter(TARGET_QUESTION_TYPES)
    if counts != expected:
        raise ValueError(
            "完整题组必须包含 4 道单选题、1 道多选题和 1 道判断题；"
            f"实际为 single={counts['single']}、multiple={counts['multiple']}、judge={counts['judge']}"
        )


def normalize_judge_option_text(text: str) -> str:
    normalized = " ".join(str(text).strip().split())
    lowered = normalized.lower()
    if lowered in _TRUE_SYNONYMS:
        return "正确"
    if lowered in _FALSE_SYNONYMS:
        return "错误"
    raise ValueError("判断题选项必须是语义明确的‘正确’和‘错误’")


def uses_strict_question_type_quota(prompt_version: str) -> bool:
    return prompt_version == STRICT_QUESTION_TYPE_PROMPT_VERSION
