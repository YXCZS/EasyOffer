"""Resumable Chroma-to-Milvus migration utilities."""
from __future__ import annotations

import hashlib
from typing import Any


def migrate_chroma_collection(chroma_store: Any, milvus_store: Any, *, batch_size: int = 100, dry_run: bool = False, state: dict[str, Any] | None = None) -> dict[str, Any]:
    collection = getattr(chroma_store, "_collection", None)
    if collection is None:
        raise ValueError("Chroma collection is unavailable")
    payload = collection.get(include=["documents", "metadatas", "ids"]) or {}
    documents = payload.get("documents") or []
    metadatas = payload.get("metadatas") or []
    ids = payload.get("ids") or []
    start = int((state or {}).get("offset", 0))
    records: list[dict[str, Any]] = []
    for index in range(start, min(len(documents), start + max(1, batch_size))):
        text = str(documents[index] or "").strip()
        metadata = dict(metadatas[index] or {}) if index < len(metadatas) else {}
        if not text:
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        records.append({"chunk_id": str(ids[index]) if index < len(ids) else digest, "text": text, "content_hash": digest, **metadata})
    if records and not dry_run:
        milvus_store.upsert_document(records[0].get("document_id", "migrated"), records[0].get("source_name", "migrated"), records)
    next_offset = min(len(documents), start + max(1, batch_size))
    return {"source_count": len(documents), "migrated_count": len(records), "next_offset": next_offset, "complete": next_offset >= len(documents), "dry_run": dry_run, "content_hashes": [item["content_hash"] for item in records]}
