from __future__ import annotations

import json

from app.corpus.cli import _configure_standard_streams, _load_evaluation_report, main
from app.corpus.evaluation import EvaluationReport


def write_manifest(tmp_path):
    (tmp_path / "redis.md").write_text(
        "# Redis\n\n问题：RDB 和 AOF 有什么区别？\n答案：RDB 是快照，AOF 记录写命令。" * 3,
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        """manifest_version: cli-v1
sources:
  - document_id: redis-cli
    path: redis.md
    source_name: Redis docs
    source_url: https://redis.io/docs/
    technology: Redis
    role_tags: [backend]
    document_version: v1
    language: zh-CN
    content_type: markdown
    license_status: approved
    target_corpus_version: cli-v1
""",
        encoding="utf-8",
    )
    return manifest


def test_cli_help_lists_governance_commands(capsys):
    assert main(["--help"]) == 0
    output = capsys.readouterr().out
    for command in ("preview", "ingest", "inspect", "evaluate", "approve", "publish", "withdraw", "retry", "stats"):
        assert command in output


def test_cli_configures_utf8_output_streams(monkeypatch):
    configured = []

    class Stream:
        def reconfigure(self, **kwargs):
            configured.append(kwargs)

    monkeypatch.setattr("app.corpus.cli.sys.stdout", Stream())
    monkeypatch.setattr("app.corpus.cli.sys.stderr", Stream())

    _configure_standard_streams()

    assert configured == [{"encoding": "utf-8"}, {"encoding": "utf-8"}]


def test_cli_preview_emits_json_without_milvus(tmp_path, capsys):
    exit_code = main([
        "--runtime-root", str(tmp_path / "runtime"),
        "--store", "memory",
        "preview", str(write_manifest(tmp_path)),
    ])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["mode"] == "preview"
    assert payload["chunk_count"] > 0


def test_cli_loads_wrapped_evaluation_artifact(tmp_path):
    report = EvaluationReport(
        corpus_version="v1",
        benchmark_version="b1",
        top_k=5,
        metrics={"hit_at_5": 1.0},
        queries=[],
    )
    path = tmp_path / "evaluation.json"
    path.write_text(
        json.dumps({"report": report.model_dump(mode="json"), "gate": {"passed": True}}),
        encoding="utf-8",
    )

    loaded = _load_evaluation_report(path)

    assert loaded == report


def test_cli_blocked_operation_returns_nonzero_json(tmp_path, capsys):
    exit_code = main([
        "--runtime-root", str(tmp_path / "runtime"),
        "--store", "memory",
        "publish", "missing-version",
    ])

    payload = json.loads(capsys.readouterr().err)
    assert exit_code == 1
    assert payload["failure_type"] == "PublicationError"


def test_cli_returns_failure_when_requested_ragas_gate_is_unavailable(tmp_path, capsys, monkeypatch):
    def unavailable_ragas(*args, **kwargs):
        return {
            "ragas": {"status": "unavailable", "metrics": {}},
            "gates": {"passed": False, "failed_metrics": {"faithfulness": {"actual": "unavailable"}}},
        }

    monkeypatch.setattr("app.corpus.cli.CorpusPipeline.evaluate_full", unavailable_ragas)
    exit_code = main([
        "--runtime-root", str(tmp_path / "runtime"), "--store", "memory", "evaluate",
        "golden.yaml", "candidate-v1", "--include-generation", "--ragas",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ragas"]["status"] == "unavailable"
