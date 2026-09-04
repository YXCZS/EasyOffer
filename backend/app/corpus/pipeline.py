from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.corpus.chunking import DeepSeekBoundaryClassifier, build_child_chunks, build_parent_units
from app.corpus.config import CorpusConfig
from app.corpus.dedup import deduplicate_chunks
from app.corpus.evaluation import (
    EvaluationReport, QueryEvaluation, enforce_gate, evaluate_store, load_benchmark, load_golden_dataset,
    calculate_context_metrics, calculate_metrics, _answer_integrity, _normalize_hit,
    build_evaluation_payload, evaluate_quiz_business, evaluate_report_business,
    aggregate_quiz_quality, aggregate_report_quality, evaluate_agent_trace, detect_agent_risks,
    aggregate_agent_evaluations, enforce_full_gate, write_evaluation_files,
    FULL_EVALUATION_GATES,
)
from app.corpus.evaluation_runner import OfflineEvaluationRunner, ProductionEvaluationAdapter
from app.corpus.manifest import load_manifest
from app.corpus.models import (
    BatchResult,
    ChildChunk,
    DocumentProcessResult,
    ParentUnit,
    ParsedBlock,
    ParsedDocument,
    PublicationResult,
    SourceEntry,
)
from app.corpus.parsers import parse_source
from app.corpus.quality import review_records
from app.corpus.registry import CorpusRegistry
from app.corpus.storage import CorpusStore, MilvusCorpusStore


class PublicationError(RuntimeError):
    pass


_SENSITIVE_KEY = re.compile(r"(api[_-]?key|secret|token|password|authorization)", re.IGNORECASE)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CorpusPipeline:
    def __init__(self, config: CorpusConfig | None = None, store: CorpusStore | None = None):
        self.config = config or CorpusConfig()
        self.store = store or MilvusCorpusStore()
        self.registry = CorpusRegistry(self.config.runtime_root)

    def _batch_id(self, manifest_path: Path, mode: str, sources: list[SourceEntry]) -> str:
        hasher = hashlib.sha256(manifest_path.read_bytes())
        hasher.update(self.config.pipeline_revision.encode("utf-8"))
        for source in sources:
            hasher.update(source.document_id.encode("utf-8"))
        digest = hasher.hexdigest()[:16]
        if mode == "ingest":
            return f"ingest-{digest}"
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{mode}-{stamp}-{digest}"

    def _write_json(self, path: Path, value: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(_redact(value), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        temporary.replace(path)
        return path

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows),
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _save_parsed(self, path: Path, parsed: ParsedDocument) -> None:
        self._write_json(
            path,
            {
                "text": parsed.text,
                "blocks": [asdict(block) for block in parsed.blocks],
                "page_count": parsed.page_count,
                "warnings": parsed.warnings,
                "rejected_blocks": parsed.rejected_blocks,
                "parser_name": parsed.parser_name,
                "parser_schema": parsed.parser_schema,
                "metadata": parsed.metadata,
            },
        )

    def _load_parsed(self, path: Path, source: SourceEntry) -> ParsedDocument:
        payload = self._read_json(path)
        return ParsedDocument(
            source=source,
            text=str(payload["text"]),
            blocks=[ParsedBlock(**item) for item in payload["blocks"]],
            page_count=payload.get("page_count"),
            warnings=list(payload.get("warnings") or []),
            rejected_blocks=list(payload.get("rejected_blocks") or []),
            parser_name=str(payload.get("parser_name") or "local"),
            parser_schema=str(payload.get("parser_schema") or "text"),
            metadata=dict(payload.get("metadata") or {}),
        )

    def _process(self, manifest_path: str | Path, mode: str) -> tuple[BatchResult, list[dict[str, Any]]]:
        started = time.perf_counter()
        path = Path(manifest_path).resolve()
        manifest = load_manifest(path)
        enabled_sources = [source for source in manifest.sources if source.enabled]
        batch_id = self._batch_id(path, mode, enabled_sources)
        batch_dir = self.config.runtime_root / "runs" / batch_id
        classifier = DeepSeekBoundaryClassifier(self.config.runtime_root / "cache" / "boundaries")
        documents: list[DocumentProcessResult] = []
        all_chunks = []
        for source in enabled_sources:
            document_dir = batch_dir / "documents" / source.document_id
            status_path = document_dir / "status.json"
            status = self._read_json(status_path) if mode == "ingest" and status_path.exists() else {}
            completed_stages = list(status.get("completed_stages") or [])
            current_stage = "parse"
            try:
                parsed_path = document_dir / "parsed.json"
                if mode == "ingest" and "parsed" in completed_stages and parsed_path.exists():
                    parsed = self._load_parsed(parsed_path, source)
                else:
                    parsed = parse_source(source)
                    if mode == "ingest":
                        self._save_parsed(parsed_path, parsed)
                        completed_stages = ["parsed"]
                        self._write_json(status_path, {"document_id": source.document_id, "status": "processing", "completed_stages": completed_stages})

                current_stage = "parents"
                parents_path = document_dir / "parents.json"
                if mode == "ingest" and "parents" in completed_stages and parents_path.exists():
                    parents = [ParentUnit(**item) for item in self._read_json(parents_path)]
                else:
                    parents = build_parent_units(parsed, self.config, classifier)
                    if mode == "ingest":
                        self._write_json(parents_path, [asdict(parent) for parent in parents])
                        completed_stages = ["parsed", "parents"]
                        self._write_json(status_path, {"document_id": source.document_id, "status": "processing", "completed_stages": completed_stages})

                current_stage = "chunks"
                chunks_path = document_dir / "chunks.jsonl"
                if mode == "ingest" and "chunks" in completed_stages and chunks_path.exists():
                    chunks = [ChildChunk(**item) for item in self._read_jsonl(chunks_path)]
                else:
                    chunks = build_child_chunks(parents, source, self.config)
                    if mode == "ingest":
                        self._write_jsonl(chunks_path, [asdict(chunk) for chunk in chunks])
                        completed_stages = ["parsed", "parents", "chunks"]
                        self._write_json(status_path, {"document_id": source.document_id, "status": "staged", "completed_stages": completed_stages})
                all_chunks.extend(chunks)
                rejected = list(parsed.rejected_blocks)
                documents.append(
                    DocumentProcessResult(
                        document_id=source.document_id,
                        status="previewed" if mode == "preview" else "staged",
                        page_count=parsed.page_count,
                        text_length=len(parsed.text),
                        parent_count=len(parents),
                        chunk_count=len(chunks),
                        parsed_block_count=len(parsed.blocks),
                        assigned_block_count=len(parsed.blocks) - len(rejected),
                        rejected_blocks=rejected,
                        completed_stages=completed_stages,
                        warnings=parsed.warnings,
                        metrics={
                            "pdf_preflight": parsed.metadata.get("pdf_preflight", {}),
                            "visual": parsed.metadata.get("visual_metrics", {}),
                        },
                    )
                )
            except Exception as exc:
                if mode == "ingest":
                    self._write_json(
                        status_path,
                        {
                            "document_id": source.document_id,
                            "status": "failed",
                            "failed_stage": current_stage,
                            "completed_stages": completed_stages,
                            "failure_reason": str(exc)[:300] or type(exc).__name__,
                        },
                    )
                documents.append(
                    DocumentProcessResult(
                        document_id=source.document_id,
                        status="failed",
                        completed_stages=completed_stages,
                        failure_reason=str(exc)[:300] or type(exc).__name__,
                    )
                )
        deduplicated = deduplicate_chunks(all_chunks, self.config.near_duplicate_hamming_distance)
        duplicate_by_document: dict[str, int] = {}
        internal_duplicate_by_document: dict[str, int] = {}
        chunk_documents = {item.chunk_id: item.document_id for item in all_chunks}
        for duplicate in deduplicated.duplicates:
            document_id = chunk_documents.get(duplicate.chunk_id, "")
            duplicate_by_document[document_id] = duplicate_by_document.get(document_id, 0) + 1
            if document_id and document_id == chunk_documents.get(duplicate.duplicate_of, ""):
                internal_duplicate_by_document[document_id] = internal_duplicate_by_document.get(document_id, 0) + 1
        records = [chunk.to_record() for chunk in deduplicated.kept]
        quality = review_records(records, self.config) if records else None
        issues_by_document: dict[str, set[str]] = {}
        if quality:
            for issue in quality.issues:
                issues_by_document.setdefault(issue.document_id, set()).add(issue.code)
        kept_by_document: dict[str, int] = {}
        for row in records:
            kept_by_document[str(row["document_id"])] = kept_by_document.get(str(row["document_id"]), 0) + 1
        for document in documents:
            document.duplicate_count = duplicate_by_document.get(document.document_id, 0)
            if document.status != "failed":
                document.chunk_count = kept_by_document.get(document.document_id, 0)
                document.quality_issues = sorted(issues_by_document.get(document.document_id, set()))
                if document.duplicate_count:
                    document.quality_issues.append("duplicate_content")
                    internal_duplicates = internal_duplicate_by_document.get(document.document_id, 0)
                    total_candidates = document.chunk_count + internal_duplicates
                    if internal_duplicates / max(1, total_candidates) > self.config.duplicate_content_ratio_threshold:
                        document.quality_issues.append("duplicate_ratio_exceeded")
        stage_path = batch_dir / "chunks.jsonl"
        if mode == "ingest":
            self._write_jsonl(stage_path, records)
            self._write_json(
                batch_dir / "quality.json",
                {
                    "passed": bool(quality and quality.passed),
                    "issues": [asdict(issue) for issue in quality.issues] if quality else [],
                    "duplicates": [asdict(item) for item in deduplicated.duplicates],
                },
            )
        report_path = batch_dir / "report.json"
        report = {
            "batch_id": batch_id,
            "manifest_version": manifest.manifest_version,
            "corpus_version": manifest.sources[0].target_corpus_version,
            "mode": mode,
            "started_at": _now(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "documents": [asdict(item) for item in documents],
            "totals": {
                "documents": len(documents),
                "successful_documents": sum(item.status != "failed" for item in documents),
                "failed_documents": sum(item.status == "failed" for item in documents),
                "chunks": len(records),
                "duplicates": len(deduplicated.duplicates),
            },
            "quality_findings": {
                item.document_id: item.quality_issues
                for item in documents
                if item.quality_issues
            },
        }
        self._write_json(report_path, report)
        result = BatchResult(
            batch_id=batch_id,
            corpus_version=manifest.sources[0].target_corpus_version,
            mode=mode,
            documents=documents,
            report_path=report_path,
            stage_path=stage_path if mode == "ingest" else None,
        )
        return result, records

    def preview(self, manifest_path: str | Path) -> BatchResult:
        result, _ = self._process(manifest_path, "preview")
        return result

    def ingest(self, manifest_path: str | Path) -> BatchResult:
        result, records = self._process(manifest_path, "ingest")
        if records:
            self.store.upsert(records)
        self.registry.record_batch(
            result.batch_id,
            {
                "batch_id": result.batch_id,
                "corpus_version": result.corpus_version,
                "mode": result.mode,
                "manifest_path": str(Path(manifest_path).resolve()),
                "report_path": str(result.report_path),
                "stage_path": str(result.stage_path),
                "chunk_count": result.chunk_count,
                "documents": [asdict(item) for item in result.documents],
                "recorded_at": _now(),
            },
        )
        return result

    def evaluate(self, benchmark_path: str | Path, corpus_version: str) -> EvaluationReport:
        benchmark = load_benchmark(benchmark_path)
        report = evaluate_store(self.store, benchmark, corpus_version, status="unpublished")
        gate = enforce_gate(report, self.config.gates)
        path = self.config.runtime_root / "evaluations" / f"{corpus_version}-{benchmark.benchmark_version}.json"
        self._write_json(path, {"report": report.model_dump(mode="json"), "gate": gate.model_dump(mode="json")})
        self.registry.record_evaluation(
            corpus_version,
            {"path": str(path), "gate": gate.model_dump(mode="json"), "recorded_at": _now()},
        )
        return report

    def evaluate_full(self, benchmark_path: str | Path, corpus_version: str, *, status: str = "published",
                      generation_fn: Any | None = None, agent_trace_fn: Any | None = None,
                      include_generation: bool = False, include_agent: bool = False,
                      include_ragas: bool = False, output: str | Path | None = None,
                      override_reason: str | None = None, override_by: str | None = None) -> dict[str, Any]:
        """Run the offline, auditable evaluation envelope.

        Optional model and Agent stages call the real production boundaries
        through a thin adapter. Deterministic evaluation never calls a model.
        """
        dataset = load_golden_dataset(benchmark_path)
        if include_ragas and not include_generation:
            raise ValueError("include_ragas requires include_generation")
        adapter = ProductionEvaluationAdapter(
            self.store, corpus_version=corpus_version, status=status, top_k=dataset.top_k,
        )
        runner = OfflineEvaluationRunner(
            self.store, corpus_version=corpus_version, status=status, top_k=dataset.top_k,
            generation_fn=(generation_fn or adapter.generate) if include_generation else None,
            agent_trace_fn=(agent_trace_fn or adapter.agent_trace) if include_agent else None,
        )
        full_run = runner.run_full(dataset)
        observations = full_run["observations"]
        # Keep the legacy EvaluationReport envelope while using the same
        # observation adapter for full evaluation. This prevents offline
        # metrics from silently drifting from the production retrieval call.
        query_results: list[QueryEvaluation] = []
        for query, observation in zip(dataset.queries, observations):
            hits = observation.hits
            context = calculate_context_metrics(query, hits[:dataset.top_k])
            query_results.append(QueryEvaluation(query=query, hits=hits,
                latency_ms=observation.latency_ms,
                answer_integrity=all(_answer_integrity(hit) for hit in hits) if hits else False,
                **context, error=observation.error))
        report = EvaluationReport(corpus_version=corpus_version,
                                  benchmark_version=dataset.benchmark_version,
                                  top_k=dataset.top_k, metrics=calculate_metrics(query_results, dataset.top_k),
                                  queries=query_results)
        quiz_results, report_results, agent_results = [], [], []
        responses: dict[str, str] = {}
        errors: list[str] = [f"{item['sample_id']}:{item['stage']}:{item['error']}" for item in full_run["errors"]]
        report_by_id = {item.query.query_id: item for item in report.queries}
        for query in dataset.queries:
            item = report_by_id[query.query_id]
            generated = full_run["generations"].get(query.query_id)
            if include_generation:
                if generated is None or getattr(generated, "error", None):
                    quiz_results.append(evaluate_quiz_business(query.query_id, None, query.expected_knowledge_points, query.difficulty))
                    if generated is not None and getattr(generated, "error", None):
                        errors.append(f"{query.query_id}:generation:{generated.error}")
                else:
                    quiz_payload = getattr(generated, "quiz", generated)
                    report_payload = getattr(generated, "report", None)
                    quiz_results.append(evaluate_quiz_business(query.query_id, quiz_payload, query.expected_knowledge_points, query.difficulty, item.hits))
                    if report_payload is not None:
                        report_results.append(evaluate_report_business(query.query_id, report_payload, query.expected_knowledge_points, query.topic, item.hits))
                    responses[query.query_id] = str(getattr(generated, "response", "") or "")
            trace = full_run["traces"].get(query.query_id)
            if include_agent:
                if trace is None:
                    agent_results.append({"result": {"task_completed": False, "answer_present": False}, "process": {"route_correct": False, "expected_tools_present": False, "stopped_within_budget": False}, "risk": {"passed": False}})
                    errors.append(f"{query.query_id}:agent:missing_trace")
                else:
                    trace.policy_findings = sorted(set(trace.policy_findings + detect_agent_risks(trace, private=query.knowledge_scope == "private")))
                    agent_results.append(evaluate_agent_trace(trace, query.expected_route, query.expected_tools))
        quiz_quality = aggregate_quiz_quality(quiz_results)
        report_quality = aggregate_report_quality(report_results)
        agent_quality = aggregate_agent_evaluations(agent_results)
        ragas_result = None
        if include_ragas:
            try:
                from app.corpus.ragas_evaluation import evaluate_ragas_from_observations
                import asyncio
                ragas_result = asyncio.run(evaluate_ragas_from_observations(dataset, observations, responses=responses))
                if ragas_result.status != "success":
                    errors.append(ragas_result.error or f"ragas_status:{ragas_result.status}")
            except Exception as exc:
                from app.corpus.evaluation import RagasEvaluationReport
                ragas_result = RagasEvaluationReport(status="failed", error=f"{type(exc).__name__}: {exc}")
                errors.append(ragas_result.error or "ragas_failed")
        metrics = {**report.metrics}
        if include_generation:
            metrics.update(quiz_quality)
            if report_results:
                metrics.update(report_quality)
        if include_agent:
            metrics.update(agent_quality)
        if ragas_result:
            metrics.update({name: float(value) for name, value in ragas_result.metrics.items() if value is not None})
        selected_gates = dict(self.config.gates)
        if include_generation:
            selected_gates.update({name: FULL_EVALUATION_GATES[name] for name in ("quiz_valid_rate", "quiz_duplicate_rate")})
        if include_ragas:
            selected_gates.update({
                name: FULL_EVALUATION_GATES[name]
                for name in (
                    "context_precision",
                    "context_recall",
                    "faithfulness",
                    "answer_relevancy",
                )
            })
        if include_agent:
            selected_gates.update({name: FULL_EVALUATION_GATES[name] for name in ("private_kb_violation_rate", "high_risk_false_allow_rate")})
        gates = enforce_full_gate(metrics, gates=selected_gates, required_metrics=set(selected_gates),
                                  override_reason=override_reason, override_by=override_by)
        payload = build_evaluation_payload(report, dataset=dataset, ragas=ragas_result,
                                           quiz_quality=quiz_quality, report_quality=report_quality,
                                           agent=agent_quality, gates=gates, errors=errors,
                                           metadata={"status_filter": status, "include_ragas": include_ragas,
                                                     "include_generation": include_generation, "include_agent": include_agent,
                                                     "code_version": self.config.pipeline_revision,
                                                     "comparison_thresholds": self.config.comparison_thresholds},
                                           generation_observations=full_run["generations"], agent_traces=full_run["traces"])
        if output is None:
            output = self.config.runtime_root / "evaluations" / f"{corpus_version}-{dataset.benchmark_version}-full.json"
        json_path, md_path = write_evaluation_files(payload, output)
        payload["report_path"] = str(json_path)
        payload["markdown_path"] = str(md_path)
        self.registry.record_evaluation(corpus_version, {
            "path": str(json_path), "markdown_path": str(md_path),
            "sha256": hashlib.sha256(json_path.read_bytes()).hexdigest(),
            "gate": gates.model_dump(mode="json"), "recorded_at": _now(),
        })
        return payload

    def approve(
        self,
        corpus_version: str,
        *,
        reviewer: str,
        evaluation_override: str | None = None,
        review_file: str | Path | None = None,
    ) -> Path:
        batch = self.registry.latest_batch_for(corpus_version)
        if not batch:
            raise PublicationError("candidate batch not found")
        blocking = sorted(
            {
                issue
                for document in batch.get("documents", [])
                for issue in document.get("quality_issues", [])
                if issue not in {"low_structure_confidence", "duplicate_content"}
            }
        )
        failed_documents = [
            document.get("document_id")
            for document in batch.get("documents", [])
            if document.get("status") == "failed"
        ]
        if failed_documents:
            blocking.append("failed_documents")
        if blocking:
            detail = ", ".join(blocking)
            if failed_documents:
                detail += " (" + ", ".join(str(item) for item in failed_documents) + ")"
            raise PublicationError("quality or license checks failed: " + detail)
        if not reviewer.strip():
            raise PublicationError("reviewer is required")
        if evaluation_override is not None and len(evaluation_override.strip()) < 8:
            raise PublicationError("evaluation override reason must be at least 8 characters")
        evaluation = self.registry.evaluation(corpus_version)
        if not evaluation_override and (not evaluation or not evaluation.get("gate", {}).get("passed")):
            raise PublicationError("retrieval evaluation gate has not passed")
        if not review_file:
            raise PublicationError("version-controlled review artifact is required")
        review_path = Path(review_file).resolve()
        review_root = self.config.review_root.resolve()
        try:
            review_path.relative_to(review_root)
        except ValueError as exc:
            raise PublicationError("review artifact must be stored under the configured review root") from exc
        if not review_path.exists() or review_path.suffix.lower() not in {".yaml", ".yml"}:
            raise PublicationError("version-controlled review artifact must be an existing YAML file")
        import yaml

        review_payload = yaml.safe_load(review_path.read_text(encoding="utf-8")) or {}
        if not isinstance(review_payload, dict):
            raise PublicationError("review artifact must be a YAML mapping")
        if str(review_payload.get("corpus_version") or "") != corpus_version:
            raise PublicationError("review artifact corpus_version mismatch")
        if str(review_payload.get("reviewer") or "").strip() != reviewer.strip():
            raise PublicationError("review artifact reviewer mismatch")
        if not str(review_payload.get("reviewed_at") or "").strip():
            raise PublicationError("review artifact reviewed_at is required")
        if str(review_payload.get("decision") or "").lower() not in {"approved", "approve", "pass"}:
            raise PublicationError("review artifact decision is not approved")
        if not str(review_payload.get("decision_reason") or "").strip():
            raise PublicationError("review artifact decision_reason is required")
        if not review_payload.get("samples"):
            raise PublicationError("review artifact must contain human samples")
        review_artifact = {
            "path": str(review_path),
            "sha256": hashlib.sha256(review_path.read_bytes()).hexdigest(),
            "sample_count": len(review_payload["samples"]),
        }
        approval = {
            "corpus_version": corpus_version,
            "reviewer": reviewer.strip(),
            "approved_at": _now(),
            "batch_id": batch["batch_id"],
            "evaluation": evaluation,
            "override_reason": evaluation_override.strip() if evaluation_override else None,
            "review_artifact": review_artifact,
        }
        path = self.config.runtime_root / "reviews" / f"{corpus_version}.json"
        self._write_json(path, approval)
        self.registry.approve(corpus_version, {**approval, "path": str(path)})
        self.store.update(f"corpus_version == '{corpus_version}'", review_status="approved")
        return path

    def publish(self, corpus_version: str) -> PublicationResult:
        if not self.registry.approval(corpus_version):
            raise PublicationError("candidate has no human approval")
        candidate_filter = f"corpus_version == '{corpus_version}'"
        if not self.store.count(candidate_filter):
            raise PublicationError("candidate has no staged chunks")
        previous = self.registry.active_version()
        timestamp = _now()
        switched_candidate = False
        deactivated_previous = False
        try:
            self.store.update(candidate_filter, status="published", published_at=timestamp)
            switched_candidate = True
            if previous and previous != corpus_version:
                self.store.update(f"corpus_version == '{previous}'", status="inactive")
                deactivated_previous = True
            if not self.store.smoke(corpus_version):
                raise PublicationError("post-publish smoke check failed")
            self.registry.set_active(corpus_version)
        except Exception as exc:
            if switched_candidate:
                self.store.update(candidate_filter, status="unpublished", published_at=None)
            if deactivated_previous and previous:
                self.store.update(f"corpus_version == '{previous}'", status="published")
            if self.registry.active_version() != previous:
                self.registry.set_active(previous)
            report_path = self.config.runtime_root / "reports" / f"publish-{corpus_version}-rollback.json"
            self._write_json(
                report_path,
                {
                    "corpus_version": corpus_version,
                    "previous_version": previous,
                    "action": "rollback",
                    "reason": type(exc).__name__,
                    "detail": str(exc)[:300],
                    "at": _now(),
                },
            )
            raise PublicationError(f"publication failed; previous version restored: {exc}") from exc
        count = self.store.count(f"corpus_version == '{corpus_version}' and status == 'published'")
        report_path = self.config.runtime_root / "reports" / f"publish-{corpus_version}.json"
        self._write_json(
            report_path,
            {"corpus_version": corpus_version, "previous_version": previous, "published_count": count, "action": "published", "at": timestamp},
        )
        return PublicationResult(corpus_version, count, previous, report_path)

    def withdraw(self, corpus_version: str, *, reason: str) -> Path:
        if not reason.strip():
            raise PublicationError("withdrawal reason is required")
        updated = self.store.update(
            f"corpus_version == '{corpus_version}'",
            status="withdrawn",
            withdrawal_reason=reason.strip(),
            withdrawn_at=_now(),
        )
        if not updated:
            raise PublicationError("corpus version not found")
        self.registry.withdraw(corpus_version, reason.strip(), _now())
        path = self.config.runtime_root / "reports" / f"withdraw-{corpus_version}.json"
        return self._write_json(path, {"corpus_version": corpus_version, "withdrawn_count": updated, "reason": reason.strip(), "at": _now()})

    def inspect(self, corpus_version: str | None = None) -> dict[str, Any]:
        registry = self.registry.load()
        if corpus_version is None:
            return registry
        return {
            "corpus_version": corpus_version,
            "active": registry.get("active_version") == corpus_version,
            "approval": registry.get("approvals", {}).get(corpus_version),
            "evaluation": registry.get("evaluations", {}).get(corpus_version),
            "withdrawal": registry.get("withdrawals", {}).get(corpus_version),
            "chunks": self.store.count(f"corpus_version == '{corpus_version}'"),
        }

    def statistics(self) -> dict[str, Any]:
        registry = self.registry.load()
        return {
            "active_version": registry.get("active_version"),
            "batch_count": len(registry.get("batches", {})),
            "approval_count": len(registry.get("approvals", {})),
            "evaluation_count": len(registry.get("evaluations", {})),
            "chunk_count": self.store.count(),
        }
