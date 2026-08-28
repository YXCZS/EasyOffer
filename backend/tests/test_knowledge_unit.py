from pathlib import Path

import pytest

from app.services.knowledge_service import KnowledgeValidationError, SecureDocumentStorage, split_text, validate_upload


def test_validate_upload_accepts_supported_files_and_rejects_empty_or_bad_type():
    name, mime = validate_upload("notes.md", "text/markdown", b"# RAG")
    assert name == "notes.md" and mime == "text/markdown"
    with pytest.raises(KnowledgeValidationError):
        validate_upload("notes.exe", "application/octet-stream", b"x")
    with pytest.raises(KnowledgeValidationError):
        validate_upload("notes.md", "text/markdown", b"")


def test_storage_isolated_and_randomized(tmp_path):
    storage = SecureDocumentStorage(str(tmp_path))
    first = storage.save(1, "../../same.md", b"a")
    second = storage.save(1, "same.md", b"b")
    assert Path(first).parent == Path(second).parent == tmp_path / "1"
    assert first != second
    with pytest.raises(KnowledgeValidationError):
        storage.remove(str(tmp_path.parent / "outside.md"))


def test_split_text_has_stable_chunk_ids_and_filters_blank_chunks(monkeypatch):
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "knowledge_chunk_size", 20)
    monkeypatch.setattr(settings, "knowledge_chunk_overlap", 2)
    chunks_a = split_text("RAG is retrieval augmented generation. " * 5)
    chunks_b = split_text("RAG is retrieval augmented generation. " * 5)
    assert chunks_a and [item["chunk_id"] for item in chunks_a] == [item["chunk_id"] for item in chunks_b]
    assert all(item["text"].strip() for item in chunks_a)
