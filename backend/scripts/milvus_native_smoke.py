"""Run a reversible native hybrid smoke test against Milvus Standalone.

Usage: ``python scripts/milvus_native_smoke.py`` from ``backend``.
The script writes one temporary document, checks owner isolation and
replacement semantics, then always removes the temporary rows.
"""
from __future__ import annotations

import secrets
import time

from app.core.config import get_settings
from app.services.knowledge_service import MilvusVectorStore
from app.services.milvus_admin import health_check


def main() -> None:
    settings = get_settings()
    if not settings.milvus_native_hybrid_enabled:
        raise SystemExit("MILVUS_NATIVE_HYBRID_ENABLED must be true")
    settings.milvus_rerank_enabled = False
    before = (health_check().collections or {}).get(
        f"{settings.milvus_private_collection}{settings.milvus_native_collection_suffix}",
        {},
    ).get("row_count", 0)
    owner_a = 900_000 + secrets.randbelow(99_999)
    owner_b = owner_a + 1
    document_id = f"smoke-{secrets.token_hex(8)}"
    store_a = MilvusVectorStore(owner_a)
    store_b = MilvusVectorStore(owner_b)

    def chunk(chunk_id: str, text: str) -> dict[str, object]:
        return {
            "chunk_id": chunk_id,
            "chunk_index": 0,
            "text": text,
            "embedding_text": text,
            "content_hash": secrets.token_hex(16),
            "document_hash": "smoke-document",
            "parent_hash": "smoke-parent",
            "parent_id": "smoke-parent",
            "parent_type": "paragraph",
            "knowledge_type": "paragraph",
            "technology": "Milvus",
            "role_tags": ["backend"],
            "page_start": 1,
            "page_end": 1,
        }

    try:
        def wait_for(query: str, expected: bool, *, marker: str | None = None) -> list[object]:
            last: list[object] = []
            for _ in range(12):
                last = store_a.search(query, 3)
                texts = [str(row[0].page_content) for row in last]
                marker_ready = marker is None or any(marker in text for text in texts)
                if bool(last) is expected and marker_ready:
                    return last
                time.sleep(1)
            return last

        store_a.upsert_document(document_id, "smoke.md", [chunk(f"{document_id}-v1", "Milvus native BM25 hybrid smoke marker")])
        own = wait_for("native BM25 hybrid smoke marker", True)
        cross = store_b.search("native BM25 hybrid smoke marker", 3)
        if not own or cross:
            raise AssertionError(f"owner isolation failed own={len(own)} cross={len(cross)}")

        store_a.upsert_document(document_id, "smoke.md", [chunk(f"{document_id}-v2", "Milvus replacement smoke marker")])
        replacement = []
        for _ in range(12):
            replacement = store_a.search("replacement smoke marker", 3)
            texts = [str(row[0].page_content) for row in replacement]
            if replacement and any("replacement smoke marker" in text for text in texts) and all("native BM25" not in text for text in texts):
                break
            time.sleep(1)
        if not replacement or any("native BM25" in str(row[0].page_content) for row in replacement):
            raise AssertionError("document replacement failed")

        store_a.delete_document(document_id)
        if wait_for("replacement smoke marker", False):
            raise AssertionError("document delete failed")
        print("native smoke passed")
    finally:
        try:
            store_a.delete_document(document_id)
        except Exception:
            pass
        after = (health_check().collections or {}).get(
            f"{settings.milvus_private_collection}{settings.milvus_native_collection_suffix}",
            {},
        ).get("row_count", 0)
        if after != before:
            raise RuntimeError(f"private row count not restored: before={before} after={after}")


if __name__ == "__main__":
    main()
