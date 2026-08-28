import asyncio

from app.core.config import get_settings
from app.research.evidence import (
    EvidenceContext,
    EvidenceItem,
    build_evidence_context,
    personal_kb_search_tool,
    plan_route,
)
from app.research.tavily_agent import ResearchContext, ResearchSource
from app.services.topic_service import normalize_learning_topic


def test_learning_topic_removes_conversational_prefixes():
    assert normalize_learning_topic("我想学习Redis持久化机制") == "Redis持久化机制"
    assert normalize_learning_topic("请给我讲一下 React Hooks") == "React Hooks"


def test_route_plan_is_structured_and_handles_forced_inputs():
    assert plan_route("https://example.com/docs", "backend", "medium").route == "extract"
    assert plan_route("React 19 最新版本", "frontend", "medium").route == "web_only"
    assert plan_route("根据我的资料学习 RAG", "ai", "medium", user_id=7).route in {"web_only", "none"}
    plan = plan_route("Harness Engineering", "backend", "hard", user_id=7)
    assert plan.route == "web_only"
    assert plan.max_tool_calls > 0
    assert plan.model_dump_json()


def test_evidence_context_deduplicates_and_keeps_source_metadata():
    context = EvidenceContext(route="hybrid")
    first = EvidenceItem("same evidence", "personal_kb", "doc-1", "notes.md", 0.9)
    context.add(first)
    context.add(EvidenceItem("same evidence", "web", "web-1", "https://example.com", None, "Example", "example.com", "now"))
    context.finalize()
    assert len(context.evidence) == 1
    assert context.source_types == ["personal_kb"]


def test_personal_tool_is_user_scoped(monkeypatch):
    class FakeDoc:
        page_content = "RAG notes"
        metadata = {"document_id": "doc-1", "source_name": "notes.md"}

    class Store:
        def search(self, query, k):
            assert query == "RAG"
            return [(FakeDoc(), 0.8)]

    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", lambda user_id: Store())
    tool = personal_kb_search_tool(42)
    result = tool.invoke({"query": "RAG", "k": 2})
    assert result[0]["document_id"] == "doc-1"


def test_document_only_evidence_does_not_call_web(monkeypatch):
    class Doc:
        page_content = "RAG document facts"
        metadata = {"document_id": "doc-a", "source_name": "notes.md", "chunk_index": 0}

    class Store:
        def get_document_chunks(self, document_id):
            assert document_id == "doc-a"
            return [Doc()]

    async def unexpected_web(*_args, **_kwargs):
        raise AssertionError("document-only route must not call Tavily")

    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", lambda _user_id: Store())
    monkeypatch.setattr("app.research.tavily_agent.TavilyResearchAgent.research", unexpected_web)
    context = asyncio.run(build_evidence_context("notes.md", "ai", "medium", user_id=7, document_id="doc-a"))
    assert context.used_personal_kb is True
    assert context.used_web is False


def test_ordinary_login_topic_does_not_search_personal_kb(monkeypatch):
    class FakeDoc:
        page_content = "RAG retrieval overview"
        metadata = {"document_id": "doc-1", "source_name": "notes.md"}

    class Store:
        def search(self, query, k):
            return [(FakeDoc(), 0.55)]

    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", lambda user_id: Store())
    settings = get_settings()
    monkeypatch.setattr(settings, "agentic_rag_enabled", True)
    context = asyncio.run(build_evidence_context("RAG retrieval", "ai", "medium", user_id=42))
    assert context.used_personal_kb is False
