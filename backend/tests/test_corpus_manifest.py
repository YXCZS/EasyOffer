from __future__ import annotations

import pytest

from app.corpus.manifest import ManifestError, load_manifest


def test_manifest_resolves_local_path_and_preserves_governance_fields(tmp_path):
    source = tmp_path / "redis.md"
    source.write_text("# Redis\n\nRedis persistence details.", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        """manifest_version: pilot-v1
sources:
  - document_id: redis-official
    path: redis.md
    source_name: Redis official documentation
    source_url: https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/
    technology: Redis
    role_tags: [backend, general]
    document_version: '7.4'
    language: zh-CN
    content_type: markdown
    license_status: approved
    target_corpus_version: pilot-v1
    retrieved_at: '2026-08-27'
""",
        encoding="utf-8",
    )

    loaded = load_manifest(manifest)

    assert loaded.manifest_version == "pilot-v1"
    assert loaded.sources[0].resolved_path == source.resolve()
    assert loaded.sources[0].publishable is True
    assert loaded.sources[0].role_tags == ["backend", "general"]


def test_manifest_rejects_duplicate_identity_and_missing_location(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        """manifest_version: pilot-v1
sources:
  - &item
    document_id: duplicate
    source_name: duplicated source
    technology: Redis
    role_tags: [backend]
    document_version: v1
    language: zh-CN
    content_type: markdown
    license_status: local-evaluation-only
    target_corpus_version: pilot-v1
  - *item
""",
        encoding="utf-8",
    )

    with pytest.raises(ManifestError):
        load_manifest(manifest)


def test_local_evaluation_source_can_be_previewed_but_not_published(tmp_path):
    source = tmp_path / "mysql.md"
    source.write_text("MySQL interview notes", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        """manifest_version: pilot-v1
sources:
  - document_id: mysql-notes
    path: mysql.md
    source_name: local notes
    technology: MySQL
    role_tags: [backend]
    document_version: v1
    language: zh-CN
    content_type: markdown
    license_status: local-evaluation-only
    target_corpus_version: pilot-v1
""",
        encoding="utf-8",
    )

    source_entry = load_manifest(manifest).sources[0]

    assert source_entry.publishable is False

