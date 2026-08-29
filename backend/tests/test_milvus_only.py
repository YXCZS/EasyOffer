from app.services.knowledge_service import MilvusVectorStore, get_public_vector_store, get_vector_store


def test_private_vector_store_is_always_milvus(monkeypatch):
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_enabled", False)
    assert isinstance(get_vector_store(42), MilvusVectorStore)


def test_public_vector_store_requires_enabled_milvus(monkeypatch):
    settings = __import__("app.core.config", fromlist=["get_settings"]).get_settings()
    monkeypatch.setattr(settings, "milvus_enabled", False)
    try:
        get_public_vector_store()
    except RuntimeError as exc:
        assert "Milvus" in str(exc)
    else:
        raise AssertionError("disabled Milvus must reject public retrieval")
