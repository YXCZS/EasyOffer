import asyncio

import pytest

from app.api.v1.dependencies import get_db, get_quiz_service
from app.core.auth import create_access_token
from app.core.errors import KnowledgeDocumentAccessError, KnowledgeDocumentNotReadyError
from app.llm.deepseek import DeepSeekQuizGenerator
from app.main import app
from app.models.quiz import QuizGenerateOutput, QuizGenerateRequest
from app.research.evidence import EvidenceContext, build_evidence_context
from app.services.quiz_service import QuizService
from tests.sample_data import make_quiz


def test_document_request_is_optional_for_existing_clients():
    request = QuizGenerateRequest(user_input="RAG")
    assert request.document_id is None
    assert request.knowledge_only is False
    with pytest.raises(ValueError):
        QuizGenerateRequest(user_input="RAG", knowledge_only=True)


def test_document_endpoint_rejects_guest_without_calling_generator(client):
    response = client.post(
        "/api/v1/quiz/generate",
        json={"user_input": "RAG", "document_id": "doc-a", "knowledge_only": True},
    )
    assert response.status_code == 401
    assert response.json()["code"] == 4003


def test_document_endpoint_maps_not_ready_error(client, monkeypatch):
    class Generator:
        async def generate(self, request, user_id=None):
            raise AssertionError("document validation must happen before generation")

    async def get_document(*args):
        return {"status": "processing"}

    monkeypatch.setattr("app.repositories.knowledge_repository.get_document", get_document)
    app.dependency_overrides[get_quiz_service] = lambda: QuizService(Generator())
    app.dependency_overrides[get_db] = lambda: object()
    token = create_access_token(7, "openid-test")
    response = client.post(
        "/api/v1/quiz/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_input": "RAG", "document_id": "doc-a", "knowledge_only": True},
    )
    assert response.status_code == 409
    assert response.json()["code"] == 4004


def test_document_generation_requires_authenticated_owner(monkeypatch):
    called = False

    class Generator:
        async def generate(self, request, user_id=None):
            nonlocal called
            called = True
            return QuizGenerateOutput(quiz=make_quiz(request))

    async def get_document(*args):
        return {"status": "ready"}

    monkeypatch.setattr("app.repositories.knowledge_repository.get_document", get_document)
    service = QuizService(Generator())
    request = QuizGenerateRequest(user_input="RAG", document_id="doc-a", knowledge_only=True)
    with pytest.raises(KnowledgeDocumentAccessError):
        asyncio.run(service.generate(request))
    assert called is False


@pytest.mark.parametrize("document_status", ["processing", "failed"])
def test_document_generation_rejects_non_ready_document(monkeypatch, document_status):
    called = False

    class Generator:
        async def generate(self, request, user_id=None):
            nonlocal called
            called = True
            return QuizGenerateOutput(quiz=make_quiz(request))

    async def get_document(*args):
        return {"status": document_status}

    monkeypatch.setattr("app.repositories.knowledge_repository.get_document", get_document)
    service = QuizService(Generator())
    request = QuizGenerateRequest(user_input="RAG", document_id="doc-a", knowledge_only=True)
    with pytest.raises(KnowledgeDocumentNotReadyError):
        asyncio.run(service.generate(request, user_id=7, connection=object()))
    assert called is False


def test_document_evidence_is_filtered_and_never_uses_web(monkeypatch):
    class Doc:
        def __init__(self, document_id, text):
            self.page_content = text
            self.metadata = {"document_id": document_id, "source_name": f"{document_id}.md"}

    class Store:
        def search(self, query, k, document_id=None):
            assert query == "RAG"
            assert document_id == "doc-a"
            return [(Doc("doc-a", "RAG retrieval notes"), 0.1), (Doc("doc-b", "other notes"), 0.99)]

    class ForbiddenAgent:
        def __init__(self, *args, **kwargs):
            raise AssertionError("single-document mode must not construct Tavily")

    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", lambda user_id: Store())
    monkeypatch.setattr("app.research.tavily_agent.TavilyResearchAgent", ForbiddenAgent)
    context = asyncio.run(
        build_evidence_context("RAG", "ai", "medium", user_id=7, document_id="doc-a")
    )
    assert context.route == "document_only"
    assert context.used_personal_kb is True
    assert context.used_web is False
    assert context.tool_calls == ["personal_kb_search"]
    assert {item.source_id for item in context.evidence} == {"doc-a"}


def test_document_evidence_reads_ordered_chunks_instead_of_filename_search(monkeypatch):
    class Doc:
        def __init__(self, chunk_index, text):
            self.page_content = text
            self.metadata = {
                "document_id": "doc-a",
                "source_name": "unrelated-file-name.md",
                "chunk_index": chunk_index,
            }

    class Store:
        def get_document_chunks(self, document_id):
            assert document_id == "doc-a"
            # Chroma may return internal-id order; the evidence layer must
            # restore the source chunk order before building the prompt.
            return [
                Doc(2, "中间章节：向量数据库通过相似度检索召回证据。"),
                Doc(0, "开头章节：RAG 将检索结果注入生成上下文。"),
                Doc(1, "第二章节：切分策略决定检索粒度。"),
            ]

        def search(self, *args, **kwargs):
            raise AssertionError("document-only mode must not use filename similarity search")

    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", lambda user_id: Store())
    context = asyncio.run(
        build_evidence_context("unrelated-file-name.md", "general", "medium", user_id=7, document_id="doc-a")
    )

    assert context.used_personal_kb is True
    assert [item.text for item in context.evidence] == [
        "开头章节：RAG 将检索结果注入生成上下文。",
        "第二章节：切分策略决定检索粒度。",
        "中间章节：向量数据库通过相似度检索召回证据。",
    ]
    prompt = context.prompt_text()
    assert "RAG 将检索结果注入生成上下文" in prompt
    assert "unrelated-file-name.md" in prompt


def test_document_chunk_sampling_keeps_document_boundaries(monkeypatch):
    from app.research.evidence import _select_document_chunks

    class Doc:
        def __init__(self, chunk_index):
            self.page_content = f"chunk-{chunk_index}-" + ("x" * 900)
            self.metadata = {"chunk_index": chunk_index}

    rows = [(Doc(index), None) for index in range(20)]
    selected = _select_document_chunks(rows, max_chars=5000)
    indexes = [doc.metadata["chunk_index"] for doc, _ in selected]
    assert indexes[0] == 0
    assert indexes[-1] == 19
    assert indexes == sorted(set(indexes))
    assert sum(len(doc.page_content) for doc, _ in selected) <= 3800


def test_document_evidence_shortage_uses_base_model_and_records_fallback(monkeypatch):
    request = QuizGenerateRequest(user_input="学习笔记.md", document_id="doc-a", knowledge_only=True)
    evidence = EvidenceContext(route="document_only", confidence="none")
    captured: dict[str, str] = {}

    async def fake_build(*args, **kwargs):
        assert kwargs["document_id"] == "doc-a"
        return evidence

    async def fake_judge(*args, **kwargs):
        return {"supported": True, "message": ""}

    async def fake_generate(request, research=None, evidence_text=""):
        captured["evidence_text"] = evidence_text
        return QuizGenerateOutput(quiz=make_quiz(request))

    monkeypatch.setattr("app.research.evidence.build_evidence_context", fake_build)
    generator = DeepSeekQuizGenerator()
    monkeypatch.setattr(generator, "_judge", fake_judge)
    monkeypatch.setattr(generator, "_generate_questions", fake_generate)
    result = asyncio.run(generator.generate(request, user_id=7))

    assert result.quiz is not None
    assert result.quiz.evidence_meta["used_base_model"] is True
    assert result.quiz.evidence_meta["used_personal_kb"] is False
    assert result.quiz.evidence_meta["used_web"] is False
    assert result.quiz.evidence_meta["fallback_reason"] == "document_content_insufficient"
    assert "document_only_fallback" in captured["evidence_text"]
