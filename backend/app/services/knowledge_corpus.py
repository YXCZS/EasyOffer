"""Public knowledge-corpus ingestion and review helpers.

Public corpus data is deliberately kept outside MySQL and COS. The helpers
produce deterministic chunk IDs and only publish records that pass review.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from app.services.knowledge_service import get_public_vector_store, split_text


@dataclass
class PublicIngestionResult:
    document_id: str
    chunks: list[dict[str, Any]]
    status: str
    rejected_reason: str | None = None


def clean_public_text(text: str) -> str:
    value = re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", " ", str(text or ""))
    value = re.sub(r"\n{3,}", "\n\n", value)
    return re.sub(r"[ \t]+", " ", value).strip()


def ingest_public_document(
    text: str,
    *,
    source_url: str = "",
    source_name: str = "",
    technology: str = "",
    role_tags: list[str] | None = None,
    version: str = "",
    language: str = "zh-CN",
    document_id: str | None = None,
    publish: bool = False,
) -> PublicIngestionResult:
    if publish:
        raise ValueError(
            "direct publication is disabled; use the governed corpus pipeline"
        )
    cleaned = clean_public_text(text)
    if len(cleaned) < 40:
        return PublicIngestionResult(document_id or "", [], "rejected", "content_too_short")
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
    doc_id = document_id or digest[:24]
    chunks = split_text(cleaned)
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for item in chunks:
        fingerprint = hashlib.sha256(item["text"].strip().encode("utf-8")).hexdigest()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        records.append({
            **item,
            "chunk_id": f"{doc_id}:{item['chunk_index']}:{fingerprint[:12]}",
            "document_id": doc_id,
            "source_id": digest,
            "source_url": source_url,
            "source_name": source_name,
            "technology": technology,
            "role_tags": role_tags or ["general"],
            "version": version,
            "language": language,
            "status": "unpublished",
        })
    if not records:
        return PublicIngestionResult(doc_id, [], "rejected", "no_chunks")
    return PublicIngestionResult(doc_id, records, "unpublished")


def review_public_chunks(chunks: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Apply deterministic pre-review checks before human/ops approval."""
    if not chunks:
        return False, "no_chunks"
    for chunk in chunks:
        if not str(chunk.get("text") or "").strip():
            return False, "empty_chunk"
        if not chunk.get("source_url") and not chunk.get("source_name"):
            return False, "missing_source"
    return True, None


def publish_public_chunks(chunks: list[dict[str, Any]], publish: bool = True) -> int:
    ok, reason = review_public_chunks(chunks)
    if not ok:
        raise ValueError(reason or "quality_review_failed")
    document_hashes = {
        str(chunk.get("document_id") or ""): hashlib.sha256(
            "\n\n".join(
                str(item.get("text") or "")
                for item in chunks
                if str(item.get("document_id") or "") == str(chunk.get("document_id") or "")
            ).encode("utf-8")
        ).hexdigest()
        for chunk in chunks
    }
    updated = [
        {
            **chunk,
            "document_version": chunk.get("document_version") or chunk.get("version") or "legacy",
            "corpus_version": chunk.get("corpus_version") or "legacy",
            "parent_id": chunk.get("parent_id") or chunk.get("chunk_id"),
            "document_hash": chunk.get("document_hash") or document_hashes[str(chunk.get("document_id") or "")],
            "parent_hash": chunk.get("parent_hash") or hashlib.sha256(str(chunk.get("text") or "").encode("utf-8")).hexdigest(),
            "knowledge_type": chunk.get("knowledge_type") or "paragraph",
            "content_hash": chunk.get("content_hash") or hashlib.sha256(str(chunk.get("text") or "").encode()).hexdigest(),
            "license_status": chunk.get("license_status") or "approved",
            "review_status": "approved",
            "status": "published" if publish else "unpublished",
        }
        for chunk in chunks
    ]
    get_public_vector_store().upsert_public_chunks(updated)
    return len(updated)
