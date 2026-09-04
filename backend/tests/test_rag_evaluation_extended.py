from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.corpus.evaluation import (
    AgentTrace,
    BenchmarkQuery,
    GoldenDataset,
    ToolCallObservation,
    calculate_context_metrics,
    detect_agent_risks,
    evaluate_agent_trace,
    evaluate_quiz_business,
    evaluate_report_business,
    redact_evaluation,
    build_evaluation_payload,
    compare_evaluation_payloads,
    enforce_full_gate,
    write_evaluation_files,
    EvaluationReport,
    aggregate_agent_evaluations,
    calculate_metrics,
    QueryEvaluation,
    RetrievalObservation,
)
from app.corpus.ragas_evaluation import evaluate_ragas, evaluate_ragas_from_observations
from app.corpus.evaluation_runner import OfflineEvaluationRunner, ProductionEvaluationAdapter
from app.corpus.config import CorpusConfig
from app.corpus.pipeline import CorpusPipeline
from app.corpus.storage import InMemoryCorpusStore


def query(**overrides):
    data = dict(
        query_id="q-1", topic="RAG", query="What is RAG?", role="backend", difficulty="medium",
        expected_technologies=["RAG"], relevance={"ctx": 2}, expected_knowledge_points=["retrieval"],
        reference_answer="RAG retrieves evidence before generation.", reference_context_ids=["ctx"],
        reference_contexts=["RAG retrieves evidence before generation."], expected_route="public_milvus_search",
        expected_tools=["public_milvus_search"],
    )
    data.update(overrides)
    return data


def test_context_metrics_full_partial_and_empty():
    item = BenchmarkQuery.model_validate(query())
    assert calculate_context_metrics(item, [{"parent_id": "ctx", "text": "RAG retrieves evidence."}])["context_precision"] == 1.0
    assert calculate_context_metrics(item, [])["context_recall"] == 0.0


def test_business_evaluators_report_rule_ids():
    quiz = evaluate_quiz_business("q", {"questions": [{"type": "single", "question": "retrieval", "options": ["a"], "answer": ["a"]}]}, ["retrieval"], "medium")
    assert quiz.passed
    structured_quiz = evaluate_quiz_business(
        "q-structured",
        {"questions": [{"type": "single", "stem": "retrieval", "options": [
            {"key": "A", "text": "retrieval"}, {"key": "B", "text": "generation"}
        ], "answer": ["A"], "difficulty": "medium"}]},
        ["retrieval"], "medium",
    )
    assert structured_quiz.passed
    report = evaluate_report_business("q", {"summary": "RAG retrieval", "weaknesses": ["x"], "recommendations": ["y"]}, ["retrieval"], "RAG")
    assert report.passed
    assert {rule.rule_id for rule in report.rules} >= {"report.has_summary", "report.has_weakness", "report.has_recommendation"}


def test_agent_trace_four_layers_and_risk():
    trace = AgentTrace(sample_id="q", route="public_kb", completed=True, answer="ok", tool_calls=[ToolCallObservation(name="public_milvus_search")])
    evaluation = evaluate_agent_trace(trace, "public_milvus_search", ["public_milvus_search"])
    assert evaluation["passed"]
    assert "private_scope_violation:tavily_search" in detect_agent_risks(trace.model_copy(update={"tool_calls": [ToolCallObservation(name="tavily_search")]}), private=True)


def test_redaction_removes_secret_values_by_key():
    value = redact_evaluation({"api_key": "secret", "nested": {"Authorization": "Bearer abc"}, "topic": "RAG"})
    assert value["api_key"] == "[REDACTED]"
    assert value["nested"]["Authorization"] == "[REDACTED]"
    assert value["topic"] == "RAG"


def test_ragas_unavailable_is_explicit(monkeypatch):
    dataset = GoldenDataset(benchmark_version="v", embedding_model="e", queries=[query(query_id=f"q-{i}") for i in range(100)])
    async def fake(*args, **kwargs):
        return {"context_precision": 1.0}
    result = asyncio.run(evaluate_ragas(dataset, [{"sample_id": "q-0", "user_input": "x"}], evaluator=fake))
    assert result.status == "partial"
    assert result.samples[0].status == "failed"


def test_ragas_results_are_joined_by_sample_id_and_proxy_is_excluded():
    dataset = GoldenDataset(benchmark_version="v", embedding_model="e", queries=[query(query_id=f"q-{i}") for i in range(100)])

    async def fake(rows, **kwargs):
        # Deliberately reverse the order and include a proxy metric.
        return [
            {"sample_id": "q-1", "context_precision": 0.7, "context_recall": 0.8,
             "faithfulness": 0.9, "answer_relevancy_proxy": 0.99},
            {"sample_id": "q-0", "context_precision": 0.9, "context_recall": 0.8,
             "faithfulness": 0.9, "answer_relevancy": 0.8},
        ]

    result = asyncio.run(evaluate_ragas(dataset, [
        {"sample_id": "q-0", "user_input": "x"},
        {"sample_id": "q-1", "user_input": "y"},
    ], evaluator=fake, metrics=[type("M", (), {"name": "context_precision"})(),
                                type("M", (), {"name": "context_recall"})(),
                                type("M", (), {"name": "faithfulness"})(),
                                type("M", (), {"name": "answer_relevancy"})(),
                                type("M", (), {"name": "answer_relevancy_proxy"})()]))
    assert result.status == "partial"
    assert result.samples[0].sample_id == "q-0"
    assert result.samples[0].scores["answer_relevancy"] == 0.8
    assert "answer_relevancy_proxy" not in result.metrics


def test_full_gate_requires_auditable_override():
    with pytest.raises(ValueError, match="override_by"):
        enforce_full_gate({"faithfulness": 0.1}, gates={"faithfulness": {"operator": "min", "value": 0.8}}, override_reason="known provider incident")
    result = enforce_full_gate({"faithfulness": 0.1}, gates={"faithfulness": {"operator": "min", "value": 0.8}}, override_reason="known provider incident", override_by="release-engineer")
    assert result.passed and result.overridden_at


def test_agent_route_keeps_router_and_tool_names_separate():
    trace = AgentTrace(
        sample_id="q", route="public_kb", completed=True, answer="evidence",
        tool_calls=[ToolCallObservation(name="public_milvus_search")],
    )

    result = evaluate_agent_trace(
        trace, expected_route="public_milvus_search",
        expected_tools=["public_milvus_search"],
    )

    assert result["process"]["route_correct"] is True
    assert result["process"]["expected_tools_present"] is True


def test_full_ragas_gate_contract_includes_both_context_metrics():
    from app.corpus.evaluation import FULL_EVALUATION_GATES

    assert FULL_EVALUATION_GATES["context_precision"] == {"operator": "min", "value": 0.80}
    assert FULL_EVALUATION_GATES["context_recall"] == {"operator": "min", "value": 0.80}


def test_full_payload_comparison_detects_retrieval_drift_without_mutating_inputs():
    base = {"metadata": {"top_k": 5}, "dataset": {"benchmark_version": "v"},
            "retrieval": {"metrics": {"hit_at_5": 1.0}}, "samples": [{"query": {"query_id": "q"}, "hits": [{"parent_id": "old"}]}], "gates": {"passed": True}}
    candidate = {"metadata": {"top_k": 5}, "dataset": {"benchmark_version": "v"},
                 "retrieval": {"metrics": {"hit_at_5": 0.5}}, "samples": [{"query": {"query_id": "q"}, "hits": [{"parent_id": "new"}]}], "gates": {"passed": False}}
    result = compare_evaluation_payloads(base, candidate)
    assert result["result_drift"] == ["q"]
    assert base["retrieval"]["metrics"] == {"hit_at_5": 1.0}


def test_report_pair_write_restores_previous_files_when_replacement_fails(tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    markdown = output.with_suffix(".md")
    output.write_text('{"old": true}', encoding="utf-8")
    markdown.write_text("old markdown", encoding="utf-8")
    report = EvaluationReport(corpus_version="v", benchmark_version="b", top_k=5, metrics={}, queries=[])
    payload = build_evaluation_payload(report)
    import app.corpus.evaluation as module
    original_replace = module.os.replace
    calls = {"count": 0}

    def fail_second_replace(source, destination):
        calls["count"] += 1
        if calls["count"] == 4:
            raise OSError("simulated disk fault")
        return original_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_second_replace)
    with pytest.raises(OSError):
        write_evaluation_files(payload, output)
    assert json.loads(output.read_text(encoding="utf-8")) == {"old": True}
    assert markdown.read_text(encoding="utf-8") == "old markdown"


def test_runner_uses_requested_published_version_and_private_user_scope():
    store = InMemoryCorpusStore()
    common = {"document_id": "doc", "parent_id": "ctx", "role_tags": ["backend"], "source_name": "docs", "text": "RAG evidence", "embedding_text": "RAG evidence"}
    store.upsert([
        {**common, "chunk_id": "old", "corpus_version": "old", "status": "published", "user_id": "1"},
        {**common, "chunk_id": "new-user-1", "corpus_version": "new", "status": "published", "user_id": "1"},
        {**common, "chunk_id": "new-user-2", "corpus_version": "new", "status": "published", "user_id": "2"},
    ])
    runner = OfflineEvaluationRunner(store, corpus_version="new", status="published")
    observation = runner.retrieve(BenchmarkQuery.model_validate(query(knowledge_scope="private", user_id="1")))
    assert observation.error is None
    assert observation.hits and all(hit["corpus_version"] == "new" for hit in observation.hits)
    assert all(str(hit["user_id"]) == "1" for hit in observation.hits)


def test_runner_does_not_hide_callback_type_error_and_resolves_legacy_async_callback():
    dataset = GoldenDataset(benchmark_version="v", embedding_model="e", queries=[query(query_id=f"q-{i}") for i in range(100)])

    async def legacy_callback(query, observation):
        return {"query": query.query_id}

    result = OfflineEvaluationRunner(InMemoryCorpusStore(), corpus_version="v", generation_fn=legacy_callback).run_full(dataset)
    assert result["generations"]["q-0"] == {"query": "q-0"}

    def broken_callback(*, query, observation):
        raise TypeError("callback implementation error")

    with pytest.raises(TypeError, match="callback implementation error"):
        OfflineEvaluationRunner(InMemoryCorpusStore(), corpus_version="v", generation_fn=broken_callback).run_full(dataset)


def test_ragas_mock_handles_success_timeout_auth_and_malformed_results():
    dataset = GoldenDataset(benchmark_version="v", embedding_model="e", queries=[query(query_id=f"q-{i}") for i in range(100)])
    rows = [{"sample_id": "q-0", "user_input": "RAG", "response": "quiz", "reference": "answer", "retrieved_contexts": ["context"]}]

    async def success(*args, **kwargs):
        return [{"sample_id": "q-0", "context_precision": 1.0, "context_recall": 1.0, "faithfulness": 1.0, "answer_relevancy": 1.0}]

    ok = asyncio.run(evaluate_ragas(dataset, rows, evaluator=success, max_retries=0))
    assert ok.status == "success" and set(ok.metrics) == {"context_precision", "context_recall", "faithfulness", "answer_relevancy"}

    async def timeout(*args, **kwargs):
        await asyncio.sleep(0.05)

    timed_out = asyncio.run(evaluate_ragas(dataset, rows, evaluator=timeout, timeout_seconds=0.001, max_retries=0))
    assert timed_out.status == "failed" and "TimeoutError" in (timed_out.error or "")

    async def unauthorized(*args, **kwargs):
        raise PermissionError("401 unauthorized")

    rejected = asyncio.run(evaluate_ragas(dataset, rows, evaluator=unauthorized, max_retries=0))
    assert rejected.status == "failed" and "PermissionError" in (rejected.error or "")

    async def malformed(*args, **kwargs):
        return [{"sample_id": "q-0", "context_precision": "not-a-float"}]

    invalid = asyncio.run(evaluate_ragas(dataset, rows, evaluator=malformed, max_retries=0))
    assert invalid.status == "failed" and "ValueError" in (invalid.error or "")


def test_ragas_skips_provider_when_generation_response_is_missing():
    dataset = GoldenDataset(
        benchmark_version="v", embedding_model="e",
        queries=[query(query_id=f"q-{index}") for index in range(100)],
    )
    observation = RetrievalObservation(
        sample_id="q-0", query="RAG", corpus_version="v", status="published",
        retrieved_contexts=["context"], retrieved_context_ids=["ctx"],
    )

    result = asyncio.run(evaluate_ragas_from_observations(
        dataset, [observation], responses={"q-0": ""},
    ))

    assert result.status == "failed"
    assert result.error == "generation_response_missing:1"
    assert result.samples[0].error == "generation_response_missing"
    assert all(value is None for value in result.metrics.values())


def test_ragas_audit_groups_canonical_scores_by_scenario():
    dataset = GoldenDataset(
        benchmark_version="v", embedding_model="e",
        queries=[query(query_id=f"q-{index}", scenario_type="url" if index == 1 else "stable_technical") for index in range(100)],
    )

    async def evaluator(*args, **kwargs):
        return [
            {"sample_id": "q-0", "context_precision": 1, "context_recall": 1, "faithfulness": 1, "answer_relevancy": 1},
            {"sample_id": "q-1", "context_precision": 0.5, "context_recall": 0.5, "faithfulness": 0.5, "answer_relevancy": 0.5},
        ]

    result = asyncio.run(evaluate_ragas(dataset, [{"sample_id": "q-0"}, {"sample_id": "q-1"}], evaluator=evaluator, max_retries=0))
    assert result.status == "success"
    assert result.evaluated_at
    assert result.scenario_metrics["stable_technical"]["faithfulness"] == 1.0
    assert result.scenario_metrics["url"]["answer_relevancy"] == 0.5
    assert all(sample.scenario_type in {"stable_technical", "url"} for sample in result.samples)


def test_ragas_uses_async_collection_scorers():
    dataset = GoldenDataset(
        benchmark_version="v", embedding_model="e",
        queries=[query(query_id=f"q-{index}") for index in range(100)],
    )
    captured = []

    class Result:
        value = 1.0

    class Metric:
        def __init__(self, name):
            self.name = name

        async def ascore(self, user_input="", response="", reference="", retrieved_contexts=None):
            captured.append((self.name, user_input, response, reference, retrieved_contexts))
            return Result()

    metrics = [Metric(name) for name in (
        "context_precision", "context_recall", "faithfulness", "answer_relevancy",
    )]
    result = asyncio.run(evaluate_ragas(
        dataset,
        [{"sample_id": "q-0", "user_input": "RAG", "response": "answer",
          "reference": "reference", "retrieved_contexts": ["context"]}],
        llm=object(), embeddings=object(), metrics=metrics, concurrency=3,
        max_retries=0,
    ))

    assert result.status == "success"
    assert {item[0] for item in captured} == {
        "context_precision", "context_recall", "faithfulness", "answer_relevancy",
    }
    assert all(item[1:] == ("RAG", "answer", "reference", ["context"]) for item in captured)


def test_comparison_uses_configured_regression_thresholds():
    baseline = {
        "metadata": {"top_k": 5, "comparison_thresholds": {"quality": 0.02, "latency_ms": 5}},
        "dataset": {"benchmark_version": "v"}, "retrieval": {"metrics": {"hit_at_5": 0.90, "p95_latency_ms": 20}},
        "samples": [], "gates": {"passed": True},
    }
    within_budget = {**baseline, "retrieval": {"metrics": {"hit_at_5": 0.89, "p95_latency_ms": 24}}}
    regressed = {**baseline, "retrieval": {"metrics": {"hit_at_5": 0.85, "p95_latency_ms": 30}}}
    assert compare_evaluation_payloads(baseline, within_budget)["regressions"] == []
    result = compare_evaluation_payloads(baseline, regressed)
    assert set(result["regressions"]) == {"hit_at_5", "p95_latency_ms"}
    assert result["regression_details"]["hit_at_5"]["threshold"] == 0.02


def test_deterministic_metrics_cover_duplicate_role_contamination_and_percentiles():
    item = BenchmarkQuery.model_validate(query(role="backend"))
    result = QueryEvaluation(query=item, latency_ms=30, hits=[
        {"parent_id": "ctx", "content_hash": "same", "role_tags": ["backend"], "source_name": "docs", "parent_recovered": True, "text": "RAG retrieves evidence before generation."},
        {"parent_id": "other", "content_hash": "same", "role_tags": ["frontend"], "source_name": "docs", "parent_recovered": True, "text": "unrelated"},
    ])
    metrics = calculate_metrics([result], 5)
    assert metrics["duplicate_result_rate"] == 0.5
    assert metrics["role_contamination_rate"] == 0.5
    assert metrics["p50_latency_ms"] == metrics["p95_latency_ms"] == 30


def test_duplicate_metric_detects_multiple_child_hits_from_same_parent():
    item = BenchmarkQuery.model_validate(query(role="backend"))
    result = QueryEvaluation(query=item, latency_ms=1, hits=[
        {"parent_id": "same-parent", "content_hash": "child-a", "role_tags": ["backend"]},
        {"parent_id": "same-parent", "content_hash": "child-b", "role_tags": ["backend"]},
    ])

    assert calculate_metrics([result], 5)["duplicate_result_rate"] == 0.5


def test_agent_aggregation_tracks_process_efficiency_and_risk_denominators():
    passing = evaluate_agent_trace(AgentTrace(sample_id="a", route="public_milvus_search", completed=True, answer="ok", total_latency_ms=10, token_usage={"total": 8}, estimated_cost_cny=0.012, retry_count=1, tool_calls=[ToolCallObservation(name="public_milvus_search")]), "public_milvus_search", ["public_milvus_search"])
    failed = evaluate_agent_trace(AgentTrace(sample_id="b", route="base_model", completed=False, total_latency_ms=50, retry_count=4, policy_findings=["private_scope_violation:tavily_search"]), "personal_milvus_search", ["personal_milvus_search"])
    metrics = aggregate_agent_evaluations([passing, failed])
    assert metrics["agent_task_completion_rate"] == 0.5
    assert metrics["agent_total_retry_count"] == 5
    assert metrics["private_kb_violation_rate"] == 0.5
    assert metrics["high_risk_false_allow_rate"] == 0.0
    assert metrics["agent_mean_estimated_cost_cny"] == pytest.approx(0.012)
    assert metrics["agent_cost_observed_rate"] == 0.5


def test_production_adapter_preserves_sanitized_agent_event_contract():
    captured = {}
    async def fake_agent(*args, **kwargs):
        captured["user_id"] = kwargs.get("user_id")
        return {
            "route": "public_milvus_search", "done": True, "completed": True, "evidence": [{"text": "evidence", "source_type": "public_kb", "corpus_version": "v"}],
            "trace_events": [{"name": "public_milvus_search", "arguments": {"query_length": 12, "role": "backend"}, "duration_ms": 3, "status": "success", "result_count": 1}],
            "total_latency_ms": 4, "candidate_count": 1, "filtered_count": 1, "confidence": 0.9, "coverage": 1.0,
        }
    adapter = ProductionEvaluationAdapter(InMemoryCorpusStore(), corpus_version="v", agent_runner=fake_agent)
    trace = adapter.agent_trace(query=BenchmarkQuery.model_validate(query()), observation=None)
    assert trace.completed and trace.tool_calls[0].arguments == {"query_length": 12, "role": "backend"}
    assert "What is RAG" not in trace.model_dump_json()
    assert captured["user_id"] == 0


def test_production_generation_uses_evaluation_identity_for_public_rag():
    captured = {}

    class UnsupportedOutput:
        supported = False
        quiz = None
        message = "test stop"

    class Generator:
        async def generate(self, request, user_id=None):
            captured["user_id"] = user_id
            captured["topic"] = request.user_input
            return UnsupportedOutput()

    adapter = ProductionEvaluationAdapter(
        InMemoryCorpusStore(), corpus_version="v",
        evaluation_user_id=0, quiz_generator_factory=Generator,
    )
    observation = adapter.generate(query=BenchmarkQuery.model_validate(query()), observation=None)

    assert captured == {"user_id": 0, "topic": "What is RAG?"}
    assert observation.error == "test stop"


def test_pipeline_registry_stores_auditable_report_summary(tmp_path):
    store = InMemoryCorpusStore()
    record = {"document_id": "doc", "parent_id": "ctx", "corpus_version": "v", "status": "published", "chunk_id": "chunk", "role_tags": ["backend"], "source_name": "docs", "text": "RAG retrieves evidence before generation.", "embedding_text": "RAG retrieves evidence before generation."}
    store.upsert([record])
    dataset_path = tmp_path / "golden.yaml"
    import yaml
    dataset_path.write_text(yaml.safe_dump({"benchmark_version": "v", "embedding_model": "e", "queries": [query(query_id=f"q-{i}") for i in range(100)]}, allow_unicode=True), encoding="utf-8")
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime"), store=store)
    payload = pipeline.evaluate_full(dataset_path, "v", output=tmp_path / "evaluation.json")
    summary = pipeline.registry.evaluation("v")
    assert payload["report_path"] and summary["path"] == payload["report_path"]
    assert summary["sha256"] and summary["markdown_path"].endswith(".md")
