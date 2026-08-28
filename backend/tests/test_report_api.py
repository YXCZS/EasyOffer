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
            + [
                {"question_id": quiz.questions[4].id, "selected_answers": ["C", "A"]},
                {"question_id": quiz.questions[5].id, "selected_answers": ["B"]},
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["score"] == 5
    assert data["total"] == 6
    assert data["accuracy"] == 83.3
    assert "confidence" not in data
    assert len(data["summary"]) == 3
    assert len(data["question_results"]) == 6
    assert data["question_results"][0]["status"] == "correct"
    assert data["question_results"][0]["selected_answers"] == ["A"]
    assert data["question_results"][0]["correct_answers"] == ["A"]
    assert data["question_results"][4]["status"] == "correct"
    assert data["question_results"][4]["selected_answers"] == ["C", "A"]
    assert data["question_results"][4]["correct_answers"] == ["A", "C"]
    assert data["question_results"][5]["status"] == "incorrect"
    assert data["question_results"][5]["selected_answer_texts"] == ["错误"]
    assert data["question_results"][5]["correct_answer_texts"] == ["正确"]


def test_report_multiple_choice_requires_exact_answer_set(client):
    quiz = make_quiz(QuizGenerateRequest(user_input="Redis 持久化机制", role="backend"))
    multiple = quiz.questions[4]
    judge = quiz.questions[5]
    response = client.post(
        "/api/v1/report/generate",
        json={
            "quiz_id": quiz.quiz_id,
            "topic": quiz.topic,
            "role": quiz.role,
            "questions": [multiple.model_dump(), judge.model_dump()],
            "answer_records": [
                {"question_id": multiple.id, "selected_answers": ["A"]},
                {"question_id": judge.id, "selected_answers": ["A"]},
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["score"] == 1
    assert [item["status"] for item in data["question_results"]] == ["incorrect", "correct"]


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
