"""Backfill dense-only Milvus collections into native BM25 hybrid collections.

The source is read-only. The target collections are created with the current
application schema when ``MILVUS_NATIVE_HYBRID_ENABLED=true``. Run this once
after starting Milvus Standalone, then validate retrieval before switching the
feature flag for the application.

Example:
    python scripts/migrate_milvus_hybrid.py --source-uri http://127.0.0.1:19531
"""

from __future__ import annotations

import argparse
import os
from typing import Any


def _payload(row: dict[str, Any]) -> dict[str, Any] | None:
    """Map an old dynamic-field row to the native hybrid schema."""
    pk = row.get("pk") or row.get("id")
    vector = row.get("vector")
    text = row.get("text") or row.get("evidence_text") or row.get("page_content")
    if not pk or not vector or not text:
        return None
    payload: dict[str, Any] = {
        "pk": str(pk),
        "text": str(text),
        "vector": vector,
    }
    for key, value in row.items():
        if key not in {"pk", "id", "text", "vector", "sparse"}:
            payload[key] = value
    return payload


def migrate_collection(source: Any, target: Any, source_name: str, target_name: str, limit: int, batch_size: int) -> int:
    # Milvus keeps collections released until an explicit load.  This is
    # especially common for the old Lite server used as a migration source.
    if not source.has_collection(source_name):
        return 0
    source.load_collection(source_name)
    rows = source.query(collection_name=source_name, output_fields=["*"], limit=limit)
    payloads = [item for row in rows if (item := _payload(dict(row))) is not None]
    migrated = 0
    for offset in range(0, len(payloads), batch_size):
        batch = payloads[offset:offset + batch_size]
        if batch:
            target.upsert(collection_name=target_name, data=batch)
            migrated += len(batch)
    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--source-token", default="")
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()
    target_uri = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
    if args.source_uri == target_uri:
        raise SystemExit("source-uri and target MILVUS_URI must be different")
    os.environ["MILVUS_NATIVE_HYBRID_ENABLED"] = "true"
    from pymilvus import MilvusClient
    from app.services.milvus_admin import initialize_collections

    initialize_collections()
    source_kwargs = {"uri": args.source_uri}
    if args.source_token:
        source_kwargs["token"] = args.source_token
    source = MilvusClient(**source_kwargs)
    target = MilvusClient(uri=target_uri, token=os.getenv("MILVUS_TOKEN") or None)
    from app.core.config import get_settings

    settings = get_settings()
    suffix = settings.milvus_native_collection_suffix
    pairs = [
        (settings.milvus_public_collection, f"{settings.milvus_public_collection}{suffix}"),
        (settings.milvus_private_collection, f"{settings.milvus_private_collection}{suffix}"),
    ]
    result = {
        target_name: migrate_collection(source, target, source_name, target_name, args.limit, args.batch_size)
        for source_name, target_name in pairs
    }
    print(result)


if __name__ == "__main__":
    main()
