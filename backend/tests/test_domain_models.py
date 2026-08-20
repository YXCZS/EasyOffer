import pytest
from pydantic import ValidationError

from app.models.quiz import Question, QuestionOption


def test_question_rejects_answer_not_in_options():
    with pytest.raises(ValidationError, match="正确答案必须存在于选项中"):
        Question(
            id="q1",
            type="single",
            stem="题目",
            options=[QuestionOption(key="A", text="A"), QuestionOption(key="B", text="B")],
            answer=["C"],
            explanation="解释",
            option_explanations={"A": "错", "B": "错"},
            knowledge_point="知识点",
            misconception="误区",
            difficulty="medium",
            version_context="通用",
        )
