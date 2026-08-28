import asyncio
import json

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.core.config import get_settings
from app.llm.deepseek import DeepSeekQuizGenerator
from app.llm.deepseek import _normalize_quiz_payload
from app.models.quiz import QuizGenerateRequest
from app.research.tavily_agent import (
    QueryExpansionPlan,
    ResearchContext,
    ResearchSource,
    TavilyResearchAgent,
    _clean_url,
    _deduplicate_sources,
    _normalize_result,
    split_content_chunks,
    validate_query_plan,
)
from tests.sample_data import make_quiz


def test_research_context_prompt_is_bounded_and_marks_untrusted_data():
    context = ResearchContext(
        status="success",
        summary="A" * 500,
        sources=[ResearchSource(source_id="s1", url="https://example.com", retrieved_at="now", excerpt="B" * 500)],
    )
    text = context.prompt_text(120)
    assert len(text) <= 120
    assert "系统指令" in text


def test_tavily_agent_without_key_returns_structured_fallback(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "tavily_api_key", None)
    monkeypatch.setattr(settings, "tavily_enabled", True)
    result = asyncio.run(TavilyResearchAgent().research("Harness Engineering", "backend", "medium"))
    assert result.status == "failed"
    assert result.fallback_reason == "tavily_disabled"


def test_quiz_payload_normalizes_model_aliases():
    request = QuizGenerateRequest(user_input="Harness Engineering")
    payload = {"questions": [{
        "type": "multiple_choice", "stem": "Which?", "options": ["A", "B"],
        "answer": ["A", "B"], "explanation": "Because", "option_explanations": {"A": "yes", "B": "yes"},
        "knowledge_point": "Harness", "misconception": "none", "difficulty": "中等", "version_context": "current",
    }] * 6}
    normalized = _normalize_quiz_payload(payload, request)
    assert normalized["quiz"]["questions"][0]["type"] == "multiple"
    assert normalized["quiz"]["questions"][0]["difficulty"] == "medium"


def test_research_sources_are_normalized_and_invalid_urls_removed():
    context = _normalize_result(
        {"status": "success", "summary": "ok", "sources": [
            {"url": "https://example.com/path)", "title": "Example", "content": "body"},
            {"url": "not-a-url", "title": "bad"},
        ]},
        ["tavily_search"],
    )
    assert len(context.sources) == 1
    assert context.sources[0].url == "https://example.com/path"
    assert _clean_url(" https://example.com/page。 ") == "https://example.com/page"


def test_research_failure_uses_legacy_prompt(monkeypatch):
    request = QuizGenerateRequest(user_input="Harness Engineering", role="backend")

    class FailedProvider:
        async def research(self, topic, role, difficulty):
            return ResearchContext(status="failed", fallback_reason="timeout")

    calls = []

    def fake_model(temperature):
        calls.append(temperature)
        if temperature == 0:
            return RunnableLambda(lambda _: AIMessage(content='{"supported":true,"message":null}'))
        return RunnableLambda(lambda _: AIMessage(content=json.dumps(make_quiz(request).model_dump())))

    monkeypatch.setattr("app.llm.deepseek._chat_model", fake_model)
    output = asyncio.run(DeepSeekQuizGenerator(FailedProvider()).generate(request))
    assert output.quiz is not None
    assert output.quiz.research_used is False
    assert calls == [0, 0.4]


def test_successful_research_is_injected_and_exposed(monkeypatch):
    request = QuizGenerateRequest(user_input="Harness Engineering 最新实践与系统设计", role="backend", difficulty="hard")
    context = ResearchContext(
        status="success",
        summary="Harness is a software engineering practice.",
        tools=["tavily_search"],
        sources=[ResearchSource(source_id="s1", url="https://example.com", excerpt="Harness is a software engineering practice.", retrieved_at="now")],
    )

    class Provider:
        async def research(self, topic, role, difficulty):
            return context

    captured = []

    def fake_model(temperature):
        if temperature == 0:
            return RunnableLambda(lambda _: AIMessage(content='{"supported":true,"message":null}'))

        def invoke(values):
            captured.append(values)
            return AIMessage(content=json.dumps(make_quiz(request).model_dump()))

        return RunnableLambda(invoke)

    monkeypatch.setattr("app.llm.deepseek._chat_model", fake_model)
    output = asyncio.run(DeepSeekQuizGenerator(Provider()).generate(request, user_id=42))
    assert output.quiz is not None
    assert output.quiz.research_used is True
    assert output.quiz.research_tools == ["tavily_search"]
    assert "Harness is a software engineering practice" in str(captured[0])


def test_user_evidence_route_retries_without_repeating_network_research(monkeypatch):
    request = QuizGenerateRequest(user_input="Harness Engineering 最新实践与系统设计", role="backend", difficulty="hard")

    class EmptyStore:
        def search(self, query, k):
            return []

    class Provider:
        def __init__(self):
            self.calls = 0

        async def research(self, topic, role, difficulty):
            self.calls += 1
            return ResearchContext(
                status="success",
                tools=["tavily_search"],
                sources=[ResearchSource(source_id="s1", url="https://example.com", excerpt="facts", retrieved_at="now")],
            )

    provider = Provider()
    attempts = {"count": 0}

    def fake_model(temperature):
        if temperature == 0:
            return RunnableLambda(lambda _: AIMessage(content='{"supported":true,"message":null}'))

        def invoke(_):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return AIMessage(content='{"supported":true,"message":null}')
            return AIMessage(content=json.dumps(make_quiz(request).model_dump()))

        return RunnableLambda(invoke)

    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", lambda user_id: EmptyStore())
    monkeypatch.setattr("app.llm.deepseek._chat_model", fake_model)
    output = asyncio.run(DeepSeekQuizGenerator(provider).generate(request, user_id=42))
    assert output.quiz is not None
    assert attempts["count"] == 2
    assert provider.calls == 1


def test_query_plan_is_bounded_deduplicated_and_rejects_topic_drift():
    plan = validate_query_plan(
        {"canonical_topic": "React Hooks", "queries": ["React Hooks useState", "React Hooks interview", "React Hooks useState"]},
        "React Hooks",
    )
    assert isinstance(plan, QueryExpansionPlan)
    assert len(plan.queries) == 2
    try:
        validate_query_plan({"queries": ["cooking recipes", "travel"]}, "Harness Engineering")
    except ValueError:
        pass
    else:
        raise AssertionError("planner drift must be rejected")


def test_search_sources_are_deduplicated_and_url_content_is_chunked():
    first = ResearchSource(source_id="a", title="React guide", url="https://example.com?a=1", excerpt="short", retrieved_at="now")
    richer = ResearchSource(source_id="b", title="React guide", url="https://example.com?a=2", excerpt="a much longer relevant body", retrieved_at="now")
    assert _deduplicate_sources([first, richer]) == [richer]
    chunks = split_content_chunks("# Intro\n\n" + "A" * 40 + "\n\n# Details\n\n" + "B" * 40, 50)
    assert len(chunks) >= 2
    assert all(chunk for chunk in chunks)


def test_controlled_research_filters_before_returning_evidence(monkeypatch):
    agent = TavilyResearchAgent()
    async def planner(*args):
        return QueryExpansionPlan(canonical_topic="Harness Engineering", queries=["Harness Engineering", "Harness Engineering interview"]), None
    async def search(query, role, difficulty):
        return [ResearchSource(source_id=query, title=query, url=f"https://example.com/{len(query)}", excerpt="relevant evidence", retrieved_at="now")], None
    async def filtering(topic, role, plan, candidates):
        return [candidates[0].model_copy(update={"relevance_score": 0.9})], None
    monkeypatch.setattr(agent, "_plan_queries", planner)
    monkeypatch.setattr(agent, "_search_query", search)
    monkeypatch.setattr(agent, "_filter_candidates", filtering)
    settings = get_settings()
    monkeypatch.setattr(settings, "tavily_api_key", "test")
    monkeypatch.setattr(settings, "tavily_enabled", True)
    result = asyncio.run(agent.research("Harness Engineering", "backend", "medium"))
    assert result.status == "success"
    assert result.candidate_count == 2
    assert result.filtered_count == 1


def test_filter_failure_never_returns_unfiltered_sources(monkeypatch):
    agent = TavilyResearchAgent()
    async def planner(*args):
        return QueryExpansionPlan(canonical_topic="RAG", queries=["RAG"]), None
    async def search(*args):
        return [ResearchSource(source_id="s", title="RAG", url="https://example.com", excerpt="candidate", retrieved_at="now")], None
    async def filtering(*args):
        return [], "evidence_filter_failed"
    monkeypatch.setattr(agent, "_plan_queries", planner)
    monkeypatch.setattr(agent, "_search_query", search)
    monkeypatch.setattr(agent, "_filter_candidates", filtering)
    settings = get_settings()
    monkeypatch.setattr(settings, "tavily_api_key", "test")
    monkeypatch.setattr(settings, "tavily_enabled", True)
    result = asyncio.run(agent.research("RAG", "ai", "medium"))
    assert result.status == "failed"
    assert result.sources == []
    assert result.fallback_reason == "evidence_filter_failed"


def test_url_research_skips_query_expansion(monkeypatch):
    agent = TavilyResearchAgent()
    called = {"planner": False}
    async def planner(*args):
        called["planner"] = True
        raise AssertionError("URL research must not call query planner")
    async def extract(*args):
        return [ResearchSource(source_id="url-1", title="Docs", url="https://example.com/docs", excerpt="relevant", retrieved_at="now")], None
    async def filtering(*args):
        return [args[-1][0].model_copy(update={"relevance_score": 0.9})], None
    monkeypatch.setattr(agent, "_plan_queries", planner)
    monkeypatch.setattr(agent, "_extract_url", extract)
    monkeypatch.setattr(agent, "_filter_candidates", filtering)
    settings = get_settings()
    monkeypatch.setattr(settings, "tavily_api_key", "test")
    monkeypatch.setattr(settings, "tavily_enabled", True)
    result = asyncio.run(agent.research("https://example.com/docs", "backend", "medium"))
    assert result.status == "success"
    assert called["planner"] is False
