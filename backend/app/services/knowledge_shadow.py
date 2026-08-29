"""Offline retrieval comparison helper for Milvus deployments."""
from __future__ import annotations

import time
from typing import Any


def compare_retrieval(primary_store: Any, secondary_store: Any, queries: list[str], *, k: int = 5) -> dict[str, Any]:
    """Compare two retrieval implementations without coupling to a backend name.

    This is useful when validating a Milvus index or embedding change. Both
    stores must expose ``search(query, k)`` and return ``(Document, score)``
    rows with ``content_hash`` or ``document_id`` metadata.
    """
    rows = []
    agreements = 0.0
    for query in queries:
        started = time.perf_counter()
        primary = primary_store.search(query, k)
        primary_ids = {
            str((getattr(doc, "metadata", None) or {}).get("content_hash")
                or (getattr(doc, "metadata", None) or {}).get("document_id"))
            for doc, _ in primary
        }
        primary_ms = round((time.perf_counter() - started) * 1000, 2)
        started = time.perf_counter()
        secondary = secondary_store.search(query, k)
        secondary_ids = {
            str((getattr(doc, "metadata", None) or {}).get("content_hash")
                or (getattr(doc, "metadata", None) or {}).get("document_id"))
            for doc, _ in secondary
        }
        secondary_ms = round((time.perf_counter() - started) * 1000, 2)
        intersection = len(primary_ids & secondary_ids)
        union = len(primary_ids | secondary_ids)
        agreement = intersection / union if union else 1.0
        agreements += agreement
        rows.append({
            "query": query,
            "primary_count": len(primary),
            "secondary_count": len(secondary),
            "agreement": round(agreement, 4),
            "primary_latency_ms": primary_ms,
            "secondary_latency_ms": secondary_ms,
            "metadata_mismatch": sorted(primary_ids ^ secondary_ids),
        })
    average = agreements / max(1, len(queries))
    return {
        "queries": rows,
        "recall_agreement": round(average, 4),
        "validation_threshold": 0.9,
        "validation_ready": bool(rows) and average >= 0.9,
    }
