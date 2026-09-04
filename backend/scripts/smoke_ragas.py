"""Run one real Milvus + DashScope/RAGAS sample without generating a release report."""
from __future__ import annotations

import asyncio

from app.corpus.evaluation import load_golden_dataset
from app.corpus.evaluation_runner import OfflineEvaluationRunner
from app.corpus.ragas_evaluation import evaluate_ragas_from_observations
from app.corpus.storage import MilvusCorpusStore


def main() -> None:
    dataset = load_golden_dataset("corpus/benchmarks/golden-v2.yaml")
    sample = dataset.model_copy(update={"queries": dataset.queries[:1]})
    runner = OfflineEvaluationRunner(
        MilvusCorpusStore(),
        corpus_version="full-authorized-v1",
        status="published",
        top_k=sample.top_k,
    )
    observations = runner.run(sample)
    # This is intentionally the Golden reference rather than a production
    # answer: the smoke command verifies evaluator connectivity only and never
    # writes a release-quality report.
    responses = {sample.queries[0].query_id: sample.queries[0].reference_answer}
    result = asyncio.run(evaluate_ragas_from_observations(
        sample,
        observations,
        responses=responses,
        timeout_seconds=600,
        max_retries=0,
        concurrency=4,
    ))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
