from app.services.knowledge_service import MilvusVectorStore


class FakeDoc:
    def __init__(self, owner, role="backend", status="published", document_id="doc"):
        self.page_content = "Redis persistence"
        self.metadata = {"owner_id": owner, "role_tags": f"|{role}|", "status": status, "document_id": document_id}


class FakeStore:
    def __init__(self):
        self.expr = None
        self.added_documents = []
        self.added_ids = []

    def similarity_search_with_relevance_scores(self, query, k=4, **kwargs):
        self.expr = kwargs.get("expr")
        return [(FakeDoc(7), 0.9), (FakeDoc(8, role="frontend", status="unpublished"), 0.8)]

    def add_documents(self, documents, ids):
        self.added_documents = documents
        self.added_ids = ids

    def upsert(self, documents, ids):
        self.added_documents = documents
        self.added_ids = ids


def test_private_milvus_search_enforces_owner_scope(monkeypatch):
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_retrieval_top_k", 5)
    store = MilvusVectorStore(7)
    fake = FakeStore()
    store._store = fake
    rows = store.search("Redis", 5)
    assert len(rows) == 1
    assert "owner_id == 7" in fake.expr


def test_public_milvus_search_filters_published_role(monkeypatch):
    store = MilvusVectorStore(public=True)
    fake = FakeStore()
    store._store = fake
    rows = store.search("Redis", 5, role="backend", published_only=True)
    assert len(rows) == 1
    assert "status == 'published'" in fake.expr


def test_milvus_adapter_declares_configured_cosine_index(monkeypatch):
    import sys
    import types

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_metric_type", "COSINE")
    captured = {}

    class FakeMilvus:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "langchain_milvus", types.SimpleNamespace(Milvus=FakeMilvus))
    monkeypatch.setitem(
        sys.modules,
        "pymilvus",
        types.SimpleNamespace(connections=types.SimpleNamespace(has_connection=lambda alias: True)),
    )

    MilvusVectorStore(public=True)._get()

    assert captured["index_params"] == {"index_type": "AUTOINDEX", "metric_type": "COSINE"}
    assert captured["search_params"] == {"metric_type": "COSINE", "params": {}}


def test_public_upsert_embeds_enriched_text_and_retains_original_evidence():
    store = MilvusVectorStore(public=True)
    fake = FakeStore()
    store._store = fake

    store.upsert_public_chunks([
        {
            "chunk_id": "chunk-1",
            "document_id": "redis-doc",
            "document_version": "7.4",
            "corpus_version": "pilot-v1",
            "parent_id": "parent-1",
            "technology": "redis",
            "text": "RDB 是 Redis 的快照持久化机制。",
            "embedding_text": "技术：Redis\n标题：RDB 持久化\n正文：RDB 是 Redis 的快照持久化机制。",
            "role_tags": ["backend"],
            "knowledge_type": "qa",
            "document_hash": "document-hash-1",
            "parent_hash": "parent-hash-1",
            "content_hash": "hash-1",
            "license_status": "approved",
            "review_status": "approved",
            "status": "unpublished",
        }
    ])

    assert fake.added_ids == ["chunk-1"]
    document = fake.added_documents[0]
    assert document.page_content.startswith("技术：Redis")
    assert document.metadata["evidence_text"] == "RDB 是 Redis 的快照持久化机制。"
    assert document.metadata["document_hash"] == "document-hash-1"
    assert document.metadata["parent_hash"] == "parent-hash-1"


def test_public_upsert_rejects_incomplete_metadata_before_embedding():
    store = MilvusVectorStore(public=True)
    fake = FakeStore()
    store._store = fake

    import pytest
    with pytest.raises(ValueError, match="metadata incomplete"):
        store.upsert_public_chunks([{"chunk_id": "missing-fields", "text": "facts"}])
    assert fake.added_documents == []


def test_public_upsert_allows_local_evaluation_candidate_only():
    store = MilvusVectorStore(public=True)
    fake = FakeStore()
    store._store = fake
    candidate = {
        "chunk_id": "candidate-1",
        "document_id": "redis-local",
        "document_version": "local-2026-08",
        "corpus_version": "pilot-v1",
        "parent_id": "parent-1",
        "technology": "Redis",
        "text": "RDB 是 Redis 的快照持久化机制。",
        "role_tags": ["backend"],
        "knowledge_type": "qa",
        "document_hash": "document-hash-1",
        "parent_hash": "parent-hash-1",
        "content_hash": "hash-1",
        "license_status": "local-evaluation-only",
        "review_status": "pending",
        "status": "unpublished",
    }

    store.upsert_public_chunks([candidate])

    assert fake.added_ids == ["candidate-1"]
    assert fake.added_documents[0].metadata["status"] == "unpublished"
    assert fake.added_documents[0].metadata["license_status"] == "local-evaluation-only"

    candidate["chunk_id"] = "candidate-2"
    candidate["status"] = "published"
    import pytest

    with pytest.raises(ValueError, match="cannot be published"):
        store.upsert_public_chunks([candidate])


def test_public_parent_lookup_uses_exact_scalar_identity(monkeypatch):
    store = MilvusVectorStore(public=True)
    captured = {}

    def query(filter_expr, *, limit=10000):
        captured["filter"] = filter_expr
        return [
            {"child_index": 1, "evidence_text": "答案"},
            {"child_index": 0, "evidence_text": "问题"},
        ]

    monkeypatch.setattr(store, "query_public_chunks", query)
    rows = store.get_parent_chunks(
        "parent-1",
        document_id="redis-doc",
        document_version="7.4",
        corpus_version="pilot-v1",
    )

    assert [row["evidence_text"] for row in rows] == ["问题", "答案"]
    assert "parent_id == 'parent-1'" in captured["filter"]
    assert "document_id == 'redis-doc'" in captured["filter"]
    assert "document_version == '7.4'" in captured["filter"]
    assert "corpus_version == 'pilot-v1'" in captured["filter"]
