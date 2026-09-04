"""Run one real production quiz generation followed by all RAGAS metrics."""
from __future__ import annotations

import asyncio
import json
import sys

from app.corpus.evaluation import load_golden_dataset
from app.corpus.evaluation_runner import ProductionEvaluationAdapter
from app.corpus.ragas_evaluation import evaluate_ragas_from_observations
from app.corpus.storage import MilvusCorpusStore


def main() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    dataset = load_golden_dataset("corpus/benchmarks/golden-v2.yaml")
    sample = dataset.model_copy(update={"queries": dataset.queries[:1]})
    query = sample.queries[0]
    adapter = ProductionEvaluationAdapter(
        MilvusCorpusStore(),
        corpus_version="full-authorized-v1",
        status="published",
        top_k=sample.top_k,
        evaluation_user_id=0,
    )
    observation = adapter.retrieve(query)
    generation = adapter.generate(query=query, observation=observation)
    if generation.error:
        print(json.dumps({
            "status": "failed",
            "stage": "generation",
            "sample_id": query.query_id,
            "error": generation.error,
        }, ensure_ascii=False, indent=2))
        return
    result = asyncio.run(evaluate_ragas_from_observations(
        sample,
        [observation],
        responses={query.query_id: generation.response},
        timeout_seconds=1200,
        metric_timeout_seconds=240,
        max_retries=1,
        concurrency=4,
    ))
    print(json.dumps({
        "status": result.status,
        "sample_id": query.query_id,
        "generation_latency_ms": generation.latency_ms,
        "response_chars": len(generation.response),
        "evidence_meta": generation.quiz.get("evidence_meta", {}) if generation.quiz else {},
        "ragas": result.model_dump(mode="json"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
