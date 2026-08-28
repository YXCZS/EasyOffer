from __future__ import annotations

import math
import re
import statistics
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.corpus.config import DEFAULT_GATES


class BenchmarkQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str
    topic: str
    query: str
    role: str
    difficulty: str
    expected_technologies: list[str]
    relevance: dict[str, int]
    expected_knowledge_points: list[str]


class BenchmarkSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_version: str
    embedding_model: str
    top_k: int = Field(default=5, ge=1, le=20)
    queries: list[BenchmarkQuery] = Field(min_length=1)


class QueryEvaluation(BaseModel):
    query: BenchmarkQuery
    hits: list[dict[str, Any]]
    latency_ms: float
    answer_integrity: bool = True


class EvaluationReport(BaseModel):
    corpus_version: str
    benchmark_version: str
    top_k: int
    metrics: dict[str, float]
    queries: list[QueryEvaluation]


class GateResult(BaseModel):
    passed: bool
    failed_metrics: dict[str, dict[str, float | str]]
    override_reason: str | None = None


def load_benchmark(path: str | Path) -> BenchmarkSet:
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return BenchmarkSet.model_validate(raw)


def _identity(hit: dict[str, Any]) -> str:
    return str(hit.get("parent_id") or hit.get("document_id") or hit.get("source_id") or "")


def _gain(query: BenchmarkQuery, hit: dict[str, Any]) -> int:
    identities = (
        str(hit.get("parent_id") or ""),
        str(hit.get("document_id") or ""),
        str(hit.get("source_id") or ""),
    )
    return max((int(query.relevance.get(identity, 0)) for identity in identities if identity), default=0)


def _gain_identity(query: BenchmarkQuery, hit: dict[str, Any]) -> str:
    for identity in (
        str(hit.get("parent_id") or ""),
        str(hit.get("document_id") or ""),
        str(hit.get("source_id") or ""),
    ):
        if identity and int(query.relevance.get(identity, 0)) > 0:
            return identity
    return ""


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return float(ordered[rank])


def calculate_metrics(results: list[QueryEvaluation], top_k: int = 5) -> dict[str, float]:
    if not results:
        return {key: 0.0 for key in ("hit_at_5", "mrr_at_5", "ndcg_at_5")}
    hits_at_k: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    covered = 0
    duplicates = 0
    total_hits = 0
    contaminated = 0
    traceable = 0
    recoverable = 0
    latency = []
    integrity = []
    for result in results:
        ranked = result.hits[:top_k]
        seen_relevant_identities: set[str] = set()
        gains = []
        for hit in ranked:
            identity = _gain_identity(result.query, hit)
            gain = _gain(result.query, hit)
            if identity in seen_relevant_identities:
                gain = 0
            elif identity:
                seen_relevant_identities.add(identity)
            gains.append(gain)
        relevant_ranks = [index + 1 for index, gain in enumerate(gains) if gain > 0]
        hits_at_k.append(1.0 if relevant_ranks else 0.0)
        reciprocal_ranks.append(1.0 / relevant_ranks[0] if relevant_ranks else 0.0)
        dcg = sum(((2**gain) - 1) / math.log2(index + 2) for index, gain in enumerate(gains))
        ideal = sorted(result.query.relevance.values(), reverse=True)[:top_k]
        idcg = sum(((2**gain) - 1) / math.log2(index + 2) for index, gain in enumerate(ideal))
        ndcgs.append(dcg / idcg if idcg else 0.0)
        covered += 1 if relevant_ranks else 0
        seen_hashes: set[str] = set()
        for hit in ranked:
            total_hits += 1
            content_hash = str(hit.get("content_hash") or "")
            if content_hash and content_hash in seen_hashes:
                duplicates += 1
            if content_hash:
                seen_hashes.add(content_hash)
            roles = hit.get("role_tags") or []
            if isinstance(roles, str):
                roles = [item for item in roles.strip("|").split("|") if item]
            if result.query.role not in roles and "general" not in roles:
                contaminated += 1
            if hit.get("source_name") or hit.get("source_url") or hit.get("citation"):
                traceable += 1
            if hit.get("parent_recovered") is True:
                recoverable += 1
        latency.append(result.latency_ms)
        integrity.append(1.0 if result.answer_integrity else 0.0)
    return {
        "hit_at_5": statistics.fmean(hits_at_k),
        "mrr_at_5": statistics.fmean(reciprocal_ranks),
        "ndcg_at_5": statistics.fmean(ndcgs),
        "knowledge_coverage_rate": covered / len(results),
        "duplicate_result_rate": duplicates / max(1, total_hits),
        "role_contamination_rate": contaminated / max(1, total_hits),
        "source_traceability_rate": traceable / max(1, total_hits),
        "parent_recovery_rate": recoverable / max(1, total_hits),
        "answer_integrity_rate": statistics.fmean(integrity),
        "p50_latency_ms": _percentile(latency, 0.50),
        "p95_latency_ms": _percentile(latency, 0.95),
    }


def _normalize_hit(row: Any, store: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        hit = dict(row)
    else:
        doc, score = row if isinstance(row, tuple) else (row, None)
        hit = {**dict(getattr(doc, "metadata", {}) or {}), "text": str(getattr(doc, "page_content", "")), "score": score}
    parent_id = str(hit.get("parent_id") or "")
    hit["parent_recovered"] = False
    if parent_id:
        def escaped(value: Any) -> str:
            return str(value or "").replace("\\", "\\\\").replace("'", "\\'")

        filters = [f"parent_id == '{escaped(parent_id)}'"]
        for field in ("document_id", "document_version", "corpus_version"):
            if hit.get(field):
                filters.append(f"{field} == '{escaped(hit[field])}'")
        parents = store.query(" and ".join(filters), limit=100)
        hit["parent_recovered"] = bool(parents)
        if parents:
            parents.sort(key=lambda item: int(item.get("child_index", item.get("chunk_index", 0))))
            hit["parent_text"] = "\n".join(
                str(item.get("text") or item.get("evidence_text") or "") for item in parents
            )
    return hit


def _answer_integrity(hit: dict[str, Any]) -> bool:
    text = str(hit.get("parent_text") or hit.get("evidence_text") or hit.get("text") or "").strip()
    if len(text) < 20:
        return False
    if hit.get("parent_id") and hit.get("parent_recovered") is not True:
        return False
    if not (hit.get("source_name") or hit.get("source_url") or hit.get("citation")):
        return False
    looks_like_question = text.endswith(("?", "？")) or bool(
        re.search(r"(?:问题|什么|如何|为什么|区别|原理).{0,80}[?？]", text)
    )
    if not looks_like_question:
        return True
    if str(hit.get("parent_type") or hit.get("knowledge_type") or "") == "qa":
        question_end = max(text.find("?"), text.find("？"))
        if question_end >= 0 and len(text[question_end + 1 :].strip()) >= 20:
            return True
    return bool(re.search(r"(?:答案|解答|解析|答[:：]|Answer)\s*[:：]?\s*\S+", text, re.IGNORECASE))


def evaluate_store(store: Any, benchmark: BenchmarkSet, corpus_version: str, status: str = "unpublished") -> EvaluationReport:
    results: list[QueryEvaluation] = []
    for query in benchmark.queries:
        started = time.perf_counter()
        rows = store.search(query.query, benchmark.top_k, role=query.role, corpus_version=corpus_version, status=status)
        latency_ms = (time.perf_counter() - started) * 1000
        hits = [_normalize_hit(row, store) for row in rows]
        answer_integrity = all(_answer_integrity(hit) for hit in hits) if hits else False
        results.append(QueryEvaluation(query=query, hits=hits, latency_ms=latency_ms, answer_integrity=answer_integrity))
    return EvaluationReport(
        corpus_version=corpus_version,
        benchmark_version=benchmark.benchmark_version,
        top_k=benchmark.top_k,
        metrics=calculate_metrics(results, benchmark.top_k),
        queries=results,
    )


def enforce_gate(
    report: EvaluationReport,
    gates: dict[str, dict[str, float | str]] | None = None,
    override_reason: str | None = None,
) -> GateResult:
    failed: dict[str, dict[str, float | str]] = {}
    for name, rule in (gates or DEFAULT_GATES).items():
        actual = float(report.metrics.get(name, 0.0))
        expected = float(rule["value"])
        operator = str(rule["operator"])
        if (operator == "min" and actual < expected) or (operator == "max" and actual > expected):
            failed[name] = {"actual": actual, "expected": expected, "operator": operator}
    return GateResult(passed=not failed or bool(override_reason), failed_metrics=failed, override_reason=override_reason)


def compare_reports(current: EvaluationReport, candidate: EvaluationReport) -> dict[str, Any]:
    if current.benchmark_version != candidate.benchmark_version or current.top_k != candidate.top_k:
        raise ValueError("reports require identical benchmark version and top-k")
    names = set(current.metrics) | set(candidate.metrics)
    deltas = {name: float(candidate.metrics.get(name, 0)) - float(current.metrics.get(name, 0)) for name in names}
    lower_is_better = {"duplicate_result_rate", "role_contamination_rate", "p50_latency_ms", "p95_latency_ms"}
    regressions = [
        name for name, delta in deltas.items()
        if (name in lower_is_better and delta > 0) or (name not in lower_is_better and delta < 0)
    ]
    current_queries = {item.query.query_id: item for item in current.queries}
    drift = []
    for item in candidate.queries:
        previous = current_queries.get(item.query.query_id)
        if previous and [_identity(hit) for hit in previous.hits] != [_identity(hit) for hit in item.hits]:
            drift.append(item.query.query_id)
    return {"metric_deltas": deltas, "regressions": sorted(regressions), "result_drift": drift}
