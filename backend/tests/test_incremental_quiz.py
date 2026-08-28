import asyncio
import uuid

import aiomysql
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.api.v1.dependencies import get_incremental_quiz_service
from app.main import app
from app.models.generation import QuizGenerationTaskCreateRequest, QuizGenerationTaskProgressRequest
from app.models.quiz import QuizGenerateRequest
from app.repositories import generation_repository
from app.services.incremental_quiz_service import IncrementalQuizService
from tests.sample_data import make_quiz


def test_generation_request_normalizes_topic_and_rejects_invalid_document_mode():
    payload = QuizGenerationTaskCreateRequest(user_input="  Redis   缓存 ")
    assert payload.user_input == "Redis 缓存"
    with pytest.raises(ValueError):
        QuizGenerationTaskCreateRequest(user_input="Redis", knowledge_only=True)


def test_generation_task_create_returns_before_model_execution(monkeypatch):
    request = QuizGenerationTaskCreateRequest(user_input="Redis 缓存")

    async def create_task(_connection, task_id, user_id, payload):
        return {
            "task_id": task_id,
            "status": "queued",
            "generated_count": 0,
            "total_count": 6,
            "version": 1,
            "progress_version": 1,
            "current_index": 0,
            "questions": [],
            "answer_records": [],
            "quiz": None,
            "updated_at": "now",
        }

    monkeypatch.setattr(generation_repository, "create_task", create_task)
    service = IncrementalQuizService(object())
    snapshot = asyncio.run(service.create(request, None, object()))
    assert snapshot.status == "queued"
    assert snapshot.task_id.startswith("gen_")
    assert snapshot.generated_count == 0


def test_deepseek_single_question_generation_uses_strict_question_shape(monkeypatch):
    import json

    from app.llm import deepseek
    from app.llm.deepseek import DeepSeekQuizGenerator

    payload = {
        "question": {
            "id": "q1",
            "type": "single",
            "stem": "Redis 的过期键由什么机制清理？",
            "options": [{"key": "A", "text": "惰性删除"}, {"key": "B", "text": "完全不清理"}],
            "answer": ["A"],
            "explanation": "访问时可以触发惰性删除。",
            "option_explanations": {"A": "正确", "B": "错误"},
            "knowledge_point": "过期策略",
            "misconception": "把过期和淘汰混为一谈",
            "difficulty": "medium",
            "version_context": "Redis 主流版本",
        }
    }
    monkeypatch.setattr(
        deepseek,
        "_chat_model",
        lambda *_args, **_kwargs: RunnableLambda(lambda _value: AIMessage(content=json.dumps(payload))),
    )
    request = QuizGenerateRequest(user_input="Redis 缓存")
    question = asyncio.run(
        DeepSeekQuizGenerator().generate_incremental_question(request, 1, [], {"evidence_text": ""})
    )
    assert question.id == "q1"
    assert question.options[0].text == "惰性删除"


def test_incremental_prompt_receives_deterministic_target_type(monkeypatch):
    import json

    from app.llm import deepseek
    from app.llm.deepseek import DeepSeekQuizGenerator

    request = QuizGenerateRequest(user_input="Redis 持久化")
    base = make_quiz(request)
    captured_prompts: list[str] = []
    response_index = 0

    def answer(prompt_value):
        nonlocal response_index
        captured_prompts.append(prompt_value.to_string())
        question = base.questions[response_index].model_dump()
        response_index += 1
        return AIMessage(content=json.dumps({"question": question}, ensure_ascii=False))

    monkeypatch.setattr(
        deepseek,
        "_chat_model",
        lambda *_args, **_kwargs: RunnableLambda(answer),
    )

    generator = DeepSeekQuizGenerator()
    for index in range(1, 7):
        question = asyncio.run(
            generator.generate_incremental_question(
                request,
                index,
                [],
                {"evidence_text": ""},
            )
        )
        assert question.type == base.questions[index - 1].type

    assert [
        next(
            item
            for item in ("single", "multiple", "judge")
            if f"Required question type: {item}" in prompt
        )
        for prompt in captured_prompts
    ] == ["single", "single", "single", "single", "multiple", "judge"]


def test_incremental_question_plan_has_six_distinct_learning_goals():
    from app.llm.deepseek import DeepSeekQuizGenerator

    request = QuizGenerateRequest(user_input="RAG 缂撳瓨")
    plan = DeepSeekQuizGenerator._fallback_question_plan(request)
    assert len(plan) == 6
    assert len({item["knowledge_point"] for item in plan}) == 6
    assert [item["type"] for item in plan] == [
        "single", "single", "single", "single", "multiple", "judge"
    ]
    assert all(item["objective"] for item in plan)


def test_prepare_incremental_does_not_start_or_wait_for_question_plan(monkeypatch):
    from app.llm.deepseek import DeepSeekQuizGenerator

    async def supported_judgement(self, request, **_kwargs):
        return {"supported": True, "message": None}

    async def unexpected_plan(*_args, **_kwargs):
        raise AssertionError("逐题生成不应创建六题蓝图任务")

    monkeypatch.setattr(DeepSeekQuizGenerator, "_judge", supported_judgement)
    monkeypatch.setattr(DeepSeekQuizGenerator, "_build_question_plan", unexpected_plan)
    prepared = asyncio.run(
        DeepSeekQuizGenerator().prepare_incremental(QuizGenerateRequest(user_input="RAG 缓存"))
    )
    assert prepared["supported"] is True
    assert "question_plan" not in prepared
    assert "_question_plan_task" not in prepared


def test_prepare_incremental_uses_base_model_when_first_question_evidence_times_out(monkeypatch):
    from app.llm.deepseek import DeepSeekQuizGenerator

    async def supported_judgement(self, request, **_kwargs):
        return {"supported": True, "message": None}

    async def slow_evidence(*_args, **_kwargs):
        await asyncio.sleep(0.05)

    settings = get_settings()
    monkeypatch.setattr(settings, "incremental_first_question_evidence_timeout_seconds", 0.001)
    monkeypatch.setattr(settings, "incremental_evidence_timeout_seconds", 1.0)
    monkeypatch.setattr(DeepSeekQuizGenerator, "_judge", supported_judgement)
    monkeypatch.setattr("app.research.evidence.build_evidence_context", slow_evidence)
    prepared = asyncio.run(
        DeepSeekQuizGenerator().prepare_incremental(
            QuizGenerateRequest(user_input="Harness Engineering"), user_id=7
        )
    )
    assert prepared["supported"] is True
    assert prepared["evidence_meta"]["used_base_model"] is True
    assert "fallback_reason" in prepared["evidence_meta"]


def test_guest_prepare_incremental_never_starts_research(monkeypatch):
    from app.llm.deepseek import DeepSeekQuizGenerator

    async def supported_judgement(self, request, **_kwargs):
        return {"supported": True, "message": None}

    class ForbiddenProvider:
        async def research(self, *_args, **_kwargs):
            raise AssertionError("guest generation must not call Tavily")

    monkeypatch.setattr(DeepSeekQuizGenerator, "_judge", supported_judgement)
    prepared = asyncio.run(
        DeepSeekQuizGenerator(ForbiddenProvider()).prepare_incremental(
            QuizGenerateRequest(user_input="RAG")
        )
    )
    assert prepared["evidence_meta"]["route"] == "none"
    assert prepared["evidence_meta"]["used_base_model"] is True


def test_generation_task_repository_lifecycle():
    async def run() -> None:
        settings = get_settings()
        connection = await aiomysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            db=settings.mysql_database,
            charset="utf8mb4",
        )
        task_id = f"test_gen_{uuid.uuid4().hex}"
        try:
            row = await generation_repository.create_task(
                connection,
                task_id,
                None,
                QuizGenerateRequest(user_input="Redis 缓存").model_dump(),
            )
            assert row["status"] == "queued"
            assert row["version"] == 1
            assert await generation_repository.claim_task(connection, task_id, None)
            question = make_quiz(QuizGenerateRequest(user_input="Redis 缓存")).questions[0].model_dump()
            row = await generation_repository.append_question(connection, task_id, None, question, 1)
            assert row["generated_count"] == 1
            assert row["version"] == 2
            assert await generation_repository.append_question(connection, task_id, None, question, 1) is None
            row = await generation_repository.save_progress(
                connection,
                task_id,
                None,
                1,
                [{"question_id": "q1", "selected_answers": ["A"], "duration_ms": 10}],
                1,
            )
            assert row["progress_version"] == 2
            failed = await generation_repository.mark_failed(connection, task_id, None, "temporary model failure")
            assert failed["status"] == "failed"
            row = await generation_repository.save_progress(
                connection,
                task_id,
                None,
                1,
                [{"question_id": "q1", "selected_answers": ["B"], "duration_ms": 20}],
                2,
            )
            assert row["status"] == "failed"
            assert row["progress_version"] == 3
            assert await generation_repository.retry_task(connection, task_id, None)
            assert await generation_repository.claim_task(connection, task_id, None)
            quiz = make_quiz(QuizGenerateRequest(user_input="Redis 缓存")).model_copy(update={"quiz_id": task_id})
            row = await generation_repository.mark_completed(
                connection, task_id, None, quiz.quiz_id, quiz.model_dump(), quiz.title, quiz.summary
            )
            assert row["status"] == "completed"
            assert row["quiz"]["quiz_id"] == task_id
        finally:
            async with connection.cursor() as cursor:
                await cursor.execute("DELETE FROM quiz_generation_tasks WHERE task_id=%s", (task_id,))
                await connection.commit()
            connection.close()

    asyncio.run(run())


class _Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_):
        return False


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _Acquire(self.connection)


def test_incremental_service_appends_questions_in_order(monkeypatch):
    request = QuizGenerateRequest(user_input="Redis 缓存", generate_images=True)
    base = make_quiz(request)
    state = {
        "task_id": "task-test",
        "status": "generating",
        "version": 1,
        "progress_version": 1,
        "questions": [],
        "answer_records": [],
        "generated_count": 0,
        "total_count": 6,
        "current_index": 0,
        "request": request.model_dump(),
        "updated_at": "now",
    }

    async def get_task(_connection, _task_id, _user_id):
        return dict(state, questions=list(state["questions"]))

    async def append_question(_connection, _task_id, _user_id, question, expected_version):
        if expected_version != state["version"]:
            return None
        state["questions"].append(question)
        state["generated_count"] += 1
        state["version"] += 1
        return dict(state, questions=list(state["questions"]))

    async def mark_completed(_connection, _task_id, _user_id, quiz_id, quiz, title, summary):
        state.update(status="completed", quiz=quiz, quiz_id=quiz_id, title=title, summary=summary)
        return dict(state, questions=list(state["questions"]))

    monkeypatch.setattr(generation_repository, "get_task", get_task)
    monkeypatch.setattr(generation_repository, "append_question", append_question)
    monkeypatch.setattr(generation_repository, "mark_completed", mark_completed)

    from app.repositories import visual_asset_repository

    async def bind_task_assets(_connection, _task_id, _quiz_id):
        return None

    async def sync_task_asset_snapshots(_connection, _task_id, _quiz_id):
        return None

    monkeypatch.setattr(visual_asset_repository, "bind_task_assets", bind_task_assets)
    monkeypatch.setattr(visual_asset_repository, "sync_task_asset_snapshots", sync_task_asset_snapshots)
    scheduled: list[str] = []

    class VisualAssets:
        async def schedule(self, _pool, question, **_kwargs):
            scheduled.append(question.id)
            return f"asset-{question.id}"

    calls: dict[int, int] = {}

    class FakeGenerator:
        async def prepare_incremental(self, request, user_id=None):
            return {"supported": True, "evidence_meta": {}, "evidence_text": ""}

        async def generate_incremental_question(self, request, index, existing_stems, prepared):
            calls[index] = calls.get(index, 0) + 1
            if index == 5 and calls[index] == 1:
                return base.questions[index - 1].model_copy(update={"type": "single", "answer": ["A"]})
            return base.questions[index - 1]

        def finalize_incremental(self, request, questions, prepared, quiz_id):
            return base.model_copy(update={"quiz_id": quiz_id, "questions": questions})

    service = IncrementalQuizService(FakeGenerator(), visual_assets=VisualAssets())
    asyncio.run(service._generate_all(_Pool(object()), "task-test", None, request))
    assert state["status"] == "completed"
    assert state["generated_count"] == 6
    assert [item["id"] for item in state["questions"]] == [f"q{i}" for i in range(1, 7)]
    assert calls[5] == 2
    assert [item["type"] for item in state["questions"]] == [
        "single", "single", "single", "single", "multiple", "judge"
    ]
    assert scheduled == [f"q{i}" for i in range(1, 7)]


def test_incremental_service_falls_back_after_invalid_single_question(monkeypatch):
    request = QuizGenerateRequest(user_input="RAG 检索")
    base = make_quiz(request)
    state = {
        "task_id": "task-fallback",
        "status": "generating",
        "version": 1,
        "progress_version": 1,
        "questions": [],
        "answer_records": [],
        "generated_count": 0,
        "total_count": 6,
        "current_index": 0,
        "request": request.model_dump(),
        "updated_at": "now",
    }

    async def get_task(_connection, _task_id, _user_id):
        return dict(state, questions=list(state["questions"]))

    async def append_question(_connection, _task_id, _user_id, question, expected_version):
        assert expected_version == state["version"]
        state["questions"].append(question)
        state["generated_count"] += 1
        state["version"] += 1
        return dict(state, questions=list(state["questions"]))

    async def mark_completed(_connection, _task_id, _user_id, quiz_id, quiz, title, summary):
        state.update(status="completed", quiz=quiz, quiz_id=quiz_id, title=title, summary=summary)
        return dict(state, questions=list(state["questions"]))

    monkeypatch.setattr(generation_repository, "get_task", get_task)
    monkeypatch.setattr(generation_repository, "append_question", append_question)
    monkeypatch.setattr(generation_repository, "mark_completed", mark_completed)

    class BrokenGenerator:
        async def prepare_incremental(self, request, user_id=None):
            return {"supported": True, "evidence_meta": {}, "evidence_text": ""}

        async def generate_incremental_question(self, request, index, existing_stems, prepared):
            raise ValueError("invalid model payload")

        def finalize_incremental(self, request, questions, prepared, quiz_id):
            return base.model_copy(update={"quiz_id": quiz_id, "questions": questions})

    service = IncrementalQuizService(BrokenGenerator(), max_question_attempts=2)
    asyncio.run(service._generate_all(_Pool(object()), "task-fallback", None, request))
    assert state["status"] == "completed"
    assert state["generated_count"] == 6
    assert all(item["id"].startswith("fallback-") for item in state["questions"])
    assert [item["type"] for item in state["questions"]] == [
        "single", "single", "single", "single", "multiple", "judge"
    ]
    assert state["questions"][4]["answer"] == ["A", "B"]
    assert [item["text"] for item in state["questions"][5]["options"]] == ["正确", "错误"]


def test_fallback_questions_cover_distinct_blueprint_dimensions():
    request = QuizGenerateRequest(user_input="RAG 技术")
    from app.llm.deepseek import DeepSeekQuizGenerator

    plan = DeepSeekQuizGenerator._fallback_question_plan(request)
    questions = []
    for index, plan_item in enumerate(plan, 1):
        questions.append(
            IncrementalQuizService._fallback_question(request, index, [q.stem for q in questions], plan_item)
        )
    assert len({question.stem for question in questions}) == 6
    assert len({question.knowledge_point for question in questions}) == 6
    assert len({question.explanation for question in questions}) == 6
    assert all(
        IncrementalQuizService._question_diversity_error(question, questions[:index - 1], plan[index - 1]) is None
        for index, question in enumerate(questions, 1)
    )


def test_semantically_duplicate_question_is_rejected():
    request = QuizGenerateRequest(user_input="Redis 持久化")
    first = IncrementalQuizService._fallback_question(
        request, 1, [], {"knowledge_point": "Redis 持久化·核心概念", "objective": "解释定义", "type": "single"}
    )
    duplicate = first.model_copy(update={"id": "q2", "stem": "Redis 持久化的核心概念，以下哪项表述最准确？"})
    assert IncrementalQuizService._question_diversity_error(duplicate, [first], {"knowledge_point": "Redis 持久化·核心概念"})


def test_same_core_conclusion_with_different_scenario_is_rejected():
    request = QuizGenerateRequest(user_input="Redis 持久化")
    first = IncrementalQuizService._fallback_question(request, 1, [])
    first = first.model_copy(
        update={
            "stem": "Redis 同时开启 RDB 和 AOF 后，重启时优先加载哪一种？",
            "knowledge_point": "Redis 持久化恢复优先级",
            "explanation": "同时启用时 Redis 通常优先加载 AOF，因为 AOF 的写入记录更完整。",
        }
    )
    duplicate = IncrementalQuizService._fallback_question(request, 2, [first.stem]).model_copy(
        update={
            "stem": "执行 BGSAVE 后 Redis 崩溃，同时存在 RDB 与 AOF 时会用哪个文件恢复？",
            "knowledge_point": "AOF 与 RDB 的重启恢复顺序",
            "explanation": "Redis 会优先用 AOF 恢复，因为 AOF 通常保留了更完整的写入历史。",
        }
    )

    assert IncrementalQuizService._question_diversity_error(duplicate, [first])


def test_incremental_service_retries_after_duplicate_model_response(monkeypatch):
    request = QuizGenerateRequest(user_input="Redis 缓存")
    base = make_quiz(request)
    state = {
        "task_id": "task-retry-duplicate", "status": "generating", "version": 1,
        "progress_version": 1, "questions": [], "answer_records": [],
        "generated_count": 0, "total_count": 6, "current_index": 0,
        "request": request.model_dump(), "updated_at": "now",
    }

    async def get_task(_connection, _task_id, _user_id):
        return dict(state, questions=list(state["questions"]))

    async def append_question(_connection, _task_id, _user_id, question, expected_version):
        assert expected_version == state["version"]
        state["questions"].append(question)
        state["generated_count"] += 1
        state["version"] += 1
        return dict(state, questions=list(state["questions"]))

    async def mark_completed(_connection, _task_id, _user_id, quiz_id, quiz, title, summary):
        state.update(status="completed", quiz=quiz, quiz_id=quiz_id, title=title, summary=summary)
        return dict(state, questions=list(state["questions"]))

    monkeypatch.setattr(generation_repository, "get_task", get_task)
    monkeypatch.setattr(generation_repository, "append_question", append_question)
    monkeypatch.setattr(generation_repository, "mark_completed", mark_completed)
    calls: dict[int, int] = {}

    class DuplicateOnceGenerator:
        async def prepare_incremental(self, request, user_id=None):
            return {"supported": True, "evidence_meta": {}, "evidence_text": {}}

        async def generate_incremental_question(self, request, index, existing_stems, prepared):
            calls[index] = calls.get(index, 0) + 1
            return base.questions[0] if index == 2 and calls[index] == 1 else base.questions[index - 1]

        def finalize_incremental(self, request, questions, prepared, quiz_id):
            return base.model_copy(update={"quiz_id": quiz_id, "questions": questions})

    asyncio.run(IncrementalQuizService(DuplicateOnceGenerator())._generate_all(_Pool(object()), state["task_id"], None, request))
    assert state["status"] == "completed"
    assert calls[2] == 2
    assert len({question["stem"] for question in state["questions"]}) == 6


def test_generation_progress_request_validates_version():
    payload = QuizGenerationTaskProgressRequest(current_index=1, progress_version=2)
    assert payload.progress_version == 2
    with pytest.raises(ValueError):
        QuizGenerationTaskProgressRequest(current_index=7, progress_version=1)


def test_redis_persistence_fallback_is_topic_specific():
    request = QuizGenerateRequest(user_input="我想学习Redis持久化机制", role="backend", difficulty="medium")
    question = IncrementalQuizService._fallback_question(request, 1, [])
    assert "Redis" in question.stem
    assert "持久化" in question.stem
    assert "RDB" in question.explanation or "AOF" in question.explanation
    assert question.knowledge_point.startswith("Redis 持久化")


def test_mysql_mvcc_explain_fallback_is_topic_specific_and_diverse():
    request = QuizGenerateRequest(user_input="MySQL MVCC 与 EXPLAIN 慢查询排查", role="backend")
    questions = [
        IncrementalQuizService._fallback_question(request, index, [])
        for index in range(1, 7)
    ]

    assert len({question.stem for question in questions}) == 6
    assert all(question.version_context == "MySQL 8.0 InnoDB" for question in questions)
    assert all("MySQL" in question.knowledge_point for question in questions)
    assert any("Read View" in question.explanation for question in questions)
    assert any("EXPLAIN ANALYZE" in question.explanation for question in questions)


def test_generation_task_api_returns_first_question_and_completes(monkeypatch):
    request = QuizGenerateRequest(user_input="Redis 缓存")
    base = make_quiz(request)

    class FakeGenerator:
        async def prepare_incremental(self, request, user_id=None):
            return {"supported": True, "evidence_meta": {}, "evidence_text": ""}

        async def generate_incremental_question(self, request, index, existing_stems, prepared):
            return base.questions[index - 1]

        def finalize_incremental(self, request, questions, prepared, quiz_id):
            return base.model_copy(update={"quiz_id": quiz_id, "questions": questions})

    service = IncrementalQuizService(FakeGenerator())
    app.dependency_overrides[get_incremental_quiz_service] = lambda: service
    task_id = None
    try:
        with TestClient(app) as client:
            created = client.post("/api/v1/quiz/generation-tasks", json=request.model_dump())
            assert created.status_code == 200
            task_id = created.json()["data"]["task_id"]
            snapshot = None
            for _ in range(20):
                response = client.get(f"/api/v1/quiz/generation-tasks/{task_id}")
                assert response.status_code == 200
                snapshot = response.json()["data"]
                if snapshot["status"] == "completed":
                    break
                import time

                time.sleep(0.05)
            assert snapshot["status"] == "completed", snapshot
            assert snapshot["generated_count"] == 6
            assert len(snapshot["questions"]) == 6
            assert [item["type"] for item in snapshot["questions"]] == [
                "single", "single", "single", "single", "multiple", "judge"
            ]
            assert snapshot["quiz"]["prompt_version"] == "question-types-v1"
    finally:
        app.dependency_overrides.pop(get_incremental_quiz_service, None)
        if task_id:
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
                        await cursor.execute("DELETE FROM quiz_generation_tasks WHERE task_id=%s", (task_id,))
                        await connection.commit()
                finally:
                    connection.close()

            asyncio.run(cleanup())
