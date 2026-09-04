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


def test_private_upsert_preserves_structured_chunk_metadata():
    store = MilvusVectorStore(7)
    fake = FakeStore()
    store._store = fake

    store.upsert_document("doc-1", "notes.pdf", [{
        "chunk_id": "chunk-1",
        "chunk_index": 0,
        "text": "retrieval route",
        "embedding_text": "Structure type: table\nretrieval route",
        "content_hash": "content-hash",
        "document_hash": "document-hash",
        "parent_hash": "parent-hash",
        "parent_id": "parent-1",
        "parent_type": "table",
        "knowledge_type": "table",
        "section_path": ["RAG", "Routing"],
        "page_start": 2,
        "page_end": 2,
        "bbox": [1, 2, 3, 4],
        "mineru_node_path": "1.3",
        "technology": "RAG",
        "role_tags": ["ai"],
        "corpus_version": "personal",
        "language": "zh-CN",
        "license_status": "approved",
        "structure_confidence": 0.99,
    }])

    document = fake.added_documents[0]
    assert document.page_content.startswith("Structure type: table")
    assert document.metadata["parent_id"] == "parent-1"
    assert document.metadata["knowledge_type"] == "table"
    assert document.metadata["section_path"] == "RAG > Routing"
    assert document.metadata["bbox"] == "[1, 2, 3, 4]"
    assert document.metadata["technology"] == "RAG"
    assert document.metadata["role_tags"] == "|ai|"


def test_private_upsert_and_delete_always_include_owner_scope():
    store = MilvusVectorStore(42)

    class ScopedFake(FakeStore):
        def __init__(self):
            super().__init__()
            self.deleted_expr = None

        def delete(self, *, expr):
            self.deleted_expr = expr

    fake = ScopedFake()
    store._store = fake
    store.upsert_document("doc-owner-42", "notes.md", [{
        "chunk_id": "chunk-owner-42", "chunk_index": 0, "text": "owner scoped text", "content_hash": "h",
    }])
    store.delete_document("doc-owner-42")
    assert "owner_id == 42" in fake.deleted_expr
    assert "document_id == 'doc-owner-42'" in fake.deleted_expr


def test_public_milvus_search_filters_published_role(monkeypatch):
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    store = MilvusVectorStore(public=True)
    fake = FakeStore()
    store._store = fake
    rows = store.search("Redis", 5, role="backend", published_only=True)
    assert len(rows) == 1
    assert "status == 'published'" in fake.expr


def test_public_search_defaults_to_published_status(monkeypatch):
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_native_hybrid_enabled", False)
    store = MilvusVectorStore(public=True)
    fake = FakeStore()
    store._store = fake
    rows = store.search("Redis", 5)
    assert "status == 'published'" in fake.expr
    assert len(rows) == 1


def test_public_search_overfetches_when_role_filter_falls_back(monkeypatch):
    class FallbackStore(FakeStore):
        def similarity_search_with_relevance_scores(self, query, k=4, **kwargs):
            self.requested_k = k
            self.expr = kwargs.get("expr")
            if "like" in (self.expr or ""):
                raise RuntimeError("LIKE unsupported")
            rows = []
            for index in range(5):
                rows.append((FakeDoc(0, role="frontend"), 0.95 - index * 0.01))
            rows.append((FakeDoc(0, role="backend"), 0.70))
            return rows

    store = MilvusVectorStore(public=True)
    fake = FallbackStore()
    store._store = fake
    rows = store.search("Redis persistence", 1, role="backend", published_only=True)

    assert len(rows) == 1
    assert rows[0][0].metadata["role_tags"] == "|backend|"
    assert fake.requested_k >= 20


def test_public_search_applies_min_score_before_ranking(monkeypatch):
    class ScoreStore(FakeStore):
        def similarity_search_with_relevance_scores(self, query, k=4, **kwargs):
            self.expr = kwargs.get("expr")
            return [
                (FakeDoc(0, role="backend"), 0.20),
                (FakeDoc(0, role="backend"), 0.80),
            ]

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_rerank_enabled", False)
    monkeypatch.setattr(settings, "milvus_public_min_score", 0.25)
    store = MilvusVectorStore(public=True)
    fake = ScoreStore()
    store._store = fake
    rows = store.search("Redis", 5, role="backend", published_only=True)
    assert [score for _, score in rows] == [0.80]


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


def test_milvus_adapter_keeps_lite_schema_dense_only(monkeypatch):
    import sys
    import types

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_vector_dimension", 8)
    captured = {}

    class FakeMilvus:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "langchain_milvus", types.SimpleNamespace(Milvus=FakeMilvus))
    monkeypatch.setitem(sys.modules, "pymilvus", types.SimpleNamespace(connections=types.SimpleNamespace(has_connection=lambda alias: True)))

    MilvusVectorStore(public=True)._get()

    assert captured["vector_schema"] == {"dim": 8}
    assert "builtin_function" not in captured
    assert captured["search_params"]["metric_type"] == "COSINE"


def test_milvus_adapter_native_hybrid_declares_bm25_function(monkeypatch):
    import sys
    import types

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_native_hybrid_enabled", True)
    monkeypatch.setattr(settings, "milvus_vector_dimension", 8)
    captured = {}

    class FakeBM25:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeMilvus:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "langchain_milvus",
        types.SimpleNamespace(Milvus=FakeMilvus, BM25BuiltInFunction=FakeBM25),
    )
    monkeypatch.setitem(
        sys.modules,
        "pymilvus",
        types.SimpleNamespace(connections=types.SimpleNamespace(has_connection=lambda alias: True)),
    )

    store = MilvusVectorStore(public=True)
    store._get()

    assert store.collection_name.endswith("_hybrid_v2")
    assert captured["vector_field"] == ["vector", "sparse"]
    assert captured["builtin_function"].kwargs["input_field_names"] == "text"
    assert captured["builtin_function"].kwargs["output_field_names"] == "sparse"
    assert captured["search_params"][1]["metric_type"] == "BM25"


def test_native_search_passes_explicit_rrf_and_broad_fetch_k(monkeypatch):
    from langchain_core.documents import Document

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_native_hybrid_enabled", True)
    monkeypatch.setattr(settings, "milvus_rerank_enabled", False)
    monkeypatch.setattr(settings, "milvus_rrf_k", 77)
    monkeypatch.setattr(settings, "milvus_dense_recall_k", 31)
    monkeypatch.setattr(settings, "milvus_sparse_recall_k", 47)
    monkeypatch.setattr(settings, "milvus_fetch_k_max", 100)

    class NativeStore:
        def __init__(self):
            self.calls = []

        def similarity_search_with_score(self, query, **kwargs):
            self.calls.append((query, kwargs))
            return [(Document(page_content="exact RRF", metadata={"chunk_id": "native", "status": "published"}), 0.8)]

    store = MilvusVectorStore(public=True)
    fake = NativeStore()
    store._store = fake

    rows = store.search("exact", 5, published_only=True)

    assert len(rows) == 1
    kwargs = fake.calls[0][1]
    assert kwargs["fetch_k"] == 47
    ranker = kwargs["reranker"]
    assert getattr(ranker, "params", {}).get("strategy") == "rrf" or getattr(ranker, "_params", {}).get("strategy") == "rrf"
    assert getattr(ranker, "params", {}).get("k") == 77 or getattr(ranker, "_params", {}).get("k") == 77


def test_native_search_does_not_build_application_bm25(monkeypatch):
    from langchain_core.documents import Document

    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_native_hybrid_enabled", True)
    monkeypatch.setattr(settings, "milvus_rerank_enabled", False)
    monkeypatch.setattr(settings, "milvus_dense_recall_k", 12)
    monkeypatch.setattr(settings, "milvus_sparse_recall_k", 12)

    class NativeStore:
        def similarity_search_with_score(self, query, **kwargs):
            return [(Document(page_content="native", metadata={"chunk_id": "native", "status": "published"}), 0.9)]

    store = MilvusVectorStore(public=True)
    store._store = NativeStore()
    assert store.search("native", 3, published_only=True)


def test_native_search_logs_failure_type_without_query_or_secret(monkeypatch, caplog):
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_native_hybrid_enabled", True)

    class BrokenStore:
        def similarity_search_with_score(self, query, **kwargs):
            raise RuntimeError("connection failed token=secret-value")

    store = MilvusVectorStore(public=True)
    store._store = BrokenStore()
    with caplog.at_level("WARNING"):
        assert store.search("private user document secret-value", 2, published_only=True) == []
    message = " ".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in message
    assert "secret-value" not in message
    assert "private user document" not in message


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


def test_bm25_tokenizer_preserves_identifiers_and_chinese_bigrams():
    tokens = MilvusVectorStore._tokenize("HashMap 与 ConcurrentHashMap 的底层结构")
    assert "hashmap" in tokens
    assert "concurrenthashmap" in tokens
    assert "底层" in tokens


def test_dashscope_reranker_reorders_rows(monkeypatch):
    import types
    from langchain_core.documents import Document
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_rerank_enabled", True)
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "milvus_rerank_model", "gte-rerank-v2")
    store = MilvusVectorStore(public=True)

    class Result:
        def __init__(self, index, score):
            self.index = index
            self.relevance_score = score

    class Response:
        output = types.SimpleNamespace(results=[Result(1, 0.99), Result(0, 0.10)])

    class TextReRank:
        @staticmethod
        def call(**kwargs):
            assert kwargs["model"] == "gte-rerank-v2"
            return Response()

    monkeypatch.setitem(__import__("sys").modules, "dashscope", types.SimpleNamespace(TextReRank=TextReRank))
    rows = [
        (Document(page_content="generic Redis", metadata={"evidence_text": "generic"}), 0.2),
        (Document(page_content="RDB persistence", metadata={"evidence_text": "target"}), 0.3),
    ]
    ranked = store._rerank_candidates("Redis persistence", rows)
    assert ranked[0][0].page_content == "RDB persistence"
    assert ranked[0][1] == 0.99


def test_reranker_rejects_unrelated_low_score_candidates(monkeypatch):
    import types
    from langchain_core.documents import Document
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_rerank_enabled", True)
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "milvus_rerank_min_score", 0.1)
    store = MilvusVectorStore(public=True)

    class Item:
        index = 0
        relevance_score = 0.01

    class TextReRank:
        @staticmethod
        def call(**kwargs):
            return types.SimpleNamespace(output=types.SimpleNamespace(results=[Item()]))

    monkeypatch.setitem(__import__("sys").modules, "dashscope", types.SimpleNamespace(TextReRank=TextReRank))
    rows = [(Document(page_content="unrelated", metadata={"evidence_text": "unrelated"}), 0.2)]
    assert store._rerank_candidates("Harness Engineering", rows) == []
