from scripts.migrate_milvus_hybrid import _payload


def test_payload_preserves_text_vector_and_dynamic_metadata():
    payload = _payload({"pk": "c1", "vector": [0.1, 0.2], "evidence_text": "BM25", "status": "published"})
    assert payload == {
        "pk": "c1",
        "text": "BM25",
        "vector": [0.1, 0.2],
        "evidence_text": "BM25",
        "status": "published",
    }


def test_payload_skips_incomplete_rows():
    assert _payload({"pk": "c1", "vector": [0.1]}) is None
