"""Resumable production generation + batched RAGAS evaluation.

Every generated sample and every RAGAS batch is persisted before continuing.
The command can therefore be interrupted and safely resumed without repeating
completed DeepSeek calls.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from app.corpus.evaluation import load_golden_dataset
from app.corpus.evaluation_runner import ProductionEvaluationAdapter
from app.corpus.ragas_evaluation import evaluate_ragas_from_observations
from app.corpus.storage import MilvusCorpusStore


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_dump(value), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _observation_from_json(raw: dict[str, Any]):
    from app.corpus.evaluation import RetrievalObservation

    return RetrievalObservation.model_validate(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", default="corpus/benchmarks/golden-v3.yaml")
    parser.add_argument("--corpus-version", default="full-authorized-v1")
    parser.add_argument("--state-dir", default="data/public-corpus/evaluations/golden-v3-resumable")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--metric-timeout", type=float, default=90.0)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--generation-retries", type=int, default=3)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    state = Path(args.state_dir)
    state.mkdir(parents=True, exist_ok=True)
    dataset = load_golden_dataset(args.benchmark)
    store = MilvusCorpusStore()
    adapter = ProductionEvaluationAdapter(
        store, corpus_version=args.corpus_version, status="published", top_k=dataset.top_k,
    )

    observations_path = state / "observations.json"
    generations_path = state / "generations.json"
    observations: dict[str, dict[str, Any]] = _load_json(observations_path) if observations_path.exists() else {}
    generations: dict[str, dict[str, Any]] = _load_json(generations_path) if generations_path.exists() else {}

    # Retrieval and generation checkpoints are written after each sample.
    for index, query in enumerate(dataset.queries, start=1):
        if query.query_id not in observations:
            observation = adapter.retrieve(query)
            observations[query.query_id] = _dump(observation)
            _write_json(observations_path, observations)
        else:
            observation = _observation_from_json(observations[query.query_id])
        if query.query_id not in generations or generations[query.query_id].get("error"):
            generation = None
            for attempt in range(max(0, int(args.generation_retries)) + 1):
                generation = adapter.generate(query=query, observation=observation)
                if not getattr(generation, "error", None):
                    break
                if attempt < max(0, int(args.generation_retries)):
                    logging.warning("generation retry sample=%s attempt=%s error=%s", query.query_id, attempt + 1, generation.error)
                    import time
                    time.sleep(min(2 ** attempt, 8))
            assert generation is not None
            generations[query.query_id] = _dump(generation)
            _write_json(generations_path, generations)
        if index == 1 or index % 5 == 0 or index == len(dataset.queries):
            logging.info("generation checkpoint %s/%s", index, len(dataset.queries))

    # RAGAS is evaluated in resumable batches. A failed batch is retained as a
    # JSON error record and can be retried by deleting only that batch file.
    batch_dir = state / "ragas_batches"
    batch_dir.mkdir(exist_ok=True)
    batch_size = max(1, int(args.batch_size))
    for start in range(0, len(dataset.queries), batch_size):
        batch_index = start // batch_size
        batch_path = batch_dir / f"batch-{batch_index:03d}.json"
        if batch_path.exists():
            # A persisted error record is a retry marker, not a completed
            # checkpoint.  Only skip batches that contain the full sample
            # result set and have a successful status; otherwise retry the
            # batch on the next invocation.
            try:
                existing = _load_json(batch_path)
            except (OSError, json.JSONDecodeError):
                existing = {}
            if existing.get("status") == "success" and len(existing.get("samples", [])) == len(dataset.queries[start : start + batch_size]):
                continue
            batch_path.unlink(missing_ok=True)
        queries = dataset.queries[start : start + batch_size]
        batch_dataset = dataset.model_copy(update={"queries": queries})
        batch_observations = [_observation_from_json(observations[q.query_id]) for q in queries]
        responses = {
            q.query_id: str(generations[q.query_id].get("response") or "")
            for q in queries
        }
        try:
            result = asyncio.run(evaluate_ragas_from_observations(
                batch_dataset,
                batch_observations,
                responses=responses,
                timeout_seconds=max(120.0, float(args.metric_timeout) * 4),
                metric_timeout_seconds=max(10.0, float(args.metric_timeout)),
                max_retries=1,
                concurrency=max(1, int(args.concurrency)),
            ))
            _write_json(batch_path, result)
            logging.info("RAGAS batch %s complete status=%s", batch_index, result.status)
        except Exception as exc:
            _write_json(batch_path, {"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            logging.exception("RAGAS batch %s failed", batch_index)

    # Aggregate only completed result objects. The aggregate is written last,
    # and never replaces a missing/failed batch with a fabricated score.
    batch_results = []
    for path in sorted(batch_dir.glob("batch-*.json")):
        raw = _load_json(path)
        if raw.get("status") in {"success", "partial", "failed"} and "samples" in raw:
            batch_results.append(raw)
    sample_rows = [sample for result in batch_results for sample in result.get("samples", [])]
    metric_names = ("context_precision", "context_recall", "faithfulness", "answer_relevancy")
    metrics = {}
    for name in metric_names:
        values = [float(sample["scores"][name]) for sample in sample_rows if sample.get("scores", {}).get(name) is not None]
        metrics[name] = sum(values) / len(values) if values else None
    failed_samples = [sample for sample in sample_rows if sample.get("status") != "success"]
    payload = {
        "status": "success" if len(sample_rows) == len(dataset.queries) and not failed_samples else "partial",
        "benchmark_version": dataset.benchmark_version,
        "sample_count": len(dataset.queries),
        "evaluated_sample_count": len(sample_rows),
        "failed_sample_count": len(failed_samples),
        "metrics": metrics,
        "samples": sample_rows,
    }
    _write_json(state / "ragas-summary.json", payload)
    print(json.dumps({k: payload[k] for k in ("status", "sample_count", "evaluated_sample_count", "failed_sample_count", "metrics")}, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
