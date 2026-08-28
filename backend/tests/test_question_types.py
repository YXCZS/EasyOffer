from collections import Counter

import pytest
from pydantic import ValidationError

from app.models.quiz import Question, QuestionOption, Quiz
from app.services.question_types import (
    TARGET_QUESTION_TYPES,
    question_type_label,
    question_type_prompt_instruction,
    target_question_type,
    validate_question_target_type,
    validate_quiz_type_quota,
)


def make_question(index: int, question_type: str) -> Question:
    options = [
        QuestionOption(key="A", text="选项 A"),
        QuestionOption(key="B", text="选项 B"),
        QuestionOption(key="C", text="选项 C"),
        QuestionOption(key="D", text="选项 D"),
    ]
    answer = ["A"]
    if question_type == "multiple":
        answer = ["A", "C"]
    elif question_type == "judge":
        options = [
            QuestionOption(key="A", text="正确"),
            QuestionOption(key="B", text="错误"),
        ]
    return Question(
        id=f"q{index}",
        type=question_type,
        stem=f"第 {index} 题",
        options=options,
        answer=answer,
        explanation="用于验证题型契约。",
        option_explanations={option.key: "选项解释" for option in options},
        knowledge_point=f"知识点 {index}",
        misconception="常见误区",
        difficulty="medium",
        version_context="当前主流版本",
    )


def make_quiz(question_types: tuple[str, ...], *, prompt_version: str) -> Quiz:
    return Quiz(
        quiz_id="quiz_question_types",
        title="题型契约测试",
        summary="验证三种题型的固定组成。",
        topic="Redis",
        role="backend",
        difficulty="medium",
        questions=[make_question(index, item) for index, item in enumerate(question_types, start=1)],
        model_version="test-model",
        prompt_version=prompt_version,
    )


def test_target_question_types_are_deterministic_four_one_one():
    assert TARGET_QUESTION_TYPES == (
        "single",
        "single",
        "single",
        "single",
        "multiple",
        "judge",
    )
    assert Counter(TARGET_QUESTION_TYPES) == Counter(single=4, multiple=1, judge=1)
    assert [target_question_type(index) for index in range(1, 7)] == list(TARGET_QUESTION_TYPES)


@pytest.mark.parametrize("index", [0, 7])
def test_target_question_type_rejects_out_of_range_index(index: int):
    with pytest.raises(ValueError, match="题号"):
        target_question_type(index)


def test_target_type_validation_rejects_wrong_model_type():
    with pytest.raises(ValueError, match="目标题型"):
        validate_question_target_type(make_question(5, "single"), 5)


@pytest.mark.parametrize(
    ("question_type", "label", "instruction_fragment"),
    [
        ("single", "单选题", "恰好包含 1 个"),
        ("multiple", "多选题", "至少包含 2 个"),
        ("judge", "判断题", "‘正确’和‘错误’"),
    ],
)
def test_question_type_metadata_covers_all_supported_types(
    question_type: str,
    label: str,
    instruction_fragment: str,
):
    assert question_type_label(question_type) == label
    assert instruction_fragment in question_type_prompt_instruction(question_type)


@pytest.mark.parametrize("helper", [question_type_label, question_type_prompt_instruction])
def test_question_type_metadata_rejects_unknown_type(helper):
    with pytest.raises(ValueError, match="不支持的题型"):
        helper("essay")


def test_quiz_quota_validation_rejects_wrong_composition():
    questions = [make_question(index, "single") for index in range(1, 7)]
    with pytest.raises(ValueError, match="4 道单选题、1 道多选题和 1 道判断题"):
        validate_quiz_type_quota(questions)


def test_judge_question_normalizes_supported_synonyms():
    question = make_question(6, "judge")
    payload = question.model_dump()
    payload["options"] = [
        {"key": "A", "text": "是"},
        {"key": "B", "text": "否"},
    ]

    normalized = Question.model_validate(payload)

    assert [option.text for option in normalized.options] == ["正确", "错误"]


def test_judge_question_rejects_non_boolean_options():
    payload = make_question(6, "judge").model_dump()
    payload["options"] = [
        {"key": "A", "text": "可能正确"},
        {"key": "B", "text": "需要更多条件"},
    ]

    with pytest.raises(ValidationError, match="正确.*错误"):
        Question.model_validate(payload)


def test_multiple_question_rejects_duplicate_answer_keys():
    payload = make_question(5, "multiple").model_dump()
    payload["answer"] = ["A", "A"]

    with pytest.raises(ValidationError, match="不能重复"):
        Question.model_validate(payload)


def test_new_prompt_version_requires_four_one_one_quota():
    with pytest.raises(ValidationError, match="4 道单选题、1 道多选题和 1 道判断题"):
        make_quiz(("single",) * 6, prompt_version="question-types-v1")


def test_legacy_single_choice_quiz_remains_readable():
    quiz = make_quiz(("single",) * 6, prompt_version="quiz_prompt_v1")

    assert len(quiz.questions) == 6
    assert all(question.type == "single" for question in quiz.questions)


def test_new_prompt_version_accepts_exact_four_one_one_quota():
    quiz = make_quiz(TARGET_QUESTION_TYPES, prompt_version="question-types-v1")

    assert Counter(question.type for question in quiz.questions) == Counter(
        single=4,
        multiple=1,
        judge=1,
    )
