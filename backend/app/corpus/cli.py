from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.corpus.config import CorpusConfig
from app.corpus.evaluation import EvaluationReport, compare_reports
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
        store = InMemoryCorpusStore() if args.store == "memory" else MilvusCorpusStore()
        pipeline = CorpusPipeline(config, store=store)
        if args.command == "preview":
            payload = _batch_payload(pipeline.preview(args.manifest))
        elif args.command == "ingest":
            payload = _batch_payload(pipeline.ingest(args.manifest))
        elif args.command == "evaluate":
            payload = pipeline.evaluate(args.benchmark, args.corpus_version)
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
            current = _load_evaluation_report(args.current)
            candidate = _load_evaluation_report(args.candidate)
            payload = compare_reports(current, candidate)
        else:  # pragma: no cover
            parser.error("unknown command")
        print(_json(payload))
        return 0
    except Exception as exc:
        print(_json({"error": str(exc), "failure_type": type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
