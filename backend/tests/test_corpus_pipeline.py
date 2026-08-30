from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.corpus.config import CorpusConfig
from app.corpus.manifest import load_manifest
from app.corpus.pipeline import CorpusPipeline, PublicationError
from app.corpus.storage import InMemoryCorpusStore


class RaisingSmokeStore(InMemoryCorpusStore):
    def smoke(self, corpus_version: str) -> bool:
        raise RuntimeError("milvus unavailable")


def write_manifest(tmp_path, *, license_status: str = "approved"):
    source = tmp_path / "redis.md"
    source.write_text(
        "# Redis 持久化\n\n问题：RDB 和 AOF 有什么区别？\n答案：RDB 是快照，AOF 记录写命令。"
        "RDB 恢复速度通常更快，适合备份和灾难恢复；AOF 通过记录写命令降低数据丢失窗口。"
        "面试回答还应比较文件体积、重写机制、启动恢复时延和混合持久化的适用场景。",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        f"""manifest_version: pilot-v1
sources:
  - document_id: redis-persistence
    path: redis.md
    source_name: Redis docs
    source_url: https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/
    technology: Redis
    role_tags: [backend, general]
    document_version: '7.4'
    language: zh-CN
    content_type: markdown
    license_status: {license_status}
    target_corpus_version: pilot-v1
    retrieved_at: '2026-08-27'
""",
        encoding="utf-8",
    )
    return manifest


def write_mixed_manifest(tmp_path):
    manifest = write_manifest(tmp_path)
    missing = tmp_path / "missing.md"
    text = manifest.read_text(encoding="utf-8").replace("path: redis.md", "path: missing.md")
    text = text.replace("document_id: redis-persistence", "document_id: missing-doc")
    missing.write_text("", encoding="utf-8")
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + "\n  - document_id: broken\n    path: does-not-exist.md\n    source_name: Broken\n    source_url: https://example.com/broken\n    technology: Redis\n    role_tags: [backend]\n    document_version: v1\n    language: zh-CN\n    content_type: markdown\n    license_status: approved\n    target_corpus_version: pilot-v1\n",
        encoding="utf-8",
    )
    return manifest


def write_review_artifact(tmp_path, *, corpus_version="pilot-v1", reviewer="owner"):
    review_root = tmp_path / "reviews"
    review_root.mkdir(exist_ok=True)
    path = review_root / f"{corpus_version}.yaml"
    path.write_text(
        f"corpus_version: {corpus_version}\nreviewer: {reviewer}\nreviewed_at: '2026-08-27T00:00:00Z'\n"
        "decision: approved\ndecision_reason: fixture human review completed\n"
        "samples:\n  - query_id: q1\n    chunk_id: c1\n    parent_id: p1\n",
        encoding="utf-8",
    )
    return path


def test_preview_does_not_write_store_and_emits_redacted_report(tmp_path):
    store = InMemoryCorpusStore()
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews"), store=store)

    result = pipeline.preview(write_manifest(tmp_path))

    assert store.count() == 0
    assert result.documents[0].status == "previewed"
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["documents"][0]["chunk_count"] > 0
    assert "RDB 是快照" not in result.report_path.read_text(encoding="utf-8")


def test_ingest_is_idempotent_and_candidate_remains_unpublished(tmp_path):
    store = InMemoryCorpusStore()
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews"), store=store)
    manifest = write_manifest(tmp_path)

    first = pipeline.ingest(manifest)
    second = pipeline.ingest(manifest)

    assert first.chunk_count > 0
    assert second.chunk_count == first.chunk_count
    assert store.count() == first.chunk_count
    assert {row["status"] for row in store.rows} == {"unpublished"}
    assert all(row["corpus_version"] == "pilot-v1" for row in store.rows)


def test_pipeline_revision_invalidates_old_parse_cache(tmp_path):
    manifest = write_manifest(tmp_path)
    first = CorpusPipeline(
        CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews", pipeline_revision="text-v1"),
        store=InMemoryCorpusStore(),
    )
    second = CorpusPipeline(
        CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews", pipeline_revision="mineru-v2"),
        store=InMemoryCorpusStore(),
    )
    sources = load_manifest(manifest).sources

    assert first._batch_id(manifest.resolve(), "ingest", sources) != second._batch_id(manifest.resolve(), "ingest", sources)


def test_unlicensed_candidate_cannot_be_approved_or_published(tmp_path):
    store = InMemoryCorpusStore()
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews"), store=store)
    result = pipeline.ingest(write_manifest(tmp_path, license_status="local-evaluation-only"))

    with pytest.raises(PublicationError, match="license"):
        pipeline.approve(result.corpus_version, reviewer="owner", review_file=write_review_artifact(tmp_path))


def test_failed_document_blocks_candidate_approval(tmp_path):
    store = InMemoryCorpusStore()
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews"), store=store)
    result = pipeline.ingest(write_mixed_manifest(tmp_path))

    assert any(document.status == "failed" for document in result.documents)
    with pytest.raises(PublicationError, match="failed_documents"):
        pipeline.approve(result.corpus_version, reviewer="owner", evaluation_override="fixture approval", review_file=write_review_artifact(tmp_path))


def test_publish_rolls_back_status_when_smoke_check_fails(tmp_path):
    store = InMemoryCorpusStore()
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews"), store=store)
    result = pipeline.ingest(write_manifest(tmp_path))
    pipeline.approve(result.corpus_version, reviewer="owner", evaluation_override="fixture approval", review_file=write_review_artifact(tmp_path))
    store.fail_next_smoke = True

    with pytest.raises(PublicationError, match="smoke"):
        pipeline.publish(result.corpus_version)

    assert {row["status"] for row in store.rows} == {"unpublished"}


def test_publish_and_withdraw_keep_audit_metadata(tmp_path):
    store = InMemoryCorpusStore()
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews"), store=store)
    result = pipeline.ingest(write_manifest(tmp_path))
    pipeline.approve(result.corpus_version, reviewer="owner", evaluation_override="fixture approval", review_file=write_review_artifact(tmp_path))

    assert pipeline.publish(result.corpus_version).published_count == result.chunk_count
    assert store.count("status == 'published'") == result.chunk_count
    pipeline.withdraw(result.corpus_version, reason="source correction")

    assert store.count("status == 'published'") == 0
    assert all(row["withdrawal_reason"] == "source correction" for row in store.rows)
    assert store.search("Redis", 5) == []
    assert pipeline.inspect(result.corpus_version)["withdrawal"]["reason"] == "source correction"


def test_publish_rolls_back_when_smoke_check_raises(tmp_path):
    store = RaisingSmokeStore()
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews"), store=store)
    result = pipeline.ingest(write_manifest(tmp_path))
    pipeline.approve(result.corpus_version, reviewer="owner", evaluation_override="fixture approval", review_file=write_review_artifact(tmp_path))

    with pytest.raises(PublicationError, match="previous version restored"):
        pipeline.publish(result.corpus_version)

    assert {row["status"] for row in store.rows} == {"unpublished"}
    report = json.loads((tmp_path / "runtime" / "reports" / "publish-pilot-v1-rollback.json").read_text(encoding="utf-8"))
    assert report["reason"] == "RuntimeError"


def test_json_reports_redact_secret_like_fields(tmp_path):
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews"), store=InMemoryCorpusStore())

    path = pipeline._write_json(
        tmp_path / "runtime" / "report.json",
        {"api_key": "secret-value", "nested": {"Authorization": "Bearer token"}, "safe": "ok"},
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"api_key": "[REDACTED]", "nested": {"Authorization": "[REDACTED]"}, "safe": "ok"}


def test_approval_override_requires_auditable_reason(tmp_path):
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews"), store=InMemoryCorpusStore())
    result = pipeline.ingest(write_manifest(tmp_path))

    review_file = write_review_artifact(tmp_path)
    with pytest.raises(PublicationError, match="at least 8"):
        pipeline.approve(result.corpus_version, reviewer="owner", evaluation_override="short", review_file=review_file)


def test_ingest_writes_per_document_stage_artifacts_and_reuses_them(tmp_path):
    store = InMemoryCorpusStore()
    runtime = tmp_path / "runtime"
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=runtime), store=store)
    manifest = write_manifest(tmp_path)

    first = pipeline.ingest(manifest)
    batch_dir = runtime / "runs" / first.batch_id
    document_dir = batch_dir / "documents" / "redis-persistence"
    assert (document_dir / "parsed.json").exists()
    assert (document_dir / "parents.json").exists()
    assert (document_dir / "chunks.jsonl").exists()
    assert (document_dir / "status.json").exists()

    parsed_mtime = (document_dir / "parsed.json").stat().st_mtime_ns
    second = pipeline.ingest(manifest)
    assert second.batch_id == first.batch_id
    assert (document_dir / "parsed.json").stat().st_mtime_ns == parsed_mtime
    assert store.count() == first.chunk_count


def test_versioned_yaml_review_artifact_is_required_when_supplied(tmp_path):
    store = InMemoryCorpusStore()
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews"), store=store)
    result = pipeline.ingest(write_manifest(tmp_path))
    review_file = tmp_path / "reviews" / "review.yaml"
    review_file.parent.mkdir(exist_ok=True)
    review_file.write_text(
        "corpus_version: pilot-v1\nreviewer: owner\nreviewed_at: '2026-08-27'\ndecision: approved\ndecision_reason: fixture review\nsamples:\n  - query_id: q1\n    chunk_id: c1\n",
        encoding="utf-8",
    )

    approval_path = pipeline.approve(result.corpus_version, reviewer="owner", evaluation_override="fixture approval", review_file=review_file)
    approval = pipeline.registry.approval(result.corpus_version)
    assert approval["review_artifact"]["path"] == str(review_file.resolve())
    assert approval_path.exists()


def test_versioned_yaml_review_artifact_mismatch_is_blocked(tmp_path):
    pipeline = CorpusPipeline(CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews"), store=InMemoryCorpusStore())
    result = pipeline.ingest(write_manifest(tmp_path))
    review_file = tmp_path / "reviews" / "review.yaml"
    review_file.parent.mkdir(exist_ok=True)
    review_file.write_text("corpus_version: other\nreviewer: owner\nreviewed_at: '2026-08-27'\ndecision: approved\ndecision_reason: fixture review\nsamples: [{query_id: q1}]\n", encoding="utf-8")

    with pytest.raises(PublicationError, match="mismatch"):
        pipeline.approve(result.corpus_version, reviewer="owner", evaluation_override="fixture approval", review_file=review_file)


def test_public_lifecycle_does_not_mutate_user_business_resources(tmp_path, monkeypatch):
    """Public corpus governance must remain isolated from user-owned state."""
    business_state = {
        "knowledge_documents": [{"id": 11, "user_id": 7, "status": "ready"}],
        "quiz_sessions": [{"quiz_id": "quiz-existing", "user_id": 7}],
        "quiz_progress": [{"quiz_id": "quiz-existing", "current_index": 2}],
        "generated_images": [{"question_id": "q1", "url": "https://cos.example/q1.png"}],
        "avatars": [{"user_id": 7, "url": "https://cos.example/avatar.png"}],
        "reports": [{"quiz_id": "quiz-finished", "score": 5}],
    }
    before = deepcopy(business_state)

    def forbidden_business_access(*_args, **_kwargs):
        raise AssertionError("public corpus lifecycle accessed a user-owned store")

    monkeypatch.setattr("aiomysql.create_pool", forbidden_business_access)
    monkeypatch.setattr("app.services.knowledge_service.get_vector_store", forbidden_business_access)

    store = InMemoryCorpusStore()
    config = CorpusConfig(runtime_root=tmp_path / "runtime", review_root=tmp_path / "reviews")
    pipeline = CorpusPipeline(config, store=store)

    first = pipeline.ingest(write_manifest(tmp_path))
    pipeline.approve(
        first.corpus_version,
        reviewer="owner",
        evaluation_override="fixture approval",
        review_file=write_review_artifact(tmp_path),
    )
    pipeline.publish(first.corpus_version)

    manifest = write_manifest(tmp_path)
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        .replace("manifest_version: pilot-v1", "manifest_version: pilot-v2")
        .replace("document_version: '7.4'", "document_version: '7.4.1'")
        .replace("target_corpus_version: pilot-v1", "target_corpus_version: pilot-v2"),
        encoding="utf-8",
    )
    second = pipeline.ingest(manifest)
    pipeline.approve(
        second.corpus_version,
        reviewer="owner",
        evaluation_override="fixture approval",
        review_file=write_review_artifact(tmp_path, corpus_version="pilot-v2"),
    )
    pipeline.publish(second.corpus_version)

    assert store.count("corpus_version == 'pilot-v1' and status == 'inactive'") == first.chunk_count
    assert store.count("corpus_version == 'pilot-v2' and status == 'published'") == second.chunk_count
    pipeline.withdraw(second.corpus_version, reason="fixture isolation verification")
    assert store.count("corpus_version == 'pilot-v2' and status == 'withdrawn'") == second.chunk_count
    assert business_state == before

