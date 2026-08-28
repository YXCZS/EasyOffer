import asyncio
import uuid
from pathlib import Path

import aiomysql
import pytest

from app.services import user_service
from app.core.config import get_settings
from app.models.quiz import QuizGenerateRequest
from tests.sample_data import make_quiz


@pytest.fixture
def user_client(client, monkeypatch):
    openid = f"test-{uuid.uuid4().hex}"

    async def fake_exchange(_: str) -> str:
        return openid

    monkeypatch.setattr(user_service, "exchange_code_for_openid", fake_exchange)
    yield client, openid

    async def cleanup() -> None:
        settings = get_settings()
        connection = await aiomysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            db=settings.mysql_database,
            charset="utf8mb4",
        )
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("DELETE FROM users WHERE openid = %s", (openid,))
                await connection.commit()
        finally:
            connection.close()

    asyncio.run(cleanup())


def test_wechat_login_creates_user_and_returns_token(user_client):
    client, _ = user_client
    response = client.post("/api/v1/user/login", json={"code": "wx-code"})
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["token"]
    assert payload["user"]["nickname"] == "学习者"
    assert payload["user"]["total_xp"] == 0


def test_profile_requires_login(user_client):
    client, _ = user_client
    response = client.get("/api/v1/user/profile")
    assert response.status_code == 401


def test_profile_can_be_updated_and_read(user_client):
    client, _ = user_client
    token = client.post("/api/v1/user/login", json={"code": "wx-code"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    update = client.put("/api/v1/user/profile", json={"nickname": "面试学习者"}, headers=headers)
    assert update.status_code == 200
    assert update.json()["data"]["nickname"] == "面试学习者"

    profile = client.get("/api/v1/user/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["data"]["nickname"] == "面试学习者"


def test_avatar_upload_updates_profile(user_client):
    client, _ = user_client
    token = client.post("/api/v1/user/login", json={"code": "wx-code"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/user/avatar",
        headers=headers,
        files={"image": ("avatar.png", b"test-avatar", "image/png")},
    )

    assert response.status_code == 200
    avatar_url = response.json()["data"]["avatar_url"]
    assert "/uploads/avatars/user_" in avatar_url
    filename = avatar_url.rsplit("/", 1)[-1]
    Path("uploads/avatars", filename).unlink(missing_ok=True)


def test_avatar_upload_rejects_invalid_type_and_oversized_file(user_client):
    client, _ = user_client
    token = client.post("/api/v1/user/login", json={"code": "wx-code"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    invalid = client.post(
        "/api/v1/user/avatar",
        headers=headers,
        files={"image": ("avatar.gif", b"gif", "image/gif")},
    )
    assert invalid.status_code == 415

    oversized = client.post(
        "/api/v1/user/avatar",
        headers=headers,
        files={"image": ("avatar.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
    )
    assert oversized.status_code == 413


def test_history_empty_for_new_user(user_client):
    client, _ = user_client
    token = client.post("/api/v1/user/login", json={"code": "wx-code"}).json()["data"]["token"]
    response = client.get("/api/v1/user/quizzes", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["data"] == {"items": [], "total": 0, "page": 1, "page_size": 10}


def test_authenticated_quiz_report_persistence_and_xp(user_client):
    client, _ = user_client
    token = client.post("/api/v1/user/login", json={"code": "wx-code"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    request = QuizGenerateRequest(user_input="Redis 持久化机制", role="java-backend", difficulty="medium")
    quiz = make_quiz(request)

    generated = client.post(
        "/api/v1/quiz/generate",
        json=request.model_dump(),
        headers=headers,
    )
    assert generated.status_code == 200
    assert generated.json()["data"]["quiz_id"] == quiz.quiz_id

    report = client.post(
        "/api/v1/report/generate",
        json={
                "quiz_id": quiz.quiz_id,
                "topic": quiz.topic,
                "role": quiz.role,
                "questions": [question.model_dump() for question in quiz.questions],
                "answer_records": [
                    {"question_id": question.id, "selected_answers": question.answer, "duration_ms": 100}
                    for question in quiz.questions
                ],
        },
        headers=headers,
    )
    assert report.status_code == 200
    assert report.json()["data"]["score"] == 6

    duplicate = client.post(
        "/api/v1/report/generate",
        json={
            "quiz_id": quiz.quiz_id,
            "topic": quiz.topic,
            "role": quiz.role,
            "questions": [question.model_dump() for question in quiz.questions],
            "answer_records": [
                {"question_id": question.id, "selected_answers": question.answer, "duration_ms": 100}
                for question in quiz.questions
            ],
        },
        headers=headers,
    )
    assert duplicate.status_code == 200

    profile = client.get("/api/v1/user/profile", headers=headers).json()["data"]
    assert profile["quiz_count"] == 1
    assert profile["correct_count"] == 6
    assert profile["total_xp"] == 22

    history = client.get("/api/v1/user/quizzes", headers=headers).json()["data"]
    assert history["total"] == 1
    assert history["items"][0]["quiz_id"] == quiz.quiz_id

    detail = client.get(f"/api/v1/user/quizzes/{quiz.quiz_id}", headers=headers).json()["data"]
    assert detail["report"]["score"] == 6
    assert len(detail["answer_records"]) == 6
    stale_delete = client.delete(f"/api/v1/user/quizzes/{quiz.quiz_id}/progress", headers=headers)
    assert stale_delete.status_code == 200
    assert stale_delete.json()["data"] == {"abandoned": False}


def test_incomplete_quiz_progress_can_pause_resume_and_complete(user_client):
    client, _ = user_client
    token = client.post("/api/v1/user/login", json={"code": "wx-code"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    request = QuizGenerateRequest(user_input="Redis 持久化断点续答", role="backend", difficulty="medium")
    generated = client.post("/api/v1/quiz/generate", json=request.model_dump(), headers=headers)
    assert generated.status_code == 200
    quiz = generated.json()["data"]

    incomplete = client.get("/api/v1/user/quizzes/incomplete", headers=headers)
    assert incomplete.status_code == 200
    assert incomplete.json()["data"]["items"][0]["answered_count"] == 0

    partial_records = [
        {"question_id": question["id"], "selected_answers": ["A"], "duration_ms": 100}
        for question in quiz["questions"][:2]
    ]
    saved = client.put(
        f"/api/v1/user/quizzes/{quiz['quiz_id']}/progress",
        json={"current_index": 2, "answer_records": partial_records, "version": 1},
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["status"] == "in_progress"
    assert saved.json()["data"]["answered_count"] == 2

    resumed = client.get(f"/api/v1/user/quizzes/{quiz['quiz_id']}/progress", headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["data"]["current_index"] == 2
    assert len(resumed.json()["data"]["answer_records"]) == 2

    version = saved.json()["data"]["version"]
    all_records = [
        {"question_id": question["id"], "selected_answers": question["answer"], "duration_ms": 100}
        for question in quiz["questions"]
    ]
    ready = client.put(
        f"/api/v1/user/quizzes/{quiz['quiz_id']}/progress",
        json={"current_index": 5, "answer_records": all_records, "version": version},
        headers=headers,
    )
    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ready_for_report"
    assert ready.json()["data"]["answer_records"][4]["selected_answers"] == ["A", "C"]

    resumed_ready = client.get(f"/api/v1/user/quizzes/{quiz['quiz_id']}/progress", headers=headers)
    assert resumed_ready.status_code == 200
    assert resumed_ready.json()["data"]["answer_records"][4]["selected_answers"] == ["A", "C"]

    report = client.post(
        "/api/v1/report/generate",
        json={
            "quiz_id": quiz["quiz_id"],
            "topic": quiz["topic"],
            "role": quiz["role"],
            "questions": quiz["questions"],
            "answer_records": all_records,
        },
        headers=headers,
    )
    assert report.status_code == 200
    assert client.get("/api/v1/user/quizzes/incomplete", headers=headers).json()["data"]["items"] == []


def test_incomplete_quiz_can_be_abandoned_idempotently(user_client):
    client, _ = user_client
    token = client.post("/api/v1/user/login", json={"code": "wx-code"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    request = QuizGenerateRequest(user_input="Redis 缓存淘汰", role="backend", difficulty="easy")
    generated = client.post("/api/v1/quiz/generate", json=request.model_dump(), headers=headers)
    assert generated.status_code == 200
    quiz_id = generated.json()["data"]["quiz_id"]

    deleted = client.delete(f"/api/v1/user/quizzes/{quiz_id}/progress", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["data"] == {"abandoned": True}
    assert client.get("/api/v1/user/quizzes/incomplete", headers=headers).json()["data"]["items"] == []

    repeated = client.delete(f"/api/v1/user/quizzes/{quiz_id}/progress", headers=headers)
    assert repeated.status_code == 200
    assert repeated.json()["data"] == {"abandoned": False}


def test_ready_for_report_quiz_can_be_abandoned(user_client):
    client, _ = user_client
    token = client.post("/api/v1/user/login", json={"code": "wx-code"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    generated = client.post(
        "/api/v1/quiz/generate",
        json=QuizGenerateRequest(user_input="Redis 过期策略", role="backend", difficulty="medium").model_dump(),
        headers=headers,
    )
    quiz = generated.json()["data"]
    records = [
        {"question_id": question["id"], "selected_answers": ["A"], "duration_ms": 10}
        for question in quiz["questions"]
    ]
    ready = client.put(
        f"/api/v1/user/quizzes/{quiz['quiz_id']}/progress",
        json={"current_index": 5, "answer_records": records, "version": 1},
        headers=headers,
    )
    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ready_for_report"
    deleted = client.delete(f"/api/v1/user/quizzes/{quiz['quiz_id']}/progress", headers=headers)
    assert deleted.status_code == 200


def test_progress_delete_is_user_scoped(user_client, monkeypatch):
    client, owner_openid = user_client
    other_openid = f"other-{uuid.uuid4().hex}"

    async def exchange(code: str) -> str:
        return owner_openid if code == "owner-code" else other_openid

    monkeypatch.setattr(user_service, "exchange_code_for_openid", exchange)
    owner_token = client.post("/api/v1/user/login", json={"code": "owner-code"}).json()["data"]["token"]
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    generated = client.post(
        "/api/v1/quiz/generate",
        json=QuizGenerateRequest(user_input="MySQL 索引", role="backend", difficulty="easy").model_dump(),
        headers=owner_headers,
    )
    quiz_id = generated.json()["data"]["quiz_id"]
    other_token = client.post("/api/v1/user/login", json={"code": "other-code"}).json()["data"]["token"]
    response = client.delete(
        f"/api/v1/user/quizzes/{quiz_id}/progress",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert response.status_code == 200
    assert response.json()["data"] == {"abandoned": False}
    assert client.get("/api/v1/user/quizzes/incomplete", headers=owner_headers).json()["data"]["items"]

    async def cleanup_other() -> None:
        settings = get_settings()
        connection = await aiomysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            db=settings.mysql_database,
            charset="utf8mb4",
        )
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("DELETE FROM users WHERE openid = %s", (other_openid,))
                await connection.commit()
        finally:
            connection.close()

    asyncio.run(cleanup_other())


def test_abandon_progress_maps_storage_failure_to_service_unavailable(user_client, monkeypatch):
    client, _ = user_client
    token = client.post("/api/v1/user/login", json={"code": "wx-code"}).json()["data"]["token"]

    async def fail(*args, **kwargs):
        raise RuntimeError("database disconnected")

    monkeypatch.setattr("app.api.v1.routes.progress.progress_repository.abandon_progress", fail)
    response = client.delete(
        "/api/v1/user/quizzes/quiz_missing/progress",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "练习暂时无法删除，请稍后重试"


def test_knowledge_document_name_can_be_updated_without_reprocessing(user_client, monkeypatch):
    client, owner_openid = user_client
    token = client.post("/api/v1/user/login", json={"code": "wx-code"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    async def skip_processing(*args, **kwargs):
        return None

    monkeypatch.setattr("app.api.v1.routes.knowledge.process_document", skip_processing)
    uploaded = client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        files={"file": ("notes.md", b"RAG notes", "text/markdown")},
    )
    assert uploaded.status_code == 200
    original = uploaded.json()["data"]
    document_id = original["document_id"]

    renamed = client.patch(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=headers,
        json={"original_name": "  RAG 面试重点  "},
    )
    assert renamed.status_code == 200
    renamed_document = renamed.json()["data"]
    assert renamed_document["original_name"] == "RAG 面试重点"
    assert renamed_document["document_id"] == document_id
    assert renamed_document["status"] == original["status"]
    assert renamed_document["chunk_count"] == original["chunk_count"]

    renamed_by_put = client.put(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=headers,
        json={"original_name": "RAG 面试重点（已确认）"},
    )
    assert renamed_by_put.status_code == 200
    assert renamed_by_put.json()["data"]["original_name"] == "RAG 面试重点（已确认）"

    assert client.patch(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=headers,
        json={"original_name": "   "},
    ).status_code == 422
    assert client.patch(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=headers,
        json={"original_name": "x" * 256},
    ).status_code == 422

    other_openid = f"other-doc-{uuid.uuid4().hex}"

    async def exchange(code: str) -> str:
        return owner_openid if code == "owner-code" else other_openid

    monkeypatch.setattr(user_service, "exchange_code_for_openid", exchange)
    other_token = client.post("/api/v1/user/login", json={"code": "other-code"}).json()["data"]["token"]
    cross_user = client.patch(
        f"/api/v1/knowledge/documents/{document_id}",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"original_name": "不应被修改"},
    )
    assert cross_user.status_code == 404

    async def cleanup_other() -> None:
        settings = get_settings()
        connection = await aiomysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            db=settings.mysql_database,
            charset="utf8mb4",
        )
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("DELETE FROM users WHERE openid = %s", (other_openid,))
                await connection.commit()
        finally:
            connection.close()

    asyncio.run(cleanup_other())
    client.delete(f"/api/v1/knowledge/documents/{document_id}", headers=headers)


def test_progress_version_conflict_does_not_overwrite_newer_answers(user_client):
    client, _ = user_client
    token = client.post("/api/v1/user/login", json={"code": "wx-code"}).json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    request = QuizGenerateRequest(user_input="MySQL 索引", role="backend", difficulty="easy")
    quiz = client.post("/api/v1/quiz/generate", json=request.model_dump(), headers=headers).json()["data"]
    records = [{"question_id": quiz["questions"][0]["id"], "selected_answers": ["A"], "duration_ms": 1}]
    first = client.put(
        f"/api/v1/user/quizzes/{quiz['quiz_id']}/progress",
        json={"current_index": 1, "answer_records": records, "version": 1},
        headers=headers,
    )
    assert first.status_code == 200
    conflict = client.put(
        f"/api/v1/user/quizzes/{quiz['quiz_id']}/progress",
        json={"current_index": 1, "answer_records": records, "version": 1},
        headers=headers,
    )
    assert conflict.status_code == 409
