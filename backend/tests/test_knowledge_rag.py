import asyncio

from app.research.evidence import build_evidence_context
from app.research.tavily_agent import ResearchContext, ResearchSource


class FakeDoc:
    page_content = "个人资料中的 RAG 评估方法"
    metadata = {"document_id": "doc-a", "source_name": "notes.md"}


class FakeStore:
    def search(self, query, k):
        assert query == "RAG" and k > 0
        return [(FakeDoc(), 0.92)]

    def get_document_chunks(self, document_id):
        assert document_id == "doc-a"
        return [FakeDoc()]


def test_personal_evidence_requires_explicit_document_id(monkeypatch):
    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", lambda user_id: FakeStore())
    context = asyncio.run(build_evidence_context("RAG", "ai", "medium", user_id=42, document_id="doc-a"))
    assert context.used_personal_kb is True
    assert context.used_web is False
    assert context.evidence[0].source_id == "doc-a"


def test_web_evidence_is_used_when_personal_retrieval_fails(monkeypatch):
    class BrokenStore:
        def search(self, query, k):
            raise RuntimeError("milvus unavailable")

    async def web(*args):
        return ResearchContext(status="success", sources=[ResearchSource(source_id="web-1", url="https://example.com", excerpt="current facts", retrieved_at="now")])

    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", lambda user_id: BrokenStore())
    monkeypatch.setattr("app.research.tavily_agent.TavilyResearchAgent.research", web)
    context = asyncio.run(build_evidence_context("Harness Engineering", "backend", "hard", user_id=7))
    assert context.used_personal_kb is False
    assert context.used_web is True
    assert "https://example.com" in context.citations
