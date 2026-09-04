from app.services import milvus_admin


class FakeClient:
    def __init__(self):
        self.collections = set()
        self.created = []

    def has_collection(self, name):
        return name in self.collections

    def create_collection(self, **kwargs):
        self.collections.add(kwargs["collection_name"])
        self.created.append(kwargs)

    def load_collection(self, name):
        return None

    def get_server_version(self):
        return "2.6"


def test_initialize_collections_is_idempotent(monkeypatch):
    client = FakeClient()
    settings = milvus_admin.get_settings()
    monkeypatch.setattr(settings, "milvus_vector_dimension", 4)
    monkeypatch.setattr(milvus_admin, "_client", lambda: client)
    first = milvus_admin.initialize_collections()
    second = milvus_admin.initialize_collections()
    assert all(first.values())
    assert not any(second.values())
    assert len(client.created) == 2


def test_health_check_reports_non_sensitive_collection_contract(monkeypatch):
    class DetailedClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.collections = {"easyoffer_public_chunks_hybrid_v2", "easyoffer_private_chunks_hybrid_v2"}

        def get_load_state(self, name):
            return {"state": "Loaded"}

        def describe_collection(self, name):
            return {
                "fields": [
                    {"name": "pk", "params": {}},
                    {"name": "text", "params": {}},
                    {"name": "vector", "params": {"dim": 8}},
                    {"name": "sparse", "params": {}},
                ],
                "functions": [{"name": "text_bm25"}],
            }

        def list_indexes(self, name):
            return ["vector", "sparse"]

        def get_collection_stats(self, name):
            return {"row_count": 3}

    client = DetailedClient()
    settings = milvus_admin.get_settings()
    monkeypatch.setattr(settings, "milvus_vector_dimension", 8)
    monkeypatch.setattr(milvus_admin, "_client", lambda: client)

    health = milvus_admin.health_check()

    assert health.ok is True
    assert health.collections["easyoffer_public_chunks_hybrid_v2"]["schema_version"] == "native-hybrid-v2"
    assert health.collections["easyoffer_public_chunks_hybrid_v2"]["row_count"] == 3
    assert "api_key" not in str(health).lower()


def test_existing_incompatible_native_schema_is_rejected(monkeypatch):
    class IncompatibleClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.collections = {"easyoffer_public_chunks_hybrid_v2"}

        def describe_collection(self, name):
            return {"fields": [{"name": "pk", "params": {}}], "functions": []}

        def list_indexes(self, name):
            return ["vector"]

    client = IncompatibleClient()
    settings = milvus_admin.get_settings()
    monkeypatch.setattr(settings, "milvus_vector_dimension", 8)
    monkeypatch.setattr(milvus_admin, "_client", lambda: client)

    import pytest
    with pytest.raises(ValueError, match="incompatible native schema"):
        milvus_admin.ensure_collection("easyoffer_public_chunks_hybrid_v2")
