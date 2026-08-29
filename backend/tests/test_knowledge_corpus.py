import pytest

from app.services.knowledge_corpus import ingest_public_document, review_public_chunks
from app.services.knowledge_shadow import compare_retrieval
from app.services.topic_service import prepare_topic


def test_public_ingestion_is_deterministic_and_unpublished_by_default(monkeypatch):
    result = ingest_public_document("Redis persistence uses RDB snapshots and AOF append-only logs. " * 4, source_name="Redis docs", technology="Redis", role_tags=["backend"])
    assert result.status == "unpublished"
    assert result.chunks
    assert all(chunk["status"] == "unpublished" for chunk in result.chunks)
    assert result.document_id == ingest_public_document("Redis persistence uses RDB snapshots and AOF append-only logs. " * 4, source_name="Redis docs").document_id
    assert review_public_chunks(result.chunks) == (True, None)


def test_public_review_rejects_missing_source():
    assert review_public_chunks([{"text": "facts"}])[0] is False


def test_legacy_public_ingestion_cannot_publish_without_governed_pipeline():
    with pytest.raises(ValueError, match="governed corpus pipeline"):
        ingest_public_document(
            "Redis persistence uses RDB snapshots and AOF append-only logs. " * 4,
            source_name="Redis docs",
            publish=True,
        )


def test_topic_preparation_preserves_identifiers_and_detects_urls():
    result = prepare_topic("我想学习 Redis 持久化, RDB", mode="normal")
    assert "Redis" in result.canonical_topic
    assert result.subtopics
    assert prepare_topic("https://example.com/docs").is_url is True


def test_shadow_compare_reports_agreement_and_latency():
    class Store:
        def search(self, query, k):
            class Doc:
                metadata = {"content_hash": "same"}
            return [(Doc(), 0.8)]
    result = compare_retrieval(Store(), Store(), ["RAG"])
    assert result["recall_agreement"] == 1.0
    assert result["validation_ready"] is True
