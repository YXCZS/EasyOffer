from app.models.quiz import QuizGenerateRequest
from tests.sample_data import make_quiz


def test_report_score_is_deterministic_and_excludes_confidence(client):
    quiz = make_quiz(
        QuizGenerateRequest(
            user_input="Redis 持久化机制", role="java-backend", difficulty="medium"
        )
    )
    response = client.post(
        "/api/v1/report/generate",
        json={
            "quiz_id": quiz.quiz_id,
            "topic": quiz.topic,
            "role": quiz.role,
            "questions": [question.model_dump() for question in quiz.questions],
            "answer_records": [
                {"question_id": question.id, "selected_answers": ["A"], "duration_ms": 1000}
                for question in quiz.questions[:4]
            ]
            + [{"question_id": quiz.questions[4].id, "selected_answers": ["B"]}],
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["score"] == 4
    assert data["total"] == 5
    assert data["accuracy"] == 80.0
    assert "confidence" not in data
    assert len(data["summary"]) == 3


def test_report_rejects_unknown_question_id(client):
    quiz = make_quiz(
        QuizGenerateRequest(
            user_input="Redis 持久化机制", role="java-backend", difficulty="medium"
        )
    )
    response = client.post(
        "/api/v1/report/generate",
        json={
            "quiz_id": quiz.quiz_id,
            "topic": quiz.topic,
            "role": quiz.role,
            "questions": [question.model_dump() for question in quiz.questions],
            "answer_records": [{"question_id": "missing", "selected_answers": ["A"]}],
        },
    )
    assert response.status_code == 422
