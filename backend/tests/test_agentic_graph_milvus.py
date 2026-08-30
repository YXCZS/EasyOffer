import asyncio
from types import SimpleNamespace

from app.research.agentic_graph import _compound_queries, _grade, run_agentic_rag


class Doc:
    page_content = "Redis persistence uses RDB snapshots and AOF append-only logs."
    metadata = {"document_id": "public-redis", "source_name": "Redis docs", "status": "published", "role_tags": "|backend|"}


class PublicStore:
    def search(self, query, k, **kwargs):
        assert kwargs["published_only"] is True
        return [(Doc(), 0.95)]


def test_graph_routes_to_public_milvus_and_records_tool(monkeypatch):
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_enabled", True)
    monkeypatch.setattr(settings, "agentic_rag_max_rounds", 2)
    monkeypatch.setattr(settings, "agentic_rag_max_tool_calls", 2)
    monkeypatch.setattr("app.services.knowledge_service.get_public_vector_store", lambda: PublicStore())
    state = asyncio.run(run_agentic_rag("Redis persistence", "backend", "medium", user_id=7))
    assert "public_milvus_search" in state["tool_calls"]
    assert state["evidence"]
    assert state["route"] == "public_kb"


def test_graph_uses_autonomous_tool_choice(monkeypatch):
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_enabled", True)
    monkeypatch.setattr(settings, "agentic_rag_max_rounds", 1)
    monkeypatch.setattr(settings, "agentic_rag_max_tool_calls", 1)
    monkeypatch.setattr(
        "app.research.agentic_router.AgenticRAGRouter.choose_next_tool",
        lambda self, policy, state: asyncio.sleep(0, result=(
            __import__("app.research.agentic_router", fromlist=["NextToolDecision"]).NextToolDecision(
                next_tool="tavily_search",
                reason="model selected web search",
                query="Harness Engineering software engineering",
            ),
            None,
        )),
    )

    class TavilyAgent:
        async def _search_query(self, query, role, difficulty):
            from app.research.tavily_agent import ResearchSource
            from datetime import datetime, timezone

            return [
                ResearchSource(
                    source_id="web-1",
                    title="Harness Engineering",
                    url="https://example.com/harness",
                    excerpt="Harness Engineering is a software engineering workflow concept.",
                    retrieved_at=datetime.now(timezone.utc).isoformat(),
                    relevance_score=0.9,
                )
            ], None

    monkeypatch.setattr("app.research.tavily_agent.TavilyResearchAgent", TavilyAgent)
    monkeypatch.setattr("app.services.knowledge_service.get_public_vector_store", lambda: (_ for _ in ()).throw(AssertionError("model choice should skip public KB")))
    state = asyncio.run(run_agentic_rag("Harness Engineering", "ai", "hard", user_id=7))
    assert state["tool_calls"] == ["tavily_search"]
    assert state["route"] == "web_search"


def test_graph_keeps_exact_topic_as_first_public_query_when_expansion_broadens(monkeypatch):
    queries = []

    class CapturingStore(PublicStore):
        def search(self, query, k, **kwargs):
            queries.append(query)
            return super().search(query, k, **kwargs)

    async def broad_plan(*_args, **_kwargs):
        return SimpleNamespace(queries=["Redis data structures", "Redis caching patterns"]), None

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_enabled", True)
    monkeypatch.setattr(settings, "agentic_rag_max_rounds", 1)
    monkeypatch.setattr("app.services.knowledge_service.get_public_vector_store", lambda: CapturingStore())
    monkeypatch.setattr("app.research.tavily_agent.TavilyResearchAgent._plan_queries", broad_plan)

    state = asyncio.run(run_agentic_rag("Redis persistence", "backend", "medium", user_id=7))

    assert queries == ["Redis persistence"]
    assert state["expanded_queries"][0] == "Redis persistence"


def test_graph_uses_shortest_expansion_that_preserves_all_topic_terms(monkeypatch):
    queries = []

    class CapturingStore(PublicStore):
        def search(self, query, k, **kwargs):
            queries.append(query)
            return super().search(query, k, **kwargs)

    async def anchored_plan(*_args, **_kwargs):
        return SimpleNamespace(
            queries=[
                "Redis data structures",
                "Redis persistence RDB AOF principles",
                "Redis persistence RDB AOF principles production tradeoffs",
            ]
        ), None

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_enabled", True)
    monkeypatch.setattr(settings, "agentic_rag_max_rounds", 1)
    monkeypatch.setattr(settings, "tavily_max_query_variants", 4)
    monkeypatch.setattr("app.services.knowledge_service.get_public_vector_store", lambda: CapturingStore())
    monkeypatch.setattr("app.research.tavily_agent.TavilyResearchAgent._plan_queries", anchored_plan)

    asyncio.run(run_agentic_rag("Redis persistence", "backend", "medium", user_id=7))

    assert queries == ["Redis persistence RDB AOF principles"]


def test_evidence_coverage_is_topic_term_coverage_and_never_exceeds_one():
    graded = _grade(
        {
            "topic": "Redis persistence",
            "evidence": [
                {"text": "Redis sorted sets", "score": 0.9},
                {"text": "Redis lists", "score": 0.8},
                {"text": "Redis hashes", "score": 0.7},
            ],
        }
    )

    assert graded["coverage"] == 0.5
    assert 0.0 <= graded["confidence"] <= 1.0


def test_evidence_filter_drops_broad_same_technology_results():
    exact = {"text": "Redis persistence uses RDB snapshots and AOF logs", "score": 0.86}
    graded = _grade(
        {
            "topic": "Redis persistence",
            "evidence": [
                {"text": "Redis sorted sets implement leaderboards", "score": 0.92},
                exact,
                {"text": "Redis lists implement queues", "score": 0.9},
            ],
        }
    )

    assert graded["evidence"] == [exact]
    assert graded["coverage"] == 1.0


def test_grade_prefers_hashmap_over_concurrent_hashmap_for_exact_entity():
    graded = _grade(
        {
            "topic": "HashMap 在 Java 8 中的底层结构是什么",
            "evidence": [
                {"text": "ConcurrentHashMap 在 JDK8 中使用 Node 数组和红黑树", "score": 0.94, "title": "ConcurrentHashMap"},
                {"text": "HashMap 在 Java 8 中由数组、链表和红黑树组成", "score": 0.82, "title": "HashMap"},
            ],
        }
    )
    assert graded["evidence"][0]["title"] == "HashMap"


def test_grade_keeps_spring_boot_auto_configuration_evidence():
    graded = _grade(
        {
            "topic": "Spring Boot 自动配置原理是什么",
            "evidence": [
                {"text": "Spring Interceptor 是请求拦截器", "score": 0.95, "title": "Spring"},
                {"text": "Spring Boot 通过 AutoConfiguration.imports 和条件注解完成自动配置", "score": 0.78, "title": "Spring Boot"},
            ],
        }
    )
    assert graded["evidence"][0]["title"] == "Spring Boot"


def test_grade_preserves_complementary_evidence_for_compound_question():
    graded = _grade(
        {
            "topic": "消息队列如何处理重复消费和消息丢失",
            "evidence": [
                {"text": "通过幂等键和去重表处理重复消费", "score": 0.86},
                {"text": "通过持久化、确认机制和重试处理消息丢失", "score": 0.80},
            ],
        }
    )
    assert len(graded["evidence"]) == 2
    assert graded["coverage"] > 0.5


def test_compound_queries_add_bounded_sub_intents():
    queries = _compound_queries("消息队列如何处理重复消费和消息丢失", "消息队列如何处理重复消费和消息丢失")
    assert len(queries) == 3
    assert any("重复消费" in query for query in queries[1:])
    assert any("消息丢失" in query for query in queries[1:])


def test_graph_personal_mode_never_calls_public_or_web(monkeypatch):
    class PrivateStore:
        def search(self, query, k, document_id=None, **kwargs):
            return [(Doc(), 0.9)]

    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", lambda _user_id: PrivateStore())
    monkeypatch.setattr("app.services.knowledge_service.get_public_vector_store", lambda: (_ for _ in ()).throw(AssertionError("public forbidden")))
    state = asyncio.run(run_agentic_rag("Redis", "backend", "medium", user_id=7, knowledge_only=True))
    assert state["tool_calls"] == ["personal_milvus_search"]
    assert all(item["source_type"] == "personal_kb" for item in state["evidence"])
