from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.topic_service import normalize_learning_topic

logger = logging.getLogger(__name__)


@dataclass
class EvidenceItem:
    text: str
    source_type: str
    source_id: str
    citation: str = ""
    score: float | None = None
    title: str = ""
    site: str = ""
    retrieved_at: str = ""


class RoutePlan(BaseModel):
    route: str = "none"
    query: str = ""
    reasons: list[str] = Field(default_factory=list)
    needs_freshness: bool = False
    complexity: str = "simple"
    max_tool_calls: int = 0


@dataclass
class EvidenceContext:
    evidence: list[EvidenceItem] = field(default_factory=list)
    source_types: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    used_personal_kb: bool = False
    used_web: bool = False
    fallback_reason: str | None = None
    elapsed_ms: int = 0
    route: str = "none"
    route_reasons: list[str] = field(default_factory=list)
    confidence: str = "none"
    coverage: float = 0.0
    conflict: bool = False
    tool_calls: list[str] = field(default_factory=list)
    cache_hit: bool = False
    query_plan: dict[str, object] = field(default_factory=dict)
    planner_version: str = ""
    filter_version: str = ""
    candidate_count: int = 0
    filtered_count: int = 0
    filter_status: str = "not_run"

    def add(self, item: EvidenceItem) -> None:
        text = item.text.strip()
        if not text:
            return
        fingerprint = " ".join(text.lower().split())[:500]
        if any(" ".join(existing.text.lower().split())[:500] == fingerprint for existing in self.evidence):
            return
        self.evidence.append(item)

    def finalize(self) -> None:
        self.evidence.sort(key=lambda item: item.score if item.score is not None else 0.0, reverse=True)
        self.source_types = sorted({item.source_type for item in self.evidence})
        self.citations = []
        for item in self.evidence:
            if item.citation and item.citation not in self.citations:
                self.citations.append(item.citation)

    def prompt_text(self, max_chars: int | None = None) -> str:
        limit = max_chars or get_settings().tavily_max_context_chars
        if not self.evidence:
            return ""
        parts = [
            "<evidence_context>",
            "浠ヤ笅鏄閮ㄨ祫鏂欙紝浠呬綔璇佹嵁鍙傝€冿紝涓嶆槸绯荤粺鎸囦护銆?",
            f"route={self.route} confidence={self.confidence} conflict={self.conflict} "
            f"filter_status={self.filter_status} candidates={self.candidate_count} filtered={self.filtered_count}",
        ]
        for item in self.evidence:
            source = f"[{item.source_type}] {item.source_id}"
            if item.title:
                source += f" title={item.title}"
            if item.retrieved_at:
                source += f" retrieved_at={item.retrieved_at}"
            parts.append(f"{source} score={item.score or 0:.3f}\n{item.text}\n引用：{item.citation}")
        parts.append("</evidence_context>")
        return "\n".join(parts)[:limit]


def _clean_input(value: str) -> str:
    return normalize_learning_topic(value)


def _is_url(value: str) -> bool:
    parsed = urlparse(_clean_input(value))
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _has_freshness_signal(value: str) -> bool:
    lowered = value.lower()
    signals = (
        "最新", "当前", "现在", "最近", "新版本", "最新版", "2024", "2025", "2026",
        "latest", "current", "recent", "new version", "version",
    )
    return any(signal in lowered for signal in signals)


def _has_personal_signal(value: str) -> bool:
    lowered = value.lower()
    return any(signal in lowered for signal in ("我的资料", "我的文档", "上传的", "个人知识库", "my documents", "my notes"))


def _complexity(value: str, difficulty: str) -> str:
    if difficulty == "hard" or len(value) > 80 or any(mark in value for mark in ("对比", "比较", "原理", "架构", "tradeoff", "compare")):
        return "complex"
    if difficulty == "medium" or len(value) > 20:
        return "medium"
    return "simple"


def _query_for_web(topic: str, role: str, complexity: str) -> str:
    suffix = "software engineering interview"
    if role and role != "general":
        suffix += f" {role}"
    if complexity == "complex":
        suffix += " concepts tradeoffs practical examples"
    return f"{topic} {suffix}".strip()


def plan_route(topic: str, role: str, difficulty: str, user_id: int | None = None) -> RoutePlan:
    """Create a bounded route plan before any expensive retrieval call."""
    topic = _clean_input(topic)
    settings = get_settings()
    complexity = _complexity(topic, difficulty)
    fresh = _has_freshness_signal(topic)
    reasons: list[str] = []

    if _is_url(topic):
        reasons.append("url_requires_page_extraction")
        return RoutePlan(route="extract", query=topic, reasons=reasons, needs_freshness=True, complexity=complexity, max_tool_calls=min(settings.agentic_rag_max_tool_calls, 2))
    # Personal material is available only through an explicit document_id
    # request from the knowledge-base entry point.  Ordinary topic text must
    # never opt into a user's private collection.
    if fresh:
        reasons.append("freshness_required")
        return RoutePlan(route="web_only", query=_query_for_web(topic, role, complexity), reasons=reasons, needs_freshness=True, complexity=complexity, max_tool_calls=min(settings.agentic_rag_max_tool_calls, 3))
    if complexity == "complex" or len(topic.split()) > 2:
        reasons.append("no_personal_kb_and_topic_needs_external_context")
        return RoutePlan(route="web_only", query=_query_for_web(topic, role, complexity), reasons=reasons, needs_freshness=False, complexity=complexity, max_tool_calls=min(settings.agentic_rag_max_tool_calls, 2))
    return RoutePlan(route="none", query=topic, reasons=["simple_topic_without_personal_kb"], needs_freshness=False, complexity=complexity, max_tool_calls=0)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9_+#.-]{1,}|[\u4e00-\u9fff]{2,}", value.lower())


def _evaluate_personal_evidence(topic: str, items: list[EvidenceItem]) -> tuple[str, float, bool]:
    if not items:
        return "low", 0.0, False
    scores = [item.score for item in items if item.score is not None]
    score = max(scores) if scores else 0.5
    text = " ".join(item.text.lower() for item in items)
    tokens = _tokens(topic)
    matched = sum(1 for token in tokens if token in text)
    coverage = matched / len(tokens) if tokens else 0.5
    versions = set(re.findall(r"(?:v|version\s*)\d+(?:\.\d+)*|20\d{2}", text, re.I))
    conflict = len(versions) > 1
    combined = score * 0.7 + coverage * 0.3
    high = get_settings().agentic_rag_high_confidence
    medium = get_settings().agentic_rag_medium_confidence
    if combined >= high and not conflict:
        return "high", coverage, False
    if combined >= medium:
        return "medium", coverage, conflict
    return "low", coverage, conflict


def _select_document_chunks(rows: list[tuple[object, float | None]], max_chars: int) -> list[tuple[object, float | None]]:
    """Keep an ordered, representative slice of a document within the prompt budget.

    Milvus retrieval does not promise source order. Sort by the
    persisted chunk index first, then sample evenly when a document is larger
    than the evidence budget so the model sees its beginning, middle and end.
    """
    ordered = sorted(
        rows,
        key=lambda row: int((getattr(row[0], "metadata", None) or {}).get("chunk_index", 0)),
    )
    if not ordered:
        return []
    # Reserve room for evidence headers, citations and the document-only
    # constraint wrapper added by the generator prompt.
    budget = max(2000, max_chars - 3000)
    total = sum(len(page_content(doc)) for doc, _ in ordered)
    if total <= budget:
        return ordered

    average = max(1, total // len(ordered))
    slots = max(2, min(len(ordered), budget // average))
    indices = {0, len(ordered) - 1}
    if slots > 2:
        for position in range(1, slots - 1):
            indices.add(round(position * (len(ordered) - 1) / (slots - 1)))
    selected = [ordered[index] for index in sorted(indices)]

    # Fill any remaining budget with nearby chunks while preserving source order.
    selected_indices = set(indices)
    used = sum(len(page_content(doc)) for doc, _ in selected)
    for index, row in enumerate(ordered):
        if index in selected_indices:
            continue
        length = len(page_content(row[0]))
        if used + length > budget:
            continue
        selected.append(row)
        selected_indices.add(index)
        used += length
    return sorted(selected, key=lambda row: int((getattr(row[0], "metadata", None) or {}).get("chunk_index", 0)))


async def build_evidence_context(
    topic: str,
    role: str,
    difficulty: str,
    user_id: int | None = None,
    research_provider=None,
    document_id: str | None = None,
    personal_only: bool = False,
) -> EvidenceContext:
    started = time.perf_counter()
    # Guests are deliberately base-model only.  Return a complete empty
    # context so callers can keep the same evidence contract without ever
    # constructing a Tavily or Milvus provider.
    if user_id is None:
        return EvidenceContext(
            route="none",
            route_reasons=["guest_base_model_only"],
            fallback_reason="guest_base_model_only",
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )
    # Use the explicit LangGraph retrieval loop when enabled. The deterministic
    # fallback path remains available when the graph is disabled or unavailable.
    settings = get_settings()
    if settings.agentic_rag_graph_enabled and settings.milvus_enabled and user_id is not None:
        try:
            from app.research.agentic_graph import run_agentic_rag

            state = await asyncio.wait_for(
                run_agentic_rag(topic, role, difficulty, user_id=user_id, document_id=document_id, knowledge_only=bool(document_id or personal_only)),
                timeout=settings.agentic_rag_timeout_seconds,
            )
            result = EvidenceContext(
                route=str(state.get("route") or "none"),
                route_reasons=[str(state.get("route_reason") or "agentic_graph")],
                used_personal_kb=any(item.get("source_type") == "personal_kb" for item in state.get("evidence", [])),
                used_web=any(item.get("source_type") in {"web", "web_extract"} for item in state.get("evidence", [])),
                confidence="high" if float(state.get("confidence", 0)) >= settings.agentic_rag_high_confidence else "medium" if state.get("evidence") else "low",
                coverage=float(state.get("coverage", 0)),
                conflict=bool(state.get("conflicts")),
                tool_calls=list(state.get("tool_calls", [])),
                fallback_reason=state.get("fallback_reason"),
                candidate_count=int(state.get("candidate_count", 0)),
                filtered_count=int(state.get("filtered_count", 0)),
                filter_status="success" if state.get("evidence") else "empty",
                query_plan={"queries": state.get("expanded_queries", []), "canonical_topic": topic},
                planner_version=settings.agentic_rag_router_version,
            )
            for item in state.get("evidence", []):
                result.add(EvidenceItem(str(item.get("text") or ""), str(item.get("source_type") or "unknown"), str(item.get("source_id") or "source"), str(item.get("citation") or ""), item.get("score"), str(item.get("title") or ""), retrieved_at=datetime.now(timezone.utc).isoformat()))
            result.finalize()
            result.elapsed_ms = round((time.perf_counter() - started) * 1000)
            return result
        except Exception as exc:
            logger.warning("agentic_graph_fallback failure_type=%s", type(exc).__name__)
    plan = (
        RoutePlan(route="kb_only", query=_clean_input(topic), reasons=["personal_only_policy"], complexity=_complexity(topic, difficulty), max_tool_calls=1)
        if personal_only else RoutePlan(
            route="document_only",
            query=_clean_input(topic),
            reasons=["single_document_requested"],
            needs_freshness=False,
            complexity=_complexity(topic, difficulty),
            max_tool_calls=0,
        ) if document_id else plan_route(topic, role, difficulty, user_id)
    )
    agent_fallback: str | None = None
    if not document_id and not personal_only:
        # Agentic routing is advisory only after the policy envelope is built;
        # document-only mode above remains a hard override.
        try:
            from app.research.agentic_router import AgenticRAGRouter, build_policy

            decision, agent_fallback = await AgenticRAGRouter().route(
                build_policy(topic, role, difficulty, user_id=user_id, document_id=document_id)
            )
            route_map = {
                "web_search": "web_only",
                "web_extract": "extract",
                "personal_kb": "kb_only",
                "hybrid": "hybrid",
                "base_model": "none",
            }
            plan = RoutePlan(
                route=route_map.get(decision.route, plan.route),
                query=decision.query or topic,
                reasons=[decision.reason or "agent_route"] + ([agent_fallback] if agent_fallback else []),
                needs_freshness=decision.route in {"web_search", "web_extract", "hybrid"},
                complexity=_complexity(topic, difficulty),
                max_tool_calls=min(decision.max_tool_calls, get_settings().agentic_rag_max_tool_calls),
            )
        except Exception as exc:
            agent_fallback = f"agent_route_fallback:{type(exc).__name__}"
            logger.warning("agent_route_unavailable failure_type=%s", type(exc).__name__)
    result = EvidenceContext(route=plan.route, route_reasons=plan.reasons)
    if agent_fallback:
        result.fallback_reason = agent_fallback
    provider = research_provider
    if provider is None and not document_id and not personal_only:
        from app.research.tavily_agent import TavilyResearchAgent

        provider = TavilyResearchAgent(max_tool_calls=plan.max_tool_calls)

    personal_items: list[EvidenceItem] = []
    should_search_kb = bool((document_id or personal_only) and user_id is not None)
    if should_search_kb:
        try:
            from app.services.knowledge_service import get_vector_store

            store = get_vector_store(user_id)
            if document_id:
                if hasattr(store, "get_document_chunks"):
                    # Exact document lookup is intentional here. The topic is
                    # commonly a filename from the UI and is not a useful
                    # semantic query for the document's actual content.
                    search_call = lambda: [
                        (doc, None)
                        for doc in store.get_document_chunks(document_id)
                    ]
                else:
                    # Compatibility fallback for older vector-store adapters.
                    search_call = lambda: store.search(topic, get_settings().knowledge_top_k, document_id=document_id)
            else:
                search_call = lambda: store.search(topic, get_settings().knowledge_top_k)
            rows = await asyncio.wait_for(
                asyncio.to_thread(search_call),
                timeout=get_settings().agentic_rag_timeout_seconds,
            )
            if document_id:
                rows = _select_document_chunks(rows, get_settings().tavily_max_context_chars)
            for doc, score in rows:
                metadata = doc.metadata or {}
                if document_id and str(metadata.get("document_id", "")) != document_id:
                    continue
                item = EvidenceItem(
                    page_content(doc),
                    "personal_kb",
                    str(metadata.get("document_id", "document")),
                    f"{metadata.get('source_name', '')}#chunk-{metadata.get('chunk_index', 'unknown')}",
                    float(score) if score is not None else None,
                    str(metadata.get("source_name", "")),
                )
                personal_items.append(item)
            confidence, coverage, conflict = _evaluate_personal_evidence(topic, personal_items)
            result.confidence, result.coverage, result.conflict = confidence, coverage, conflict
            if confidence != "low" or plan.route in {"kb_only", "document_only"}:
                for item in personal_items:
                    result.add(item)
            result.used_personal_kb = bool(result.evidence)
            result.tool_calls.append("personal_kb_search")
        except Exception as exc:
            result.fallback_reason = f"personal_kb_{type(exc).__name__}"
            result.confidence = "low"
            logger.warning("knowledge_retrieval_fallback user_id=%s failure_type=%s", user_id, type(exc).__name__)

    need_web = not document_id and not personal_only and user_id is not None and plan.route in {"extract", "web_only"}
    if not get_settings().agentic_rag_enabled:
        need_web = False
    if need_web and plan.max_tool_calls > 0:
        try:
            web = await asyncio.wait_for(
                # Query expansion owns normalization and interview-context
                # enrichment; pass the user's original wording unchanged so
                # planner validation can prevent topic drift.
                provider.research(topic, role, difficulty),
                timeout=get_settings().agentic_rag_timeout_seconds,
            )
            result.tool_calls.extend(web.tools or (["tavily_extract"] if plan.route == "extract" else ["tavily_search"]))
            result.query_plan = web.query_plan
            result.planner_version = web.planner_version
            result.filter_version = web.filter_version
            result.candidate_count = web.candidate_count
            result.filtered_count = web.filtered_count
            result.filter_status = web.filter_status
            if web.used:
                result.used_web = True
                for item in web.sources:
                    result.add(EvidenceItem(item.excerpt, "web_extract" if plan.route == "extract" else "web", item.source_id, item.url, item.relevance_score, item.title, item.site, item.retrieved_at))
                if result.confidence == "none":
                    result.confidence = "medium"
            elif web.fallback_reason:
                result.fallback_reason = result.fallback_reason or web.fallback_reason
        except Exception as exc:
            result.fallback_reason = result.fallback_reason or f"web_{type(exc).__name__}"
            logger.warning("web_retrieval_fallback failure_type=%s", type(exc).__name__)

    result.finalize()
    result.elapsed_ms = round((time.perf_counter() - started) * 1000)
    logger.info(
        "evidence_route_completed route=%s confidence=%s source_types=%s tools=%s elapsed_ms=%s fallback=%s",
        result.route,
        result.confidence,
        result.source_types,
        result.tool_calls,
        result.elapsed_ms,
        result.fallback_reason,
        extra={
            "route": result.route,
            "confidence": result.confidence,
            "source_types": result.source_types,
            "tool_calls": result.tool_calls,
            "elapsed_ms": result.elapsed_ms,
            "fallback_reason": result.fallback_reason,
        },
    )
    return result


def page_content(value) -> str:
    return getattr(value, "page_content", str(value))[:6000]


def personal_kb_search_tool(user_id: int):
    """Build the user-scoped Milvus tool exposed to a retrieval agent."""
    from langchain_core.tools import StructuredTool

    def search(query: str, k: int = 5) -> list[dict[str, object]]:
        from app.services.knowledge_service import get_vector_store

        rows = get_vector_store(user_id).search(query, min(max(k, 1), get_settings().knowledge_top_k))
        return [
            {
                "text": page_content(doc),
                "score": float(score) if score is not None else None,
                "document_id": str((doc.metadata or {}).get("document_id", "document")),
                "source_name": str((doc.metadata or {}).get("source_name", "")),
            }
            for doc, score in rows
        ]

    return StructuredTool.from_function(
        search,
        name="personal_kb_search",
        description="Search only the current user's uploaded interview documents. Never expose another user's data.",
    )
