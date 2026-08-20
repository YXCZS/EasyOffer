def test_generate_quiz_returns_six_valid_questions(client):
    response = client.post(
        "/api/v1/quiz/generate",
        json={
            "user_input": "Java HashMap 在 JDK 8 中的扩容机制",
            "role": "java-backend",
            "difficulty": "medium",
            "question_count": 6,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["questions"]) == 6
    assert all(
        set(question["answer"]).issubset({item["key"] for item in question["options"]})
        for question in data["questions"]
    )


def test_non_technical_topic_returns_scope_error(client):
    response = client.post(
        "/api/v1/quiz/generate", json={"user_input": "如何准备明天的旅游行程"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == 4001
    assert response.json()["data"]["supported"] is False


def test_invalid_input_is_rejected(client):
    response = client.post("/api/v1/quiz/generate", json={"user_input": " "})
    assert response.status_code == 422


def test_generate_quiz_rejects_unsupported_question_count(client):
    response = client.post(
        "/api/v1/quiz/generate", json={"user_input": "Redis 缓存", "question_count": 5}
    )
    assert response.status_code == 422
