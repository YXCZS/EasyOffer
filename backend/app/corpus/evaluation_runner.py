"""Offline adapters that observe the production RAG entry points.

The evaluation runner deliberately keeps metric calculation out of this
module.  Its only responsibility is to run the same retrieval, generation
and Agent boundaries used by EasyOffer and capture auditable observations.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Callable

from app.corpus.evaluation import (
    AgentTrace,
    BenchmarkQuery,
    GenerationObservation,
    GoldenDataset,
    RetrievalObservation,
    ToolCallObservation,
    _normalize_hit,
)


logger = logging.getLogger(__name__)


def _run_awaitable(value: Any) -> Any:
    """Resolve an async production boundary from the synchronous CLI job."""
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    raise RuntimeError("offline_evaluation_cannot_run_inside_active_event_loop")


class ProductionEvaluationAdapter:
    """Thin adapter over the real EasyOffer Agent and quiz-generator APIs.

    Public deterministic retrieval remains version-pinned through
    ``OfflineEvaluationRunner``.  Agent replay intentionally calls the
    production Agent graph rather than duplicating routing logic.  Since that
    graph reads the active public corpus, evidence is validated afterwards and
    any version contamination becomes a structured failed observation.
    """

    def __init__(
        self,
        store: Any,
        *,
        corpus_version: str,
        status: str = "published",
        top_k: int = 5,
        evaluation_user_id: int = 0,
        agent_runner: Callable[..., Any] | None = None,
        quiz_generator_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.store = store
        self.corpus_version = corpus_version
        self.status = status
        self.top_k = top_k
        self.evaluation_user_id = evaluation_user_id
        self.agent_runner = agent_runner
        self.quiz_generator_factory = quiz_generator_factory

    def retrieve(self, query: BenchmarkQuery) -> RetrievalObservation:
        return OfflineEvaluationRunner(
            self.store,
            corpus_version=self.corpus_version,
            status=self.status,
            top_k=self.top_k,
            user_id=query.user_id,
        ).retrieve(query)

    def generate(self, *, query: BenchmarkQuery, observation: RetrievalObservation | None = None) -> GenerationObservation:
        started = time.perf_counter()
        try:
            from app.models.quiz import QuizGenerateRequest
            from app.llm.deepseek import DeepSeekQuizGenerator

            generator = self.quiz_generator_factory() if self.quiz_generator_factory else DeepSeekQuizGenerator()
            effective_user_id = (
                int(query.user_id)
                if query.user_id is not None and str(query.user_id).isdigit()
                else self.evaluation_user_id
            )
            output = _run_awaitable(generator.generate(
                QuizGenerateRequest(user_input=query.query, role=query.role, difficulty=query.difficulty),
                user_id=effective_user_id,
            ))
            quiz = getattr(output, "quiz", None)
            if not getattr(output, "supported", False) or quiz is None:
                return GenerationObservation(
                    sample_id=query.query_id,
                    error=getattr(output, "message", None) or "production_generator_returned_no_quiz",
                )
            quiz_payload = quiz.model_dump(mode="json") if hasattr(quiz, "model_dump") else dict(quiz)
            # EasyOffer's production output is a quiz rather than a chat
            # answer.  Preserve its actual text as the RAGAS response; never
            # fabricate an answer from the Golden reference.
            question_text = "\n".join(
                "\n".join((
                    str(item.get("stem") or ""),
                    str(item.get("explanation") or ""),
                    str(item.get("knowledge_point") or ""),
                )) for item in quiz_payload.get("questions", [])
            )
            return GenerationObservation(
                sample_id=query.query_id,
                response="\n".join(filter(None, (str(quiz_payload.get("summary") or ""), question_text))),
                quiz=quiz_payload,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:
            return GenerationObservation(
                sample_id=query.query_id,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

    def agent_trace(self, *, query: BenchmarkQuery, observation: RetrievalObservation | None = None) -> AgentTrace:
        started = time.perf_counter()
        try:
            if self.agent_runner is None:
                from app.research.agentic_graph import run_agentic_rag
                runner = run_agentic_rag
            else:
                runner = self.agent_runner
            effective_user_id = (
                int(query.user_id)
                if query.user_id is not None and str(query.user_id).isdigit()
                else self.evaluation_user_id
            )
            state = _run_awaitable(runner(
                query.topic,
                query.role,
                query.difficulty,
                user_id=effective_user_id,
                knowledge_only=query.knowledge_scope == "private",
            ))
            evidence = list(state.get("evidence") or [])
            findings: list[str] = []
            for item in evidence:
                if item.get("source_type") == "public_kb" and item.get("corpus_version") not in ("", self.corpus_version):
                    findings.append("corpus_version_contamination")
                if query.knowledge_scope == "private" and item.get("source_type") != "personal_kb":
                    findings.append("private_scope_contamination")
            events = list(state.get("trace_events") or [])
            tool_calls = [
                ToolCallObservation.model_validate(event)
                for event in events
            ] or [ToolCallObservation(name=str(name)) for name in state.get("tool_calls") or []]
            return AgentTrace(
                sample_id=query.query_id,
                route=str(state.get("route") or "base_model"),
                tool_calls=tool_calls,
                candidate_count=int(state.get("candidate_count") or 0),
                filtered_count=int(state.get("filtered_count") or 0),
                confidence=float(state.get("confidence") or 0.0),
                coverage=float(state.get("coverage") or 0.0),
                fallback_reason=state.get("fallback_reason"),
                token_usage=dict(state.get("token_usage") or {}),
                estimated_cost_cny=(float(state["estimated_cost_cny"]) if state.get("estimated_cost_cny") is not None else None),
                retry_count=int(state.get("retry_count") or 0),
                total_latency_ms=float(state.get("total_latency_ms") or (time.perf_counter() - started) * 1000),
                completed=bool(state.get("completed", state.get("done", True))),
                answer="\n".join(str(item.get("text") or "") for item in evidence),
                policy_findings=findings,
            )
        except Exception as exc:
            return AgentTrace(
                sample_id=query.query_id,
                total_latency_ms=(time.perf_counter() - started) * 1000,
                completed=False,
                policy_findings=[f"agent_error:{type(exc).__name__}"],
            )


class OfflineEvaluationRunner:
    def __init__(self, store: Any, *, corpus_version: str, status: str = "published", top_k: int = 5,
                 retrieval_fn: Callable[..., Any] | None = None,
                 generation_fn: Callable[..., Any] | None = None,
                 agent_trace_fn: Callable[..., Any] | None = None,
                 user_id: int | str | None = None):
        self.store = store
        self.corpus_version = corpus_version
        self.status = status
        self.top_k = top_k
        self.retrieval_fn = retrieval_fn
        self.generation_fn = generation_fn
        self.agent_trace_fn = agent_trace_fn
        self.user_id = user_id

    def retrieve(self, query: BenchmarkQuery) -> RetrievalObservation:
        started = time.perf_counter()
        try:
            if self.retrieval_fn:
                rows = self.retrieval_fn(query=query, top_k=self.top_k, corpus_version=self.corpus_version, status=self.status, user_id=query.user_id if query.user_id is not None else self.user_id)
            else:
                kwargs = {"role": query.role, "corpus_version": self.corpus_version, "status": self.status}
                effective_user_id = query.user_id if query.user_id is not None else self.user_id
                if query.knowledge_scope == "private" and effective_user_id is not None:
                    kwargs["user_id"] = effective_user_id
                try:
                    rows = self.store.search(query.query, self.top_k, **kwargs)
                except TypeError:
                    kwargs.pop("user_id", None)
                    rows = self.store.search(query.query, self.top_k, **kwargs)
            # Defense in depth for stores whose search adapter cannot express
            # the private scope filter server-side.
            effective_user_id = query.user_id if query.user_id is not None else self.user_id
            if query.knowledge_scope == "private" and effective_user_id is not None:
                rows = [row for row in rows if str((row if isinstance(row, dict) else getattr(row, "metadata", {})).get("user_id", effective_user_id)) == str(effective_user_id)]
            hits = [_normalize_hit(row, self.store) for row in rows]
            return RetrievalObservation(
                sample_id=query.query_id,
                query=query.query,
                corpus_version=self.corpus_version,
                status=self.status,
                retrieved_contexts=[str(hit.get("parent_text") or hit.get("evidence_text") or hit.get("text") or "") for hit in hits],
                retrieved_context_ids=[str(hit.get("parent_id") or hit.get("document_id") or hit.get("source_id") or "") for hit in hits],
                hits=hits,
                citations=[str(hit.get("citation") or hit.get("source_url") or hit.get("source_name") or "") for hit in hits],
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception as exc:
            return RetrievalObservation(sample_id=query.query_id, query=query.query, corpus_version=self.corpus_version, status=self.status, latency_ms=(time.perf_counter() - started) * 1000, error=f"{type(exc).__name__}: {exc}")

    def run(self, dataset: GoldenDataset) -> list[RetrievalObservation]:
        if dataset.top_k != self.top_k:
            raise ValueError(f"top_k mismatch: dataset={dataset.top_k}, runner={self.top_k}")
        return [self.retrieve(query) for query in dataset.queries]

    def run_full(self, dataset: GoldenDataset) -> dict[str, Any]:
        """Run retrieval plus optional production generation/agent callbacks.

        Callbacks are deliberately injected: the offline runner does not
        duplicate the online routing algorithm or make network calls unless a
        caller explicitly supplies an adapter. Failures are retained per
        sample so a partial run remains auditable.
        """
        observations = self.run(dataset)
        generations: dict[str, Any] = {}
        traces: dict[str, Any] = {}
        errors: list[dict[str, str]] = []
        by_id = {item.sample_id: item for item in observations}
        total = len(dataset.queries)
        for position, query in enumerate(dataset.queries, start=1):
            observation = by_id.get(query.query_id)
            if self.generation_fn is not None:
                try:
                    generations[query.query_id] = _run_awaitable(self.generation_fn(query=query, observation=observation))
                except TypeError as exc:
                    # Only retry a legacy positional callback when the call
                    # signature rejected keyword arguments.  Do not hide a
                    # TypeError raised by the callback's implementation.
                    if "unexpected keyword" not in str(exc) and "positional" not in str(exc):
                        raise
                    generations[query.query_id] = _run_awaitable(self.generation_fn(query, observation))
                except Exception as exc:
                    errors.append({"sample_id": query.query_id, "stage": "generation", "error": f"{type(exc).__name__}: {exc}"})
            if self.agent_trace_fn is not None:
                try:
                    traces[query.query_id] = _run_awaitable(self.agent_trace_fn(query=query, observation=observation))
                except TypeError as exc:
                    if "unexpected keyword" not in str(exc) and "positional" not in str(exc):
                        raise
                    traces[query.query_id] = _run_awaitable(self.agent_trace_fn(query, observation))
                except Exception as exc:
                    errors.append({"sample_id": query.query_id, "stage": "agent", "error": f"{type(exc).__name__}: {exc}"})
            if position == 1 or position % 5 == 0 or position == total:
                logger.warning(
                    "offline_evaluation_progress completed=%s total=%s generations=%s traces=%s errors=%s",
                    position,
                    total,
                    len(generations),
                    len(traces),
                    len(errors),
                )
        return {"observations": observations, "generations": generations, "traces": traces, "errors": errors}

    @staticmethod
    def ragas_rows(dataset: GoldenDataset, observations: list[RetrievalObservation], responses: dict[str, str] | None = None) -> list[dict[str, Any]]:
        response_map = responses or {}
        by_id = {item.sample_id: item for item in observations}
        rows = []
        for query in dataset.queries:
            observation = by_id.get(query.query_id)
            rows.append({
                "sample_id": query.query_id,
                "user_input": query.query,
                "retrieved_contexts": observation.retrieved_contexts if observation else [],
                "reference": query.reference_answer,
                "response": response_map.get(query.query_id, ""),
            })
        return rows
