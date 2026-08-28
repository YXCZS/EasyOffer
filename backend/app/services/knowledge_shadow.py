"""Offline Chroma/Milvus shadow retrieval comparison."""
from __future__ import annotations

import time
from typing import Any


def compare_retrieval(chroma_store: Any, milvus_store: Any, queries: list[str], *, k: int = 5) -> dict[str, Any]:
    rows = []
    agreements = 0
    for query in queries:
        started = time.perf_counter()
        chroma = chroma_store.search(query, k)
        chroma_ids = {str((getattr(doc, "metadata", None) or {}).get("content_hash") or (getattr(doc, "metadata", None) or {}).get("document_id")) for doc, _ in chroma}
        chroma_ms = round((time.perf_counter() - started) * 1000, 2)
        started = time.perf_counter()
        milvus = milvus_store.search(query, k)
        milvus_ids = {str((getattr(doc, "metadata", None) or {}).get("content_hash") or (getattr(doc, "metadata", None) or {}).get("document_id")) for doc, _ in milvus}
        milvus_ms = round((time.perf_counter() - started) * 1000, 2)
        intersection = len(chroma_ids & milvus_ids)
        union = len(chroma_ids | milvus_ids)
        agreement = intersection / union if union else 1.0
        agreements += agreement
        rows.append({"query": query, "chroma_count": len(chroma), "milvus_count": len(milvus), "agreement": round(agreement, 4), "chroma_latency_ms": chroma_ms, "milvus_latency_ms": milvus_ms, "metadata_mismatch": sorted(chroma_ids ^ milvus_ids)})
    return {"queries": rows, "recall_agreement": round(agreements / max(1, len(queries)), 4), "cutover_threshold": 0.9, "cutover_ready": bool(rows) and agreements / len(rows) >= 0.9}
