from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.corpus.config import CorpusConfig
from app.corpus.evaluation import (
    EvaluationReport,
    build_evaluation_payload,
    compare_reports,
    compare_evaluation_payloads,
    enforce_gate,
    load_golden_dataset,
    migrate_legacy_benchmark,
    write_evaluation_files,
)
from app.corpus.pipeline import CorpusPipeline
from app.corpus.storage import InMemoryCorpusStore, MilvusCorpusStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="easyoffer-corpus", description="EasyOffer 公共技术面试知识库治理工具")
    parser.add_argument("--config", help="语料配置 YAML")
    parser.add_argument("--runtime-root", help="覆盖运行产物目录")
    parser.add_argument("--store", choices=("milvus", "memory"), default="milvus", help="存储后端；memory 仅用于本地预览/测试")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("preview", "ingest"):
        child = subparsers.add_parser(command, help=f"{command} 资料清单")
        child.add_argument("manifest")
    evaluate = subparsers.add_parser("evaluate", help="运行检索基准")
    evaluate.add_argument("benchmark")
    evaluate.add_argument("corpus_version")
    evaluate.add_argument("--deterministic-only", action="store_true")
    evaluate.add_argument("--ragas", action="store_true")
    evaluate.add_argument("--include-generation", action="store_true")
    evaluate.add_argument("--include-agent", action="store_true")
    evaluate.add_argument("--override-reason", help="允许门禁未达标时继续发布的审计理由")
    evaluate.add_argument("--override-by", help="执行覆盖的维护者身份")
    evaluate.add_argument("--output")
    validate = subparsers.add_parser("validate-golden", help="validate a 100-sample Golden Dataset")
    validate.add_argument("golden")
    migrate = subparsers.add_parser("migrate-golden", help="enrich a historical benchmark without changing its source")
    migrate.add_argument("benchmark")
    migrate.add_argument("output")
    eval_report = subparsers.add_parser("eval-report", help="show an evaluation report")
    eval_report.add_argument("report")
    inspect = subparsers.add_parser("inspect", help="查看版本治理状态")
    inspect.add_argument("corpus_version", nargs="?")
    approve = subparsers.add_parser("approve", help="记录人工审核")
    approve.add_argument("corpus_version")
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--override-reason")
    approve.add_argument("--review-file", required=True, help="corpus/reviews 下的版本化 YAML 人工审核记录")
    publish = subparsers.add_parser("publish", help="发布已批准候选版本")
    publish.add_argument("corpus_version")
    withdraw = subparsers.add_parser("withdraw", help="撤回公共版本")
    withdraw.add_argument("corpus_version")
    withdraw.add_argument("--reason", required=True)
    retry = subparsers.add_parser("retry", help="重新执行最近失败批次")
    retry.add_argument("corpus_version")
    subparsers.add_parser("stats", help="输出语料统计")
    compare = subparsers.add_parser("compare", help="比较两个检索评估报告")
    compare.add_argument("current")
    compare.add_argument("candidate")
    return parser


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif hasattr(value, "__dict__"):
        value = value.__dict__
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _configure_standard_streams() -> None:
    """Keep machine-readable Chinese JSON writable on Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def _batch_payload(result) -> dict[str, Any]:
    return {
        "batch_id": result.batch_id,
        "corpus_version": result.corpus_version,
        "mode": result.mode,
        "chunk_count": result.chunk_count,
        "documents": [item.__dict__ for item in result.documents],
        "report_path": str(result.report_path),
        "stage_path": str(result.stage_path) if result.stage_path else None,
    }


def _load_evaluation_report(path: str | Path) -> EvaluationReport:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return EvaluationReport.model_validate(raw.get("report", raw))


def main(argv: list[str] | None = None) -> int:
    _configure_standard_streams()
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        config = CorpusConfig.load(args.config)
        if args.runtime_root:
            values = {**config.__dict__, "runtime_root": Path(args.runtime_root)}
            config = CorpusConfig(**values)
        if args.command == "validate-golden":
            dataset = load_golden_dataset(args.golden)
            print(_json({"valid": True, "benchmark_version": dataset.benchmark_version, "sample_count": len(dataset.queries), "content_hash": dataset.content_hash}))
            return 0
        if args.command == "migrate-golden":
            migrated = migrate_legacy_benchmark(args.benchmark, output=args.output)
            print(_json({"migrated": True, "output": str(Path(args.output).resolve()), "sample_count": len(migrated.queries), "benchmark_version": migrated.benchmark_version}))
            return 0
        if args.command == "eval-report":
            print(_json(json.loads(Path(args.report).read_text(encoding="utf-8"))))
            return 0
        store = InMemoryCorpusStore() if args.store == "memory" else MilvusCorpusStore()
        pipeline = CorpusPipeline(config, store=store)
        if args.command == "preview":
            payload = _batch_payload(pipeline.preview(args.manifest))
        elif args.command == "ingest":
            payload = _batch_payload(pipeline.ingest(args.manifest))
        elif args.command == "evaluate":
            if args.ragas and not args.include_generation:
                raise ValueError("--ragas requires --include-generation so RAGAS receives real generated content")
            if args.deterministic_only and (args.ragas or args.include_generation or args.include_agent):
                raise ValueError("--deterministic-only cannot be combined with generation, Agent, or RAGAS stages")
            payload = pipeline.evaluate_full(
                args.benchmark, args.corpus_version,
                status="published",
                include_generation=args.include_generation,
                include_agent=args.include_agent,
                include_ragas=args.ragas,
                output=args.output,
                override_reason=args.override_reason,
                override_by=args.override_by,
            )
            print(_json(payload))
            if (payload.get("gates") or {}).get("passed") is False:
                return 1
            return 0
        elif args.command == "inspect":
            payload = pipeline.inspect(args.corpus_version)
        elif args.command == "approve":
            payload = {"review_path": str(pipeline.approve(args.corpus_version, reviewer=args.reviewer, evaluation_override=args.override_reason, review_file=args.review_file))}
        elif args.command == "publish":
            payload = pipeline.publish(args.corpus_version)
        elif args.command == "withdraw":
            payload = {"withdrawal_report": str(pipeline.withdraw(args.corpus_version, reason=args.reason))}
        elif args.command == "retry":
            batch = pipeline.registry.latest_batch_for(args.corpus_version)
            if not batch:
                raise ValueError("candidate batch not found")
            payload = _batch_payload(pipeline.ingest(batch["manifest_path"]))
        elif args.command == "stats":
            payload = pipeline.statistics()
        elif args.command == "compare":
            current_raw = json.loads(Path(args.current).read_text(encoding="utf-8"))
            candidate_raw = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
            payload = compare_evaluation_payloads(current_raw, candidate_raw)
        else:  # pragma: no cover
            parser.error("unknown command")
        print(_json(payload))
        return 0
    except Exception as exc:
        print(_json({"error": str(exc), "failure_type": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
