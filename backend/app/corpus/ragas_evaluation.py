"""Optional RAGAS adapter used only by offline evaluation commands.

The import is intentionally deferred so the FastAPI service has no dependency
on RAGAS and can start with the normal production install.
"""
from __future__ import annotations

import asyncio
import inspect
import time
import logging
from datetime import UTC, datetime
from typing import Any, Callable, Iterable

from app.corpus.evaluation import GoldenDataset, RagasEvaluationReport, RagasMetricResult

logger = logging.getLogger(__name__)


def _import_ragas_components() -> tuple[Any, Any, Any, Any, Any, Any]:
    """Import RAGAS while tolerating optional Vertex AI integrations.

    RAGAS 0.4.x imports the legacy ``langchain_community`` Vertex modules at
    package import time, although EasyOffer uses the OpenAI-compatible
    DashScope client and never instantiates Vertex AI.  Newer
    langchain-community releases removed those modules.  Registering tiny
    marker classes keeps the optional evaluator importable without adding a
    Vertex dependency or changing the production runtime.
    """
    import sys
    import types

    try:
        import langchain_community.chat_models.vertexai  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        module = types.ModuleType("langchain_community.chat_models.vertexai")
        module.ChatVertexAI = type("ChatVertexAI", (), {})
        sys.modules[module.__name__] = module
    try:
        import langchain_community.llms as llms  # type: ignore
        if not hasattr(llms, "VertexAI"):
            llms.VertexAI = type("VertexAI", (), {})
    except ModuleNotFoundError:
        module = types.ModuleType("langchain_community.llms")
        module.VertexAI = type("VertexAI", (), {})
        sys.modules[module.__name__] = module
    from ragas import EvaluationDataset, SingleTurnSample
    from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness
    return EvaluationDataset, SingleTurnSample, AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness


def build_dashscope_components(*, api_key: str | None = None, model: str = "qwen-plus",
    embedding_model: str = "text-embedding-v4", base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
                               timeout: float = 180.0, max_retries: int = 1) -> tuple[Any, Any]:
    """Build modern RAGAS clients over DashScope's OpenAI-compatible API."""
    from app.core.config import get_settings
    settings = get_settings()
    key = api_key or settings.dashscope_api_key or settings.embedding_api_key
    if not key:
        raise RuntimeError("dashscope_api_key_missing")
    from openai import AsyncOpenAI
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory

    client = AsyncOpenAI(
        api_key=key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
    )
    llm = llm_factory(
        model,
        provider="openai",
        client=client,
        temperature=0,
        max_tokens=4096,
    )
    embeddings = embedding_factory(
        "openai",
        model=embedding_model,
        client=client,
        interface="modern",
    )
    # Preserve stable, auditable provider names across RAGAS wrapper versions.
    setattr(llm, "model_name", model)
    setattr(embeddings, "model_name", embedding_model)
    return llm, embeddings


def _metric_name(metric: Any) -> str:
    name = str(getattr(metric, "name", None) or getattr(metric, "__name__", "metric")).lower().replace(" ", "_")
    aliases = {
        "context_precision": "context_precision",
        "context_recall": "context_recall",
        "faithfulness": "faithfulness",
        "answer_relevancy": "answer_relevancy",
        "answer_relevance": "answer_relevancy",
        "answer_relevancy_proxy": "answer_relevancy_proxy",
        "answer_relevance_proxy": "answer_relevancy_proxy",
    }
    return aliases.get(name, name)


_CANONICAL_METRICS = {"context_precision", "context_recall", "faithfulness", "answer_relevancy"}


def _model_name(value: Any) -> str | None:
    if value is None:
        return None
    return (getattr(value, "model_name", None) or getattr(value, "model", None)
            or getattr(value, "model_id", None))


def _records(result: Any) -> list[dict[str, Any]]:
    """Normalize RAGAS EvaluationResult/DataFrame/mapping to records."""
    if hasattr(result, "to_pandas"):
        result = result.to_pandas()
    if hasattr(result, "to_dict"):
        try:
            result = result.to_dict("records")
        except TypeError:
            result = result.to_dict()
    if isinstance(result, dict):
        # A dict of columns is common for dataframe-like stubs.
        if result and all(isinstance(value, (list, tuple)) for value in result.values()):
            keys = list(result)
            return [{key: result[key][index] for key in keys} for index in range(max(len(result[key]) for key in keys))]
        return [result]
    return [item for item in (result or []) if isinstance(item, dict)]


async def evaluate_ragas(
    dataset: GoldenDataset,
    samples: Iterable[dict[str, Any]],
    *,
    llm: Any = None,
    embeddings: Any = None,
    metrics: list[Any] | None = None,
    evaluator: Callable[..., Any] | None = None,
    timeout_seconds: float = 3600.0,
    metric_timeout_seconds: float = 240.0,
    max_retries: int = 1,
    concurrency: int = 4,
) -> RagasEvaluationReport:
    """Evaluate samples through RAGAS Collections API.

    ``evaluator`` is injectable for tests. In production the adapter uses the
    RAGAS 0.4 Collections scorers directly.  This avoids mixing the modern
    ``ragas.metrics.collections`` objects with the legacy batch evaluator.
    """
    started = time.perf_counter()
    rows = list(samples)
    scenario_by_id = {query.query_id: query.scenario_type for query in dataset.queries}
    requested_metric_names = [_metric_name(item) for item in metrics] if metrics is not None else []
    model_name = _model_name(llm)
    embedding_name = _model_name(embeddings)
    try:
        if evaluator is None:
            try:
                EvaluationDataset, SingleTurnSample, AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness = _import_ragas_components()
            except ImportError as exc:
                return RagasEvaluationReport(status="unavailable", error=f"ragas_not_installed:{exc}", elapsed_ms=(time.perf_counter() - started) * 1000)
            if llm is None or embeddings is None:
                built_llm, built_embeddings = build_dashscope_components()
                llm = llm or built_llm
                embeddings = embeddings or built_embeddings
                model_name = _model_name(llm)
                embedding_name = _model_name(embeddings)
            metrics = metrics or [
                ContextPrecision(llm=llm),
                ContextRecall(llm=llm),
                Faithfulness(llm=llm),
                AnswerRelevancy(llm=llm, embeddings=embeddings),
            ]
            ragas_rows = [SingleTurnSample(
                user_input=str(row.get("user_input") or row.get("query") or ""),
                retrieved_contexts=[str(value) for value in row.get("retrieved_contexts", [])],
                reference=str(row.get("reference") or row.get("reference_answer") or ""),
                response=str(row.get("response") or row.get("answer") or ""),
            ) for row in rows]
            # Construct the official dataset as a schema/contract check, then
            # execute the Collections metrics via their async scorer methods.
            evaluation_dataset = EvaluationDataset(samples=ragas_rows)
            semaphore = asyncio.Semaphore(max(1, int(concurrency)))

            async def score(metric: Any, sample: Any) -> float:
                name = _metric_name(metric)
                kwargs = {
                    "user_input": sample.user_input,
                    "response": sample.response,
                    "reference": sample.reference,
                    "retrieved_contexts": sample.retrieved_contexts,
                }
                accepted = set(inspect.signature(metric.ascore).parameters)
                kwargs = {key: value for key, value in kwargs.items() if key in accepted}
                last_error: Exception | None = None
                for attempt in range(max(0, int(max_retries)) + 1):
                    try:
                        async with semaphore:
                            value = await asyncio.wait_for(
                                metric.ascore(**kwargs),
                                timeout=max(1.0, float(metric_timeout_seconds)),
                            )
                        raw_value = getattr(value, "value", value)
                        return float(raw_value)
                    except Exception as exc:
                        last_error = exc
                        if attempt < max_retries:
                            await asyncio.sleep(min(2 ** attempt, 4))
                assert last_error is not None
                raise RuntimeError(f"{name}:{type(last_error).__name__}:{last_error}") from last_error

            async def score_sample(index: int, sample: Any) -> dict[str, Any]:
                output: dict[str, Any] = {
                    "sample_id": str(rows[index].get("sample_id") or rows[index].get("query_id") or index),
                    "user_input": sample.user_input,
                }
                results = await asyncio.gather(
                    *(score(metric, sample) for metric in metrics or []),
                    return_exceptions=True,
                )
                for metric, value in zip(metrics or [], results):
                    name = _metric_name(metric)
                    # ``asyncio.CancelledError`` is a BaseException on modern
                    # Python. Preserve it as a failed metric instead of trying
                    # to coerce it to float and losing the provider cause.
                    if isinstance(value, BaseException):
                        output[f"{name}_error"] = f"{type(value).__name__}: {value}"
                    else:
                        output[name] = value
                return output

            result = await asyncio.wait_for(
                asyncio.gather(*(
                    score_sample(index, sample)
                    for index, sample in enumerate(evaluation_dataset.samples)
                )),
                timeout=timeout_seconds,
            )
        else:
            async def invoke_injected() -> Any:
                kwargs = {"metrics": metrics, "llm": llm, "embeddings": embeddings,
                          "concurrency": max(1, int(concurrency))}
                try:
                    value = evaluator(rows, **kwargs)
                except TypeError as exc:
                    if "concurrency" not in str(exc):
                        raise
                    kwargs.pop("concurrency", None)
                    value = evaluator(rows, **kwargs)
                return await value if asyncio.iscoroutine(value) else value
            last_error = None
            result = None
            for attempt in range(max(0, max_retries) + 1):
                try:
                    result = await asyncio.wait_for(invoke_injected(), timeout=timeout_seconds)
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < max_retries:
                        await asyncio.sleep(min(2 ** attempt, 4))
            if result is None and last_error:
                raise last_error

        # EvaluationResult behaves like a mapping/dataframe depending on the
        # RAGAS version. Convert it to rows without assuming one concrete type.
        result_rows = _records(result)
        names = [_metric_name(item) for item in (metrics or [])]
        if not names and result_rows:
            names = [_metric_name(type("Metric", (), {"name": name})()) for name in result_rows[0]
                     if str(name).lower() not in {"sample_id", "user_input", "response", "reference", "retrieved_contexts"}]
        # A complete RAGAS run always has the same four contractual metrics.
        # Test-only/injected evaluators are held to that contract too.
        names = list(_CANONICAL_METRICS)
        # Only canonical RAGAS metrics belong in the generation-quality
        # section.  In particular, a retrieval proxy must never fill the
        # authoritative Answer Relevancy field.
        names = [name for name in dict.fromkeys(names) if name in _CANONICAL_METRICS]
        by_sample_id = {str(item.get("sample_id")): item for item in result_rows if item.get("sample_id") is not None}
        by_input: dict[str, list[dict[str, Any]]] = {}
        for item in result_rows:
            if item.get("user_input") is not None:
                by_input.setdefault(str(item.get("user_input")), []).append(item)
        per_sample: list[RagasMetricResult] = []
        for index, row in enumerate(rows):
            sample_id = str(row.get("sample_id") or row.get("query_id") or index)
            raw = by_sample_id.get(sample_id)
            if raw is None:
                matches = by_input.get(str(row.get("user_input") or row.get("query") or ""), [])
                raw = matches.pop(0) if matches else (result_rows[index] if index < len(result_rows) else None)
            raw = raw if isinstance(raw, dict) else {}
            scores = {name: (float(raw[name]) if raw.get(name) is not None else None) for name in names if name in raw}
            missing = [name for name in names if name not in scores or scores[name] is None]
            metric_errors = [str(raw[f"{name}_error"]) for name in missing if raw.get(f"{name}_error")]
            error = None
            if missing:
                error = "missing_metrics:" + ",".join(missing)
                if metric_errors:
                    error += "; provider_errors=" + " | ".join(metric_errors)
            per_sample.append(RagasMetricResult(sample_id=sample_id,
                status="success" if not missing else "failed", scores=scores,
                error=error,
                model=model_name, embedding_model=embedding_name,
                scenario_type=scenario_by_id.get(sample_id, "unknown")))
        aggregate: dict[str, float | None] = {}
        for name in names:
            values = [item.scores[name] for item in per_sample if item.scores.get(name) is not None]
            aggregate[name] = sum(values) / len(values) if values else None
        complete = bool(per_sample) and all(item.status == "success" for item in per_sample)
        status = "success" if complete and all(aggregate.get(name) is not None for name in _CANONICAL_METRICS if name in names) else "partial"
        scenario_metrics: dict[str, dict[str, float | None]] = {}
        for scenario in sorted({item.scenario_type for item in per_sample}):
            members = [item for item in per_sample if item.scenario_type == scenario]
            scenario_metrics[scenario] = {
                name: (sum(float(item.scores[name]) for item in members if item.scores.get(name) is not None)
                       / len([item for item in members if item.scores.get(name) is not None]))
                if any(item.scores.get(name) is not None for item in members) else None
                for name in _CANONICAL_METRICS
            }
        return RagasEvaluationReport(status=status, metrics=aggregate, samples=per_sample,
            elapsed_ms=(time.perf_counter() - started) * 1000, model=model_name,
            embedding_model=embedding_name,
            evaluated_at=datetime.now(UTC).isoformat(), scenario_metrics=scenario_metrics,
            error=None if status == "success" else "one_or_more_samples_or_metrics_failed")
    except Exception as exc:
        return RagasEvaluationReport(status="failed", metrics={}, samples=[], error=f"{type(exc).__name__}: {exc}", elapsed_ms=(time.perf_counter() - started) * 1000, model=model_name, embedding_model=embedding_name)


async def evaluate_ragas_from_observations(dataset: GoldenDataset, observations: Iterable[Any], *, responses: dict[str, str] | None = None, **kwargs: Any) -> RagasEvaluationReport:
    references = {query.query_id: query.reference_answer for query in dataset.queries}
    rows = []
    missing: list[RagasMetricResult] = []
    response_map = responses or {}
    for item in observations:
        sample_id = str(getattr(item, "sample_id", ""))
        response = str(response_map.get(sample_id, getattr(item, "response", "")) or "").strip()
        if not response:
            missing.append(RagasMetricResult(
                sample_id=sample_id,
                status="failed",
                scores={},
                error="generation_response_missing",
                scenario_type=next((
                    query.scenario_type for query in dataset.queries
                    if query.query_id == sample_id
                ), "unknown"),
            ))
            continue
        rows.append({
            "sample_id": sample_id,
            "user_input": getattr(item, "query", ""),
            "retrieved_contexts": getattr(item, "retrieved_contexts", []),
            "reference_answer": references.get(sample_id, ""),
            "response": response,
        })
    if not rows:
        return RagasEvaluationReport(
            status="failed",
            metrics={name: None for name in _CANONICAL_METRICS},
            samples=missing,
            error=f"generation_response_missing:{len(missing)}",
            evaluated_at=datetime.now(UTC).isoformat(),
        )
    result = await evaluate_ragas(dataset, rows, **kwargs)
    if missing:
        result.samples.extend(missing)
        result.status = "partial"
        suffix = f"generation_response_missing:{len(missing)}"
        result.error = f"{result.error}; {suffix}" if result.error else suffix
    return result
