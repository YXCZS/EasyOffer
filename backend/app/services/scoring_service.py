from dataclasses import dataclass

from app.models.report import AnswerRecord
from app.models.quiz import Question


@dataclass(frozen=True)
class ScoreSummary:
    score: int
    total: int
    accuracy: float
    mastered_points: list[str]
    review_points: list[str]


def calculate_score(questions: list[Question], records: list[AnswerRecord]) -> ScoreSummary:
    question_map = {question.id: question for question in questions}
    correct = 0
    mastered: list[str] = []
    review: list[str] = []
    for record in records:
        question = question_map[record.question_id]
        is_correct = set(record.selected_answers) == set(question.answer)
        if is_correct:
            correct += 1
            mastered.append(question.knowledge_point)
        else:
            review.append(question.knowledge_point)
    total = len(records)
    return ScoreSummary(
        score=correct,
        total=total,
        accuracy=round(correct / total * 100, 1),
        mastered_points=mastered,
        review_points=review,
    )
