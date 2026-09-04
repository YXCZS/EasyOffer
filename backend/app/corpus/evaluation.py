from __future__ import annotations

import math
import hashlib
import json
import os
import re
import statistics
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
    # Optional fields keep historical benchmark files backwards compatible.
    scenario_type: str = "stable_technical"
    reference_answer: str = ""
    reference_context_ids: list[str] = Field(default_factory=list)
    reference_contexts: list[str] = Field(default_factory=list)
    expected_route: str = ""
    expected_tools: list[str] = Field(default_factory=list)
    expected_citations: list[str] = Field(default_factory=list)
    safety_tags: list[str] = Field(default_factory=list)
    user_id: str | int | None = None
    knowledge_scope: str = "public"


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
    context_precision: float | None = None
    context_recall: float | None = None
    error: str | None = None


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
    override_by: str | None = None
    overridden_at: str | None = None


class GoldenDataset(BaseModel):
    """Strict, versioned dataset contract used by the full evaluation run."""

    model_config = ConfigDict(extra="forbid")

    benchmark_version: str
    embedding_model: str
    top_k: int = Field(default=5, ge=1, le=20)
    queries: list[BenchmarkQuery] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_golden_contract(self) -> "GoldenDataset":
        if len(self.queries) != 100:
            raise ValueError(f"golden dataset must contain exactly 100 queries, got {len(self.queries)}")
        ids = [item.query_id for item in self.queries]
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ValueError(f"golden dataset contains duplicate query_id: {duplicates}")
        required = ("reference_answer", "reference_context_ids", "reference_contexts", "expected_route", "expected_tools")
        for item in self.queries:
            missing = [name for name in required if not getattr(item, name)]
            if missing:
                raise ValueError(f"{item.query_id} missing required golden fields: {', '.join(missing)}")
            if len(item.reference_context_ids) != len(item.reference_contexts):
                raise ValueError(f"{item.query_id} reference context ids/texts length mismatch")
        return self

    @property
    def content_hash(self) -> str:
        """Stable hash used to identify the exact evaluated dataset."""
        payload = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class ToolCallObservation(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    duration_ms: float = 0.0
    status: str = "success"
    error_type: str | None = None


class AgentTrace(BaseModel):
    model_config = ConfigDict(extra="allow")

    sample_id: str
    route: str = "base_model"
    tool_calls: list[ToolCallObservation] = Field(default_factory=list)
    candidate_count: int = 0
    filtered_count: int = 0
    confidence: float = 0.0
    coverage: float = 0.0
    fallback_reason: str | None = None
    token_usage: dict[str, int | float] = Field(default_factory=dict)
    estimated_cost_cny: float | None = Field(default=None, ge=0)
    total_latency_ms: float = 0.0
    retry_count: int = 0
    policy_findings: list[str] = Field(default_factory=list)
    completed: bool = False
    answer: str = ""


class RetrievalObservation(BaseModel):
    model_config = ConfigDict(extra="allow")

    sample_id: str
    query: str
    corpus_version: str
    status: str = "published"
    retrieved_contexts: list[str] = Field(default_factory=list)
    retrieved_context_ids: list[str] = Field(default_factory=list)
    hits: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    error: str | None = None


class GenerationObservation(BaseModel):
    model_config = ConfigDict(extra="allow")

    sample_id: str
    response: str = ""
    quiz: dict[str, Any] | list[dict[str, Any]] | None = None
    report: dict[str, Any] | None = None
    latency_ms: float = 0.0
    error: str | None = None


class RuleResult(BaseModel):
    rule_id: str
    passed: bool
    score: float = 1.0
    details: str = ""


class BusinessEvaluation(BaseModel):
    sample_id: str
    kind: str
    passed: bool
    score: float
    rules: list[RuleResult] = Field(default_factory=list)


class RagasMetricResult(BaseModel):
    sample_id: str
    status: str = "unavailable"
    scores: dict[str, float | None] = Field(default_factory=dict)
    error: str | None = None
    model: str | None = None
    embedding_model: str | None = None
    elapsed_ms: float = 0.0
    scenario_type: str = "unknown"


class RagasEvaluationReport(BaseModel):
    status: str = "unavailable"
    metrics: dict[str, float | None] = Field(default_factory=dict)
    samples: list[RagasMetricResult] = Field(default_factory=list)
    provider: str = "ragas"
    error: str | None = None
    elapsed_ms: float = 0.0
    model: str | None = None
    embedding_model: str | None = None
    evaluated_at: str | None = None
    scenario_metrics: dict[str, dict[str, float | None]] = Field(default_factory=dict)


def evaluate_agent_trace(trace: AgentTrace, expected_route: str = "", expected_tools: list[str] | None = None) -> dict[str, Any]:
    """Evaluate an already captured trace without invoking an external model."""
    expected_tools = expected_tools or []
    called = [item.name for item in trace.tool_calls]
    # Early Golden files used the selected tool name as ``expected_route``.
    # Normalize those values to the production router vocabulary while
    # keeping tool selection evaluated independently below.
    route_aliases = {
        "public_milvus_search": "public_kb",
        "personal_milvus_search": "personal_kb",
        "tavily_search": "web_search",
        "tavily_extract": "extract",
    }
    normalized_expected_route = route_aliases.get(expected_route, expected_route)
    route_ok = not normalized_expected_route or trace.route == normalized_expected_route
    tools_ok = all(tool in called for tool in expected_tools)
    policy_ok = not trace.policy_findings
    budget_ok = len(called) <= 8 and trace.retry_count <= 3
    completed = bool(trace.completed)
    result = {
        "result": {"task_completed": completed, "answer_present": bool(trace.answer)},
        "process": {
            "route_correct": route_ok,
            "expected_tools_present": tools_ok,
            "tool_count": len(called),
            "stopped_within_budget": budget_ok,
        },
        "efficiency": {
            "total_latency_ms": trace.total_latency_ms,
            "token_usage": dict(trace.token_usage),
            "estimated_cost_cny": trace.estimated_cost_cny,
            "tool_call_count": len(called),
            "retry_count": trace.retry_count,
        },
        "risk": {
            "policy_findings": list(trace.policy_findings),
            "passed": policy_ok,
        },
        "passed": completed and route_ok and tools_ok and policy_ok and budget_ok,
    }
    return result


def detect_agent_risks(trace: AgentTrace, *, private: bool = False, allowed_tools: set[str] | None = None) -> list[str]:
    """Return hard-fail policy findings for a trace."""
    findings = list(trace.policy_findings)
    allowed_tools = allowed_tools or {"public_milvus_search", "personal_milvus_search", "tavily_search", "tavily_extract", "base_model"}
    for call in trace.tool_calls:
        if call.name not in allowed_tools:
            findings.append(f"forbidden_tool:{call.name}")
        if private and call.name in {"public_milvus_search", "tavily_search", "tavily_extract"}:
            findings.append(f"private_scope_violation:{call.name}")
    if trace.retry_count < 0:
        findings.append("invalid_retry_count")
    return sorted(set(findings))


def aggregate_agent_evaluations(items: list[dict[str, Any]]) -> dict[str, float]:
    if not items:
        return {
            "agent_task_completion_rate": 0.0,
            "agent_answer_present_rate": 0.0,
            "agent_process_pass_rate": 0.0,
            "agent_budget_pass_rate": 0.0,
            "agent_risk_violation_rate": 0.0,
            "agent_p50_latency_ms": 0.0,
            "agent_p95_latency_ms": 0.0,
            "agent_mean_token_usage": 0.0,
            "agent_mean_tool_calls": 0.0,
            "agent_total_retry_count": 0.0,
            "agent_mean_estimated_cost_cny": 0.0,
            "agent_cost_observed_rate": 0.0,
        }
    latencies = [float(item.get("efficiency", {}).get("total_latency_ms", 0.0)) for item in items]
    tokens = [float(sum((item.get("efficiency", {}).get("token_usage", {}) or {}).values())) for item in items]
    risk_findings = [item.get("risk", {}).get("policy_findings", []) or [] for item in items]
    costs = [float(value) for item in items if (value := item.get("efficiency", {}).get("estimated_cost_cny")) is not None]
    private_violations = sum(any("private_scope" in str(finding) for finding in findings) for findings in risk_findings)
    high_risk_false_allows = sum(
        bool(item.get("result", {}).get("task_completed")) and bool(item.get("risk", {}).get("policy_findings", []))
        for item in items
    )
    return {
        "agent_task_completion_rate": sum(bool(item.get("result", {}).get("task_completed")) for item in items) / len(items),
        "agent_answer_present_rate": sum(bool(item.get("result", {}).get("answer_present")) for item in items) / len(items),
        "agent_process_pass_rate": sum(bool(item.get("process", {}).get("route_correct")) and bool(item.get("process", {}).get("expected_tools_present")) for item in items) / len(items),
        "agent_budget_pass_rate": sum(bool(item.get("process", {}).get("stopped_within_budget")) for item in items) / len(items),
        "agent_risk_violation_rate": sum(not bool(item.get("risk", {}).get("passed", True)) for item in items) / len(items),
        "agent_p50_latency_ms": _percentile(latencies, 0.50),
        "agent_p95_latency_ms": _percentile(latencies, 0.95),
        "agent_mean_token_usage": statistics.fmean(tokens) if tokens else 0.0,
        "agent_mean_tool_calls": statistics.fmean(float(item.get("process", {}).get("tool_count", 0)) for item in items),
        "agent_total_retry_count": sum(float(item.get("efficiency", {}).get("retry_count", 0)) for item in items),
        "agent_mean_estimated_cost_cny": statistics.fmean(costs) if costs else 0.0,
        "agent_cost_observed_rate": len(costs) / len(items),
        "private_kb_violation_rate": private_violations / len(items),
        "high_risk_false_allow_rate": high_risk_false_allows / len(items),
    }


RAGAS_METRIC_NAMES = (
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_relevancy",
)


_SENSITIVE_KEY = re.compile(r"(api[_-]?key|secret|token|password|authorization|cookie|openid|user[_-]?id)", re.IGNORECASE)


def redact_evaluation(value: Any) -> Any:
    """Recursively remove credentials and user identifiers from trace/report data."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact_evaluation(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_evaluation(item) for item in value]
    if isinstance(value, tuple):
        return [redact_evaluation(item) for item in value]
    return value


def load_benchmark(path: str | Path) -> BenchmarkSet:
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return BenchmarkSet.model_validate(raw)


def migrate_legacy_benchmark(path: str | Path, *, output: str | Path | None = None) -> BenchmarkSet:
    """Create an auditable enriched copy of a historical benchmark.

    Historical benchmark files intentionally remain immutable.  Missing
    reference fields are derived from the labelled query and knowledge points
    so the migrated artifact can be reviewed and then replaced with curated
    excerpts without changing query IDs or relevance labels.
    """
    benchmark = load_benchmark(path)
    migrated: list[BenchmarkQuery] = []
    for item in benchmark.queries:
        context = " ".join([item.query, *item.expected_knowledge_points])
        migrated.append(item.model_copy(update={
            "reference_answer": item.reference_answer or f"{item.topic}：{context}",
            "reference_context_ids": item.reference_context_ids or list(item.relevance.keys()),
            "reference_contexts": item.reference_contexts or [context],
            "expected_route": item.expected_route or "public_milvus_search",
            "expected_tools": item.expected_tools or ["public_milvus_search"],
        }))
    result = BenchmarkSet.model_validate({**benchmark.model_dump(mode="json"), "queries": [q.model_dump(mode="json") for q in migrated]})
    if output:
        import yaml
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(result.model_dump(mode="json"), allow_unicode=True, sort_keys=False), encoding="utf-8")
    return result


def load_golden_dataset(path: str | Path) -> GoldenDataset:
    """Load the strict 100-sample dataset used by full offline evaluation."""
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    try:
        dataset = GoldenDataset.model_validate(raw)
    except ValidationError:
        raise
    violations = validate_no_sensitive_golden_data(dataset)
    if violations:
        raise ValueError("golden dataset contains sensitive data: " + "; ".join(violations))
    return dataset


def _tokenize_for_eval(value: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9][a-z0-9_+#.-]{1,}", value.lower()))
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", value):
        words.update(segment[index:index + 2] for index in range(len(segment) - 1))
    return words


def calculate_context_metrics(query: BenchmarkQuery, hits: list[dict[str, Any]]) -> dict[str, float]:
    """Deterministic context precision/recall approximation for offline triage.

    RAGAS remains the authoritative generation-quality implementation. These
    scores are useful when the optional evaluator is unavailable and are
    explicitly reported under the deterministic retrieval section.
    """
    expected_ids = {str(item) for item in query.reference_context_ids if str(item)}
    expected_text = " ".join(query.reference_contexts)
    expected_tokens = _tokenize_for_eval(expected_text)
    relevant = 0
    covered_tokens: set[str] = set()
    for hit in hits:
        identity = _identity(hit)
        text = str(hit.get("parent_text") or hit.get("evidence_text") or hit.get("text") or "")
        hit_tokens = _tokenize_for_eval(text)
        is_relevant = bool(identity and identity in expected_ids)
        if not is_relevant and expected_tokens and hit_tokens:
            overlap = len(expected_tokens & hit_tokens) / max(1, len(expected_tokens))
            is_relevant = overlap >= 0.12
        if is_relevant:
            relevant += 1
            covered_tokens.update(hit_tokens)
    precision = relevant / max(1, len(hits))
    recall = len(covered_tokens & expected_tokens) / max(1, len(expected_tokens)) if expected_tokens else (1.0 if relevant else 0.0)
    return {"context_precision": min(1.0, precision), "context_recall": min(1.0, recall)}


def validate_no_sensitive_golden_data(dataset: GoldenDataset) -> list[str]:
    violations: list[str] = []
    for item in dataset.queries:
        payload = item.model_dump(mode="json")
        def scan(value: Any, key: str = "") -> bool:
            if isinstance(value, dict):
                return any(scan(child, str(name)) for name, child in value.items())
            if isinstance(value, list):
                return any(scan(child, key) for child in value)
            if _SENSITIVE_KEY.search(key):
                return value is not None and bool(str(value).strip())
            text = str(value or "")
            return bool(re.search(r"(?:api[_-]?key|password|authorization|openid)\\s*[:=]\\s*\\S+|bearer\\s+[A-Za-z0-9._-]{12,}", text, re.I))
        if scan(payload):
            violations.append(f"{item.query_id}: sensitive credential-like content")
    return violations


def _as_question_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("questions", "items", "quiz", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _text_tokens(value: Any) -> set[str]:
    return _tokenize_for_eval(str(value or ""))


def evaluate_quiz_business(sample_id: str, payload: Any, expected_points: list[str], expected_difficulty: str, evidence: list[dict[str, Any]] | None = None) -> BusinessEvaluation:
    rules: list[RuleResult] = []
    questions = _as_question_list(payload)
    rules.append(RuleResult(rule_id="quiz.non_empty", passed=bool(questions), score=1.0 if questions else 0.0, details="question_count=%d" % len(questions)))
    seen: set[str] = set()
    duplicate_count = 0
    covered = set()
    for question in questions:
        text = " ".join(str(question.get(key) or "") for key in ("question", "stem", "content", "explanation"))
        normalized = " ".join(text.lower().split())
        if normalized and normalized in seen:
            duplicate_count += 1
        if normalized:
            seen.add(normalized)
        covered.update(_text_tokens(text))
    rules.append(RuleResult(rule_id="quiz.no_duplicate_questions", passed=duplicate_count == 0, score=1.0 if duplicate_count == 0 else 0.0, details=f"duplicates={duplicate_count}"))
    structure_errors: list[str] = []
    for index, question in enumerate(questions, 1):
        qtype = str(question.get("type") or question.get("question_type") or "single").lower()
        options = question.get("options") or question.get("choices") or []
        options_count = len(options) if isinstance(options, list) else 0
        answer = question.get("answer", question.get("correct_answer", question.get("correctAnswer")))
        answer_values = answer if isinstance(answer, list) else ([answer] if answer not in (None, "") else [])
        if qtype in {"single", "single_choice", "choice"} and len(answer_values) != 1:
            structure_errors.append(f"q{index}:single_answer_count={len(answer_values)}")
        if qtype in {"multiple", "multiple_choice", "multi"} and len(answer_values) < 2:
            structure_errors.append(f"q{index}:multiple_answer_count={len(answer_values)}")
        if qtype in {"true_false", "判断题", "judge"} and options_count not in (0, 2):
            structure_errors.append(f"q{index}:true_false_options={options_count}")
        if options_count:
            # Production ``Question`` objects expose options as ``{key, text}``
            # mappings, while lightweight fixtures may use plain strings.  The
            # answer contract is the option key (for example ``"B"``), so
            # compare against keys as well as the legacy string representation.
            option_keys = {
                str(option.get("key"))
                for option in options
                if isinstance(option, dict) and option.get("key") is not None
            }
            option_values = {
                str(option) for option in options
                if not isinstance(option, dict)
            }
            allowed_answers = option_keys | option_values
            invalid_answers = [
                value for value in answer_values
                if not (
                    str(value) in allowed_answers
                    or (isinstance(value, int) and 0 <= value < options_count)
                )
            ]
            if invalid_answers:
                structure_errors.append(f"q{index}:answer_not_in_options")
    rules.append(RuleResult(rule_id="quiz.valid_question_structure", passed=not structure_errors, score=1.0 if not structure_errors else 0.0, details=";".join(structure_errors)))
    expected = _text_tokens(" ".join(expected_points))
    coverage = len(expected & covered) / max(1, len(expected))
    rules.append(RuleResult(rule_id="quiz.knowledge_point_coverage", passed=coverage >= 0.5 if expected else bool(questions), score=coverage, details=f"coverage={coverage:.3f}"))
    difficulty_values = {str(item.get("difficulty") or item.get("level") or "").lower() for item in questions}
    difficulty_values.discard("")
    difficulty_ok = not difficulty_values or str(expected_difficulty).lower() in difficulty_values
    rules.append(RuleResult(rule_id="quiz.difficulty_matches", passed=difficulty_ok, score=1.0 if difficulty_ok else 0.0, details=f"expected={expected_difficulty};actual={sorted(difficulty_values)}"))
    evidence_text = " ".join(str(item.get("text") or "") for item in (evidence or []))
    evidence_ok = bool(evidence_text) and bool(_text_tokens(evidence_text) & covered) if questions else False
    rules.append(RuleResult(rule_id="quiz.evidence_supported", passed=evidence_ok if evidence else True, score=1.0 if evidence_ok or not evidence else 0.0, details="evidence_present=%s" % bool(evidence)))
    score = sum(item.score for item in rules) / max(1, len(rules))
    return BusinessEvaluation(sample_id=sample_id, kind="quiz", passed=all(item.passed for item in rules), score=score, rules=rules)


def evaluate_report_business(sample_id: str, payload: Any, expected_points: list[str], topic: str, evidence: list[dict[str, Any]] | None = None) -> BusinessEvaluation:
    report = payload if isinstance(payload, dict) else {}
    rules: list[RuleResult] = []
    aliases = {
        "summary": ("summary", "overall_summary", "conclusion", "总评"),
        "weakness": ("weaknesses", "weak_points", "weakness", "薄弱点"),
        "recommendation": ("recommendations", "suggestions", "advice", "建议"),
    }
    for rule_id, keys in aliases.items():
        present = any(str(report.get(key) or "").strip() or isinstance(report.get(key), list) and report.get(key) for key in keys)
        rules.append(RuleResult(rule_id=f"report.has_{rule_id}", passed=present, score=1.0 if present else 0.0, details=f"keys={keys}"))
    serialized = json.dumps(report, ensure_ascii=False)
    point_tokens = _text_tokens(" ".join(expected_points))
    coverage = len(point_tokens & _text_tokens(serialized)) / max(1, len(point_tokens))
    rules.append(RuleResult(rule_id="report.covers_knowledge_points", passed=coverage >= 0.3 if point_tokens else bool(serialized.strip()), score=coverage, details=f"coverage={coverage:.3f}"))
    relevant = bool(_text_tokens(topic) & _text_tokens(serialized)) if topic else bool(serialized.strip())
    rules.append(RuleResult(rule_id="report.topic_relevant", passed=relevant, score=1.0 if relevant else 0.0, details=f"topic={topic}"))
    evidence_ok = bool(evidence) and bool(_text_tokens(" ".join(str(item.get("text") or "") for item in evidence)) & _text_tokens(serialized))
    rules.append(RuleResult(rule_id="report.evidence_supported", passed=evidence_ok if evidence else True, score=1.0 if evidence_ok else 0.0, details="evidence_present=%s" % bool(evidence)))
    score = sum(item.score for item in rules) / max(1, len(rules))
    return BusinessEvaluation(sample_id=sample_id, kind="report", passed=all(item.passed for item in rules), score=score, rules=rules)


def aggregate_business_evaluations(items: list[BusinessEvaluation], kind: str) -> dict[str, float]:
    selected = [item for item in items if item.kind == kind]
    if not selected:
        return {f"{kind}_valid_rate": 0.0, f"{kind}_mean_score": 0.0}
    return {
        f"{kind}_valid_rate": sum(1 for item in selected if item.passed) / len(selected),
        f"{kind}_mean_score": sum(item.score for item in selected) / len(selected),
    }


def aggregate_quiz_quality(items: list[BusinessEvaluation]) -> dict[str, float]:
    """Aggregate quiz validity and duplicate-rule outcomes for quality gates."""
    selected = [item for item in items if item.kind == "quiz"]
    if not selected:
        return {"quiz_valid_rate": 0.0, "quiz_duplicate_rate": 0.0}
    duplicate_failures = sum(
        1 for item in selected if any(rule.rule_id == "quiz.no_duplicate_questions" and not rule.passed for rule in item.rules)
    )
    return {
        "quiz_valid_rate": sum(item.passed for item in selected) / len(selected),
        "quiz_duplicate_rate": duplicate_failures / len(selected),
    }


def aggregate_report_quality(items: list[BusinessEvaluation]) -> dict[str, float]:
    selected = [item for item in items if item.kind == "report"]
    if not selected:
        return {"report_valid_rate": 0.0, "report_mean_score": 0.0}
    return {
        "report_valid_rate": sum(item.passed for item in selected) / len(selected),
        "report_mean_score": sum(item.score for item in selected) / len(selected),
    }


def enforce_full_gate(
    metrics: dict[str, float],
    *,
    gates: dict[str, dict[str, float | str]] | None = None,
    override_reason: str | None = None,
    override_by: str | None = None,
    overridden_at: str | None = None,
    required_metrics: set[str] | None = None,
) -> GateResult:
    """Apply deterministic, RAGAS, business and safety gates to flat metrics."""
    failed: dict[str, dict[str, float | str]] = {}
    for name, rule in (gates or FULL_EVALUATION_GATES).items():
        if required_metrics is not None and name not in required_metrics:
            continue
        if name not in metrics or metrics[name] is None:
            failed[name] = {"actual": "unavailable", "expected": float(rule["value"]), "operator": str(rule["operator"])}
            continue
        actual = float(metrics[name])
        expected = float(rule["value"])
        operator = str(rule["operator"])
        if (operator == "min" and actual < expected) or (operator == "max" and actual > expected):
            failed[name] = {"actual": actual, "expected": expected, "operator": operator}
    if override_reason is not None and not str(override_reason).strip():
        raise ValueError("override_reason must not be blank")
    if override_reason and not str(override_by or "").strip():
        raise ValueError("override_by is required when overriding a failed gate")
    if override_reason and not overridden_at:
        overridden_at = datetime.now(UTC).isoformat()
    return GateResult(
        passed=not failed or bool(override_reason),
        failed_metrics=failed,
        override_reason=override_reason.strip() if override_reason else None,
        override_by=str(override_by).strip() if override_by else None,
        overridden_at=overridden_at,
    )


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
        return {key: 0.0 for key in ("hit_at_5", "mrr_at_5", "ndcg_at_5", "context_precision", "context_recall")}
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
    context_precisions: list[float] = []
    context_recalls: list[float] = []
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
        seen_parents: set[str] = set()
        for hit in ranked:
            total_hits += 1
            content_hash = str(hit.get("content_hash") or "")
            parent_identity = _identity(hit)
            is_duplicate = bool(
                (content_hash and content_hash in seen_hashes)
                or (parent_identity and parent_identity in seen_parents)
            )
            if is_duplicate:
                duplicates += 1
            if content_hash:
                seen_hashes.add(content_hash)
            if parent_identity:
                seen_parents.add(parent_identity)
            roles = hit.get("role_tags") or []
            if isinstance(roles, str):
                roles = [item for item in roles.strip("|").split("|") if item]
            if result.query.role not in roles and "general" not in roles:
                contaminated += 1
            if hit.get("source_name") or hit.get("source_url") or hit.get("citation"):
                traceable += 1
            if hit.get("parent_recovered") is True:
                recoverable += 1
        context = calculate_context_metrics(result.query, ranked)
        context_precisions.append(context["context_precision"])
        context_recalls.append(context["context_recall"])
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
        "context_precision": statistics.fmean(context_precisions),
        "context_recall": statistics.fmean(context_recalls),
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
        try:
            rows = store.search(query.query, benchmark.top_k, role=query.role, corpus_version=corpus_version, status=status)
        except Exception as exc:
            results.append(QueryEvaluation(query=query, hits=[], latency_ms=(time.perf_counter() - started) * 1000, answer_integrity=False, error=f"{type(exc).__name__}: {exc}"))
            continue
        latency_ms = (time.perf_counter() - started) * 1000
        hits = [_normalize_hit(row, store) for row in rows]
        answer_integrity = all(_answer_integrity(hit) for hit in hits) if hits else False
        context = calculate_context_metrics(query, hits[: benchmark.top_k])
        results.append(QueryEvaluation(query=query, hits=hits, latency_ms=latency_ms, answer_integrity=answer_integrity, **context))
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
    override_by: str | None = None,
    overridden_at: str | None = None,
) -> GateResult:
    failed: dict[str, dict[str, float | str]] = {}
    for name, rule in (gates or DEFAULT_GATES).items():
        actual = float(report.metrics.get(name, 0.0))
        expected = float(rule["value"])
        operator = str(rule["operator"])
        if (operator == "min" and actual < expected) or (operator == "max" and actual > expected):
            failed[name] = {"actual": actual, "expected": expected, "operator": operator}
    if override_reason is not None and not str(override_reason).strip():
        raise ValueError("override_reason must not be blank")
    if override_reason and not str(override_by or "").strip():
        raise ValueError("override_by is required when overriding a failed gate")
    if override_reason and not overridden_at:
        overridden_at = datetime.now(UTC).isoformat()
    return GateResult(
        passed=not failed or bool(override_reason),
        failed_metrics=failed,
        override_reason=override_reason.strip() if override_reason else None,
        override_by=str(override_by).strip() if override_by else None,
        overridden_at=overridden_at,
    )


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


def compare_evaluation_payloads(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare either full envelopes or legacy wrapped EvaluationReports."""
    current_dataset = current.get("dataset", {})
    candidate_dataset = candidate.get("dataset", {})
    if current_dataset or candidate_dataset:
        if current_dataset.get("benchmark_version") != candidate_dataset.get("benchmark_version"):
            raise ValueError("reports require identical benchmark version")
        if (current.get("metadata", {}).get("top_k") or current.get("retrieval", {}).get("top_k")) != (candidate.get("metadata", {}).get("top_k") or candidate.get("retrieval", {}).get("top_k")):
            raise ValueError("reports require identical top-k")
        left = dict(current.get("retrieval", {}).get("metrics", {}))
        right = dict(candidate.get("retrieval", {}).get("metrics", {}))
        for section in ("ragas", "quiz_quality", "report_quality", "agent"):
            left.update({f"{section}.{k}": v for k, v in (current.get(section) or {}).get("metrics", current.get(section) or {}).items() if isinstance(v, (int, float))})
            right.update({f"{section}.{k}": v for k, v in (candidate.get(section) or {}).get("metrics", candidate.get(section) or {}).items() if isinstance(v, (int, float))})
        deltas = {name: float(right.get(name, 0) or 0) - float(left.get(name, 0) or 0) for name in set(left) | set(right)}
        thresholds = {
            **(current.get("metadata", {}).get("comparison_thresholds") or {}),
            **(candidate.get("metadata", {}).get("comparison_thresholds") or {}),
        }
        lower = {name for name in deltas if any(token in name for token in ("latency", "duplicate", "contamination", "violation", "risk"))}
        def tolerance(name: str) -> float:
            if name in thresholds:
                return float(thresholds[name])
            if "latency" in name:
                return float(thresholds.get("latency_ms", 0.0))
            return float(thresholds.get("risk_rate", 0.0) if name in lower else thresholds.get("quality", 0.0))
        regression_details = {
            name: {"delta": delta, "threshold": tolerance(name), "direction": "increase_is_bad" if name in lower else "decrease_is_bad"}
            for name, delta in deltas.items()
            if (name in lower and delta > tolerance(name)) or (name not in lower and -delta > tolerance(name))
        }
        regressions = sorted(regression_details)
        current_samples = {str(item.get("query", {}).get("query_id")): item for item in current.get("samples", [])}
        drift = []
        for item in candidate.get("samples", []):
            sample_id = str(item.get("query", {}).get("query_id"))
            previous = current_samples.get(sample_id)
            if previous is None:
                continue
            old_hits = [str(hit.get("parent_id") or hit.get("document_id") or hit.get("source_id") or "") for hit in previous.get("hits", [])]
            new_hits = [str(hit.get("parent_id") or hit.get("document_id") or hit.get("source_id") or "") for hit in item.get("hits", [])]
            if old_hits != new_hits:
                drift.append(sample_id)
        return {
            "metric_deltas": deltas,
            "regressions": regressions,
            "regression_details": regression_details,
            "comparison_thresholds": thresholds,
            "result_drift": sorted(drift),
            "gate_changed": current.get("gates") != candidate.get("gates"),
        }
    return compare_reports(EvaluationReport.model_validate(current.get("report", current)), EvaluationReport.model_validate(candidate.get("report", candidate)))


FULL_EVALUATION_GATES: dict[str, dict[str, float | str]] = {
    **DEFAULT_GATES,
    "context_precision": {"operator": "min", "value": 0.80},
    "context_recall": {"operator": "min", "value": 0.80},
    "faithfulness": {"operator": "min", "value": 0.85},
    "answer_relevancy": {"operator": "min", "value": 0.80},
    "quiz_valid_rate": {"operator": "min", "value": 1.0},
    "report_valid_rate": {"operator": "min", "value": 1.0},
    "quiz_duplicate_rate": {"operator": "max", "value": 0.05},
    "private_kb_violation_rate": {"operator": "max", "value": 0.0},
    "high_risk_false_allow_rate": {"operator": "max", "value": 0.0},
}


def build_evaluation_payload(
    report: EvaluationReport,
    *,
    dataset: GoldenDataset | None = None,
    ragas: RagasEvaluationReport | None = None,
    quiz_quality: dict[str, float] | None = None,
    report_quality: dict[str, float] | None = None,
    agent: dict[str, Any] | None = None,
    gates: GateResult | None = None,
    errors: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    generation_observations: dict[str, Any] | None = None,
    agent_traces: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the stable JSON envelope consumed by CLI and CI."""
    return redact_evaluation({
        "metadata": {
            "generated_at": time.time(),
            "evaluator_version": "1",
            "top_k": report.top_k,
            "corpus_version": report.corpus_version,
            **(metadata or {}),
        },
        "dataset": {
            "benchmark_version": report.benchmark_version,
            "sample_count": len(report.queries),
            "content_hash": dataset.content_hash if dataset else None,
        },
        "retrieval": {"corpus_version": report.corpus_version, "metrics": report.metrics},
        "ragas": ragas.model_dump(mode="json") if ragas else {"status": "not_requested", "metrics": {}},
        "quiz_quality": quiz_quality or {},
        "report_quality": report_quality or {},
        "agent": agent or {},
        "gates": gates.model_dump(mode="json") if gates else None,
        "samples": [
            {
                **item.model_dump(mode="json"),
                "generation": (
                    generation_observations.get(item.query.query_id).model_dump(mode="json")
                    if generation_observations and hasattr(generation_observations.get(item.query.query_id), "model_dump")
                    else None
                ),
                "agent_trace": (
                    agent_traces.get(item.query.query_id).model_dump(mode="json")
                    if agent_traces and hasattr(agent_traces.get(item.query.query_id), "model_dump")
                    else None
                ),
            }
            for item in report.queries
        ],
        "errors": errors or [],
    })


def render_evaluation_markdown(payload: dict[str, Any]) -> str:
    """Render Markdown from the JSON payload so both outputs stay in sync."""
    retrieval = payload.get("retrieval", {})
    lines = ["# EasyOffer RAG Evaluation", "", f"- Corpus: `{retrieval.get('corpus_version', '')}`", f"- Dataset: `{payload.get('dataset', {}).get('benchmark_version', '')}`", f"- Samples: `{payload.get('dataset', {}).get('sample_count', 0)}`", "", "## Retrieval", ""]
    for name, value in (retrieval.get("metrics") or {}).items():
        lines.append(f"- {name}: `{value}`")
    ragas = payload.get("ragas") or {}
    lines.extend(["", "## RAGAS", "", f"- status: `{ragas.get('status', 'unavailable')}`"])
    for name, value in (ragas.get("metrics") or {}).items():
        lines.append(f"- {name}: `{value}`")
    for section in ("quiz_quality", "report_quality", "agent"):
        lines.extend(["", f"## {section}", ""])
        for name, value in (payload.get(section) or {}).items():
            lines.append(f"- {name}: `{value}`")
    failures = [item for item in payload.get("samples", []) if item.get("answer_integrity") is False]
    lines.extend(["", "## Failures", "", f"- count: `{len(failures)}`"])
    for item in failures:
        query = item.get("query", {})
        lines.append(f"- `{query.get('query_id', 'unknown')}`")
    return "\n".join(lines) + "\n"


def write_evaluation_files(payload: dict[str, Any], json_path: str | Path, markdown_path: str | Path | None = None) -> tuple[Path, Path]:
    """Atomically write JSON and its Markdown rendering."""
    json_target = Path(json_path)
    markdown_target = Path(markdown_path) if markdown_path else json_target.with_suffix(".md")
    json_target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    json_tmp = json_target.with_suffix(json_target.suffix + f".{token}.tmp")
    md_tmp = markdown_target.with_suffix(markdown_target.suffix + f".{token}.tmp")
    json_backup = json_target.with_suffix(json_target.suffix + f".{token}.bak")
    md_backup = markdown_target.with_suffix(markdown_target.suffix + f".{token}.bak")
    json_tmp.write_text(json.dumps(redact_evaluation(payload), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md_tmp.write_text(render_evaluation_markdown(payload), encoding="utf-8")
    moved_json = moved_md = False
    try:
        if json_target.exists():
            os.replace(json_target, json_backup)
            moved_json = True
        if markdown_target.exists():
            os.replace(markdown_target, md_backup)
            moved_md = True
        os.replace(json_tmp, json_target)
        os.replace(md_tmp, markdown_target)
    except Exception:
        # Restore the previous pair if either replacement failed.  A failed
        # evaluation must never destroy the last known-good report.
        if json_target.exists() and moved_json:
            json_target.unlink()
        if markdown_target.exists() and moved_md:
            markdown_target.unlink()
        if moved_json and json_backup.exists():
            os.replace(json_backup, json_target)
        if moved_md and md_backup.exists():
            os.replace(md_backup, markdown_target)
        raise
    finally:
        for path in (json_tmp, md_tmp, json_backup, md_backup):
            if path.exists():
                path.unlink()
    return json_target, markdown_target
