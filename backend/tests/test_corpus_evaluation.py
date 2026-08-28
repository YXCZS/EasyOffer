from __future__ import annotations

import pytest
import yaml

from app.corpus.evaluation import (
    load_benchmark,
    BenchmarkQuery,
    EvaluationReport,
    QueryEvaluation,
    calculate_metrics,
    compare_reports,
    enforce_gate,
    evaluate_store,
)
from app.corpus.quality import review_records
from app.corpus.config import CorpusConfig
from app.corpus.storage import InMemoryCorpusStore


def test_ranking_metrics_match_hand_calculated_fixture():
    queries = [
        QueryEvaluation(
            query=BenchmarkQuery(
                query_id="q1", topic="Redis", query="RDB 与 AOF", role="backend",
                difficulty="medium", expected_technologies=["Redis"],
                relevance={"p1": 2, "p2": 1}, expected_knowledge_points=["持久化"],
            ),
            hits=[
                {"parent_id": "p0", "content_hash": "a", "role_tags": "|backend|", "source_name": "x", "parent_recovered": True},
                {"parent_id": "p1", "content_hash": "b", "role_tags": "|backend|", "source_name": "x", "parent_recovered": True},
                {"parent_id": "p2", "content_hash": "c", "role_tags": "|backend|", "source_name": "x", "parent_recovered": True},
            ],
            latency_ms=20,
        )
    ]

    metrics = calculate_metrics(queries, top_k=5)

    assert metrics["hit_at_5"] == 1.0
    assert metrics["mrr_at_5"] == 0.5
    assert metrics["ndcg_at_5"] == pytest.approx(0.6590018)
    assert metrics["source_traceability_rate"] == 1.0
    assert metrics["parent_recovery_rate"] == 1.0


def test_ndcg_does_not_double_count_chunks_from_same_relevant_document():
    query = BenchmarkQuery(
        query_id="q1", topic="Redis", query="Redis 持久化", role="backend",
        difficulty="medium", expected_technologies=["Redis"],
        relevance={"redis-doc": 2}, expected_knowledge_points=["RDB", "AOF"],
    )
    result = QueryEvaluation(
        query=query,
        hits=[
            {"document_id": "redis-doc", "parent_id": f"parent-{index}", "content_hash": f"h{index}"}
            for index in range(5)
        ],
        latency_ms=1,
    )

    metrics = calculate_metrics([result], top_k=5)

    assert metrics["ndcg_at_5"] == pytest.approx(1.0)
    assert 0.0 <= metrics["ndcg_at_5"] <= 1.0


def test_gate_blocks_failed_metric_without_explicit_override():
    report = EvaluationReport(
        corpus_version="candidate", benchmark_version="pilot-v1", top_k=5,
        metrics={
            "hit_at_5": 0.8, "mrr_at_5": 0.8, "ndcg_at_5": 0.8,
            "role_contamination_rate": 0.0, "duplicate_result_rate": 0.0,
            "parent_recovery_rate": 1.0, "source_traceability_rate": 1.0,
        },
        queries=[],
    )

    gate = enforce_gate(report)

    assert gate.passed is False
    assert "hit_at_5" in gate.failed_metrics


def test_gate_blocks_incomplete_answers():
    report = EvaluationReport(
        corpus_version="candidate", benchmark_version="pilot-v1", top_k=5,
        metrics={
            "hit_at_5": 1.0, "mrr_at_5": 1.0, "ndcg_at_5": 1.0,
            "role_contamination_rate": 0.0, "duplicate_result_rate": 0.0,
            "parent_recovery_rate": 1.0, "source_traceability_rate": 1.0,
            "answer_integrity_rate": 0.8,
        },
        queries=[],
    )

    gate = enforce_gate(report)

    assert gate.passed is False
    assert "answer_integrity_rate" in gate.failed_metrics


def test_regression_comparison_lists_degraded_metrics():
    current = EvaluationReport(corpus_version="v1", benchmark_version="b1", top_k=5, metrics={"hit_at_5": 0.9, "p95_latency_ms": 20}, queries=[])
    candidate = EvaluationReport(corpus_version="v2", benchmark_version="b1", top_k=5, metrics={"hit_at_5": 0.8, "p95_latency_ms": 40}, queries=[])

    comparison = compare_reports(current, candidate)

    assert comparison["metric_deltas"]["hit_at_5"] == pytest.approx(-0.1)
    assert "hit_at_5" in comparison["regressions"]
    assert "p95_latency_ms" in comparison["regressions"]


def test_answer_missing_only_flags_question_without_answer_text():
    base = {
        "chunk_id": "c1", "document_id": "d1", "document_version": "v1", "corpus_version": "c1",
        "parent_id": "p1", "technology": "Redis", "role_tags": ["backend"], "content_hash": "h1",
        "review_status": "pending", "status": "unpublished", "source_name": "docs",
        "parent_type": "question", "structure_confidence": 0.9,
    }
    complete = review_records([{**base, "text": "问题：RDB 和 AOF 有什么区别？答案：RDB 是快照，AOF 记录写命令。"}], CorpusConfig())
    missing = review_records([{**base, "text": "问题：RDB 和 AOF 有什么区别？"}], CorpusConfig())

    assert not any(issue.code == "answer_missing" for issue in complete.issues)
    assert any(issue.code == "answer_missing" for issue in missing.issues)


def test_answer_integrity_accepts_unlabelled_qa_parent_with_answer_body():
    from app.corpus.evaluation import _answer_integrity

    hit = {
        "parent_id": "p1",
        "parent_recovered": True,
        "parent_type": "qa",
        "source_name": "authorized PDF",
        "parent_text": "Redis 的 RDB 和 AOF 有什么区别？\nRDB 保存快照，AOF 记录写命令并支持重写。",
    }

    assert _answer_integrity(hit) is True


def test_answer_integrity_requires_exact_parent_answer_and_source():
    store = InMemoryCorpusStore()
    base = {
        "document_id": "redis-doc", "document_version": "7.4", "corpus_version": "candidate-v1",
        "parent_id": "redis-rdb", "technology": "Redis", "role_tags": ["backend"],
        "status": "unpublished", "source_name": "Redis docs", "content_hash": "h1",
        "embedding_text": "Redis RDB AOF persistence",
    }
    store.upsert([
        {**base, "chunk_id": "c1", "child_index": 0, "text": "问题：RDB 和 AOF 有什么区别？"},
        {**base, "chunk_id": "c2", "child_index": 1, "text": "答案：RDB 保存快照，AOF 记录写命令。", "content_hash": "h2"},
    ])
    source_benchmark = load_benchmark("corpus/benchmarks/pilot-v1.yaml")
    benchmark = source_benchmark.model_copy(update={"queries": [source_benchmark.queries[0]]})

    report = evaluate_store(store, benchmark, "candidate-v1")

    assert report.queries[0].answer_integrity is True
    assert report.queries[0].hits[0]["parent_recovered"] is True
    assert "答案：RDB 保存快照" in report.queries[0].hits[0]["parent_text"]


def test_pilot_benchmark_has_30_labeled_queries_across_three_domains():
    benchmark = load_benchmark("corpus/benchmarks/pilot-v1.yaml")

    assert len(benchmark.queries) == 30
    assert {query.topic for query in benchmark.queries} == {"Redis", "MySQL", "RAG/Milvus"}
    assert all(query.role and query.difficulty and query.relevance for query in benchmark.queries)
    assert all(query.expected_technologies and query.expected_knowledge_points for query in benchmark.queries)


def test_human_review_template_links_queries_and_chunks():
    payload = yaml.safe_load(open("corpus/reviews/pilot-v1.template.yaml", encoding="utf-8"))
    sample = payload["samples"][0]

    assert payload["sampling_strategy"] == ["high-score", "low-score", "boundary", "conflict"]
    for field in ("query_id", "chunk_id", "parent_id", "technical_correctness", "interview_value", "version_fitness", "source_quality"):
        assert field in sample
