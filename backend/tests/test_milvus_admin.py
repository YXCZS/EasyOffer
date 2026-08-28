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
