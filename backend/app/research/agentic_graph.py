"""Policy-constrained Agentic RAG graph.

The graph is intentionally explicit rather than an opaque ReAct helper. Each
tool call and loop decision is represented in state, so privacy and cost
guards can be tested without network access.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langchain_core.tools import StructuredTool

from app.core.config import get_settings
from app.research.agentic_router import (
    AgenticRAGRouter,
    PolicyEnvelope,
    build_policy,
    deterministic_next_tool,
)


class AgenticRAGState(TypedDict, total=False):
    topic: str
    role: str
    difficulty: str
    user_id: int | None
    document_id: str | None
    policy: PolicyEnvelope
    allowed_tools: list[str]
    query: str
    expanded_queries: list[str]
    next_tool: str | None
    round: int
    tool_call_count: int
    evidence: list[dict[str, Any]]
    candidate_count: int
    filtered_count: int
    confidence: float
    coverage: float
    conflicts: list[str]
    route: str
    route_reason: str
    tool_calls: list[str]
    fallback_reason: str | None
    done: bool
    started_at: float


def _topic_terms(value: str) -> list[str]:
    return list(
        dict.fromkeys(
            re.findall(
                r"[A-Za-z][A-Za-z0-9_+#.-]{1,}|[\u4e00-\u9fff]{2,}",
                value.lower(),
            )
        )
    )


def _select_retrieval_query(topic: str, expanded_queries: list[str]) -> str:
    """Use expansion only when it preserves every explicit topic term."""
    terms = _topic_terms(topic)
    anchored = [
        query.strip()
        for query in expanded_queries
        if query.strip()
        and query.strip() != topic.strip()
        and all(term in query.lower() for term in terms)
    ]
    if not anchored:
        return topic
    # The shortest fully anchored expansion adds the least unrelated context.
    return min(anchored, key=len)


def _doc_payload(doc: Any, score: float | None, source_type: str) -> dict[str, Any]:
    metadata = dict(getattr(doc, "metadata", None) or {})
    return {
        "text": str(metadata.get("evidence_text") or getattr(doc, "page_content", ""))[:6000],
        "score": float(score) if score is not None else None,
        "source_type": source_type,
        "source_id": str(metadata.get("document_id") or metadata.get("source_id") or "source"),
        "citation": str(metadata.get("source_url") or metadata.get("source_name") or ""),
        "title": str(metadata.get("source_name") or metadata.get("title") or ""),
        "version": str(metadata.get("version") or ""),
        "parent_id": str(metadata.get("parent_id") or ""),
        "document_version": str(metadata.get("document_version") or ""),
        "corpus_version": str(metadata.get("corpus_version") or ""),
    }


def _public_payloads(rows: list[Any], store: Any) -> list[dict[str, Any]]:
    """Return evidence payloads expanded through exact public parent keys."""
    payloads: list[dict[str, Any]] = []
    parent_cache: dict[tuple[str, str, str, str], str] = {}
    for doc, score in rows:
        payload = _doc_payload(doc, score, "public_kb")
        metadata = dict(getattr(doc, "metadata", None) or {})
        parent_id = str(metadata.get("parent_id") or "")
        if parent_id:
            key = (
                parent_id,
                str(metadata.get("document_id") or ""),
                str(metadata.get("document_version") or ""),
                str(metadata.get("corpus_version") or ""),
            )
            if key not in parent_cache:
                parent_rows = store.get_parent_chunks(
                    parent_id,
                    document_id=key[1] or None,
                    document_version=key[2] or None,
                    corpus_version=key[3] or None,
                )
                parent_cache[key] = "\n".join(
                    str(item.get("evidence_text") or item.get("text") or "").strip()
                    for item in parent_rows
                    if str(item.get("evidence_text") or item.get("text") or "").strip()
                )[:6000]
            if parent_cache[key]:
                payload["text"] = parent_cache[key]
                payload["parent_recovered"] = True
        payloads.append(payload)
    return payloads


def _tool_defs() -> list[StructuredTool]:
    def public_search(query: str, role: str = "general", k: int = 5) -> list[dict[str, Any]]:
        from app.services.knowledge_service import get_public_vector_store

        store = get_public_vector_store()
        rows = store.search(query, k, role=role, published_only=True)
        return _public_payloads(rows, store)

    def personal_search(query: str, user_id: int, document_id: str | None = None, k: int = 5) -> list[dict[str, Any]]:
        from app.services.knowledge_service import get_vector_store

        rows = get_vector_store(int(user_id)).search(query, k, document_id=document_id)
        return [_doc_payload(doc, score, "personal_kb") for doc, score in rows]

    def tavily_search(query: str, role: str = "general", difficulty: str = "medium") -> list[dict[str, Any]]:
        # Synchronous wrappers are used by ToolNode. Runtime graph nodes call
        # the same implementation in a worker thread when needed.
        from app.research.tavily_agent import TavilyResearchAgent

        result = asyncio.run(TavilyResearchAgent()._search_query(query, role, difficulty))
        sources, _ = result
        return [{"text": source.excerpt, "score": source.relevance_score, "source_type": "web", "source_id": source.source_id, "citation": source.url, "title": source.title, "version": source.version_fit} for source in sources]

    def tavily_extract(url: str) -> list[dict[str, Any]]:
        from app.research.tavily_agent import TavilyResearchAgent

        sources, _ = asyncio.run(TavilyResearchAgent()._extract_url(url))
        return [{"text": source.excerpt, "score": source.relevance_score, "source_type": "web_extract", "source_id": source.source_id, "citation": source.url, "title": source.title, "version": source.version_fit} for source in sources]

    return [
        StructuredTool.from_function(public_search, name="public_milvus_search", description="Search published public interview knowledge in Milvus."),
        StructuredTool.from_function(personal_search, name="personal_milvus_search", description="Search only the current user's private Milvus documents."),
        StructuredTool.from_function(tavily_search, name="tavily_search", description="Search current web sources with Tavily."),
        StructuredTool.from_function(tavily_extract, name="tavily_extract", description="Extract the full content of a user-provided URL with Tavily."),
    ]


async def _route_controller(state: AgenticRAGState) -> dict[str, Any]:
    policy: PolicyEnvelope = state["policy"]
    if not policy.allowed_tools:
        return {"next_tool": None, "done": True, "route": "base_model", "route_reason": "base_model_only"}
    if state.get("round", 0) >= get_settings().agentic_rag_max_rounds:
        return {"next_tool": None, "done": True, "fallback_reason": "max_rounds"}
    # The model chooses the next action for ordinary authenticated users. The
    # chooser is policy-aware, and falls back to a deterministic route when
    # the model is unavailable. Tool execution itself remains in this graph
    # node so timeouts, authorization and audit fields stay centralized.
    decision, fallback = await AgenticRAGRouter().choose_next_tool(policy, state)
    if decision.next_tool == "finish":
        # A model must not terminate an empty retrieval run while an allowed
        # tool is still available. This preserves grounding even if the model
        # returns an over-eager finish decision.
        if not state.get("evidence"):
            fallback_decision = deterministic_next_tool(policy, state)
            if fallback_decision.next_tool != "finish":
                decision = fallback_decision
                fallback = fallback or "agent_finish_without_evidence"
        if decision.next_tool == "finish":
            return {
                "next_tool": None,
                "done": True,
                "route": state.get("route") or "base_model",
                "route_reason": decision.reason or "agent_finished",
                "fallback_reason": fallback,
            }
    route_map = {
        "public_milvus_search": "public_kb",
        "personal_milvus_search": "personal_kb",
        "tavily_search": "web_search",
        "tavily_extract": "web_extract",
    }
    return {
        "next_tool": decision.next_tool,
        "query": (decision.query or state.get("query") or policy.topic)[:500],
        "route": route_map.get(decision.next_tool, state.get("route") or "web_search"),
        "route_reason": decision.reason or "agent_selected_tool",
        "fallback_reason": fallback,
    }


async def _retrieve(state: AgenticRAGState) -> dict[str, Any]:
    tool = state.get("next_tool")
    if not tool:
        return {"done": True}
    policy: PolicyEnvelope = state["policy"]
    policy_name = "personal_kb_search" if tool == "personal_milvus_search" else tool
    if policy_name not in policy.allowed_tools:
        return {"done": True, "fallback_reason": "policy_blocked_tool"}
    query = state.get("query") or state["topic"]
    rows: list[dict[str, Any]] = []
    try:
        if tool == "public_milvus_search":
            from app.services.knowledge_service import get_public_vector_store

            store = get_public_vector_store()
            docs = await asyncio.wait_for(asyncio.to_thread(store.search, query, get_settings().milvus_retrieval_top_k, role=state.get("role"), published_only=True), get_settings().agentic_rag_tool_timeout_seconds)
            rows = await asyncio.wait_for(
                asyncio.to_thread(_public_payloads, docs, store),
                get_settings().agentic_rag_tool_timeout_seconds,
            )
        elif tool == "personal_milvus_search":
            from app.services.knowledge_service import get_vector_store

            docs = await asyncio.wait_for(asyncio.to_thread(get_vector_store(int(policy.user_id)).search, query, get_settings().knowledge_top_k, policy.document_id), get_settings().agentic_rag_tool_timeout_seconds)
            rows = [_doc_payload(doc, score, "personal_kb") for doc, score in docs]
        elif tool == "tavily_search":
            from app.research.tavily_agent import TavilyResearchAgent

            rows0, _ = await TavilyResearchAgent()._search_query(query, state.get("role", "general"), state.get("difficulty", "medium"))
            rows = [{"text": item.excerpt, "score": item.relevance_score, "source_type": "web", "source_id": item.source_id, "citation": item.url, "title": item.title, "version": item.version_fit} for item in rows0]
        elif tool == "tavily_extract":
            from app.research.tavily_agent import TavilyResearchAgent

            rows0, _ = await TavilyResearchAgent()._extract_url(query)
            rows = [{"text": item.excerpt, "score": item.relevance_score, "source_type": "web_extract", "source_id": item.source_id, "citation": item.url, "title": item.title, "version": item.version_fit} for item in rows0]
        else:
            return {"done": True, "fallback_reason": "unknown_tool"}
    except Exception as exc:
        return {"tool_calls": [*state.get("tool_calls", []), tool], "tool_call_count": state.get("tool_call_count", 0) + 1, "round": state.get("round", 0) + 1, "fallback_reason": f"{tool}_{type(exc).__name__}"}
    return {"evidence": [*state.get("evidence", []), *rows], "candidate_count": state.get("candidate_count", 0) + len(rows), "tool_calls": [*state.get("tool_calls", []), tool], "tool_call_count": state.get("tool_call_count", 0) + 1, "round": state.get("round", 0) + 1}


def _grade(state: AgenticRAGState) -> dict[str, Any]:
    evidence = state.get("evidence", [])
    topic_terms = _topic_terms(state.get("topic", ""))
    unique: dict[str, dict[str, Any]] = {}
    for item in evidence:
        text = str(item.get("text") or "")
        key = " ".join(text.lower().split())[:300]
        if key and key not in unique:
            unique[key] = item
    kept = list(unique.values())
    if topic_terms and kept:
        match_counts = [
            sum(1 for term in topic_terms if term in str(item.get("text", "")).lower())
            for item in kept
        ]
        best_match_count = max(match_counts, default=0)
        if best_match_count:
            kept = [
                item
                for item, match_count in zip(kept, match_counts, strict=True)
                if match_count == best_match_count
            ]
    combined_text = " ".join(str(item.get("text", "")).lower() for item in kept)
    matched_terms = sum(1 for term in topic_terms if term in combined_text)
    coverage = min(1.0, matched_terms / len(topic_terms)) if topic_terms else min(1.0, len(kept) / 3)
    score_values = [float(item["score"]) for item in kept if item.get("score") is not None]
    confidence = (max(score_values) if score_values else (0.5 if kept else 0.0)) * 0.7 + coverage * 0.3
    versions = {str(item.get("version")) for item in kept if item.get("version") and str(item.get("version")) != "unknown"}
    return {"evidence": kept, "filtered_count": len(kept), "coverage": coverage, "confidence": confidence, "conflicts": ["version_conflict"] if len(versions) > 1 else []}


def _after_grade(state: AgenticRAGState) -> str:
    if state.get("done"):
        return "finish"
    if state.get("confidence", 0.0) >= get_settings().agentic_rag_medium_confidence and state.get("evidence"):
        return "finish"
    if state.get("round", 0) >= get_settings().agentic_rag_max_rounds or state.get("tool_call_count", 0) >= get_settings().agentic_rag_max_tool_calls:
        return "finish"
    return "rewrite" if state.get("evidence") else "route"


def _rewrite(state: AgenticRAGState) -> dict[str, Any]:
    query = state.get("query") or state.get("topic", "")
    role = state.get("role") or "general"
    variant = f"{query} {role} software engineering interview practical principles"
    return {"query": variant[:500], "expanded_queries": [*state.get("expanded_queries", []), variant]}


def build_agentic_rag_graph():
    builder = StateGraph(AgenticRAGState)
    builder.add_node("route_controller", _route_controller)
    builder.add_node("retrieve", _retrieve)
    builder.add_node("grade_evidence", _grade)
    builder.add_node("rewrite_query", _rewrite)
    # Expose real tools through the official ToolNode API. Runtime retrieval
    # uses the async adapter above so policy and timeout checks remain visible.
    builder.add_node("tools", ToolNode(_tool_defs()))
    builder.add_edge(START, "route_controller")
    builder.add_conditional_edges("route_controller", lambda state: "finish" if state.get("done") else "retrieve", {"retrieve": "retrieve", "finish": END})
    builder.add_edge("retrieve", "grade_evidence")
    builder.add_conditional_edges("grade_evidence", _after_grade, {"route": "route_controller", "rewrite": "rewrite_query", "finish": END})
    builder.add_edge("rewrite_query", "route_controller")
    return builder.compile()


async def run_agentic_rag(topic: str, role: str, difficulty: str, *, user_id: int | None = None, document_id: str | None = None, knowledge_only: bool = False) -> AgenticRAGState:
    policy = build_policy(topic, role, difficulty, user_id=user_id, document_id=document_id, knowledge_only=knowledge_only)
    expanded = [topic]
    if not policy.is_url:
        try:
            from app.research.tavily_agent import TavilyResearchAgent

            plan, _ = await asyncio.wait_for(TavilyResearchAgent()._plan_queries(topic, role, difficulty), get_settings().tavily_planner_timeout_seconds)
            # Query expansion may broaden recall, but it must never replace the
            # exact user intent. The first public-KB lookup always uses the
            # original topic; variants remain available to later retrieval rounds.
            expanded = list(dict.fromkeys([topic, *plan.queries]))[
                : max(1, get_settings().tavily_max_query_variants)
            ]
        except Exception:
            # Expansion is mandatory at the graph boundary, but a planner
            # outage must not block learning. Keep an exact-topic anchor and a
            # bounded interview-context variant as the deterministic fallback.
            expanded = [topic, f"{topic} {role} software engineering interview"][:2]
    initial: AgenticRAGState = {
        "topic": topic, "query": _select_retrieval_query(topic, expanded), "role": role, "difficulty": difficulty,
        "user_id": user_id, "document_id": document_id, "policy": policy,
        "allowed_tools": list(policy.allowed_tools), "round": 0, "tool_call_count": 0,
        "evidence": [], "tool_calls": [], "expanded_queries": expanded, "started_at": time.perf_counter(),
    }
    return await build_agentic_rag_graph().ainvoke(initial)
