"""Compare dense-only, native RRF and native RRF + DashScope retrieval.

The dense-only baseline deliberately searches the ``vector`` field of the
native collection directly, so the comparison remains possible after the old
dense-only collection has been retired.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.core.config import get_settings
from app.corpus.evaluation import BenchmarkQuery, load_benchmark
from app.services.knowledge_service import EmbeddingProvider, MilvusVectorStore


@contextmanager
def count_embedding_calls():
    """Count provider calls for one benchmark mode without changing runtime code."""
    counts = {"embed_query": 0, "embed_documents": 0}
    original_query = EmbeddingProvider.embed_query
    original_documents = EmbeddingProvider.embed_documents

    def counted_query(self, text):
        counts["embed_query"] += 1
        return original_query(self, text)

    def counted_documents(self, texts):
        counts["embed_documents"] += 1
        return original_documents(self, texts)

    EmbeddingProvider.embed_query = counted_query
    EmbeddingProvider.embed_documents = counted_documents
    try:
        yield counts
    finally:
        EmbeddingProvider.embed_query = original_query
        EmbeddingProvider.embed_documents = original_documents


def _expr(query: BenchmarkQuery, store: MilvusVectorStore, corpus_version: str, status: str) -> str:
    return store._scope_expr(role=query.role, corpus_version=corpus_version, status=status)


def dense_only_search(store: MilvusVectorStore, query: BenchmarkQuery, k: int, corpus_version: str, status: str) -> list[Any]:
    settings = get_settings()
    client = store._milvus_client()
    vector = EmbeddingProvider().embed_query(query.query)
    raw = client.search(
        collection_name=store.collection_name,
        data=[vector],
        anns_field="vector",
        filter=_expr(query, store, corpus_version, status),
        limit=k,
        output_fields=["*"],
        search_params={"metric_type": settings.milvus_metric_type, "params": {}},
    )
    rows = []
    for hit in (raw[0] if raw else []):
        entity = dict(hit.get("entity") or {})
        entity.setdefault("chunk_id", hit.get("id"))
        rows.append((Document(page_content=str(entity.get("text") or entity.get("evidence_text") or ""), metadata=entity), float(hit.get("distance", 0.0))))
    return rows


def run_mode(mode: str, benchmark: Any, corpus_version: str, status: str, top_k: int, limit: int | None) -> dict[str, Any]:
    settings = get_settings()
    settings.milvus_native_hybrid_enabled = True
    settings.milvus_rerank_enabled = mode == "native_rrf_dashscope"
    store = MilvusVectorStore(public=True)
    rows = []
    selected = benchmark.queries[:limit] if limit else benchmark.queries
    with count_embedding_calls() as embedding_calls:
        for query in selected:
            started = time.perf_counter()
            hits = dense_only_search(store, query, top_k, corpus_version, status) if mode == "dense_only" else store.search(query.query, top_k, role=query.role, corpus_version=corpus_version, status=status)
            stats = dict(getattr(store, "last_retrieval_stats", {}) or {})
            hit_metadata = [dict(getattr(doc, "metadata", {}) or {}) for doc, _ in hits]
            rows.append({
                "query_id": query.query_id,
                "latency_ms": (time.perf_counter() - started) * 1000,
                "hit_ids": [str(getattr(doc, "metadata", {}).get("parent_id") or getattr(doc, "metadata", {}).get("chunk_id") or "") for doc, _ in hits],
                "milvus_candidates": int(stats.get("milvus_candidates", len(hits))),
                "rrf_candidates": int(stats.get("rrf_candidates", len(hits))),
                "rerank_ms": round(float(stats.get("rerank_ms", 0.0)), 3),
                "rerank_status": str(stats.get("rerank_status", "not_applicable")),
                "traceable_hits": sum(1 for metadata in hit_metadata if metadata.get("source_name") or metadata.get("source_url") or metadata.get("citation")),
                "relevant_gain": max((int(query.relevance.get(hit_id, 0)) for hit_id in [str(getattr(doc, "metadata", {}).get("parent_id") or getattr(doc, "metadata", {}).get("chunk_id") or "") for doc, _ in hits]), default=0),
            })
    latencies = [item["latency_ms"] for item in rows]
    hits_at_k = []
    reciprocal_ranks = []
    ndcgs = []
    recalls = []
    for item, query in zip(rows, selected):
        seen_ids: set[str] = set()
        gains = []
        for hit_id in item["hit_ids"][:top_k]:
            if hit_id in seen_ids:
                gains.append(0)
            else:
                seen_ids.add(hit_id)
                gains.append(int(query.relevance.get(hit_id, 0)))
        relevant = [index + 1 for index, gain in enumerate(gains) if gain > 0]
        hits_at_k.append(1.0 if relevant else 0.0)
        reciprocal_ranks.append(1.0 / relevant[0] if relevant else 0.0)
        dcg = sum(((2**gain) - 1) / math.log2(index + 2) for index, gain in enumerate(gains))
        ideal = sorted((int(value) for value in query.relevance.values()), reverse=True)[:top_k]
        idcg = sum(((2**gain) - 1) / math.log2(index + 2) for index, gain in enumerate(ideal))
        ndcgs.append(min(1.0, dcg / idcg) if idcg else 0.0)
        expected = {key for key, value in query.relevance.items() if int(value) > 0}
        recalls.append(len(expected.intersection(item["hit_ids"][:top_k])) / len(expected) if expected else 0.0)
    return {
        "mode": mode,
        "samples": len(rows),
        "p50_latency_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
        "p95_latency_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else 0.0,
        "hit_at_k": round(statistics.fmean(hits_at_k), 4) if hits_at_k else 0.0,
        "mrr_at_k": round(statistics.fmean(reciprocal_ranks), 4) if reciprocal_ranks else 0.0,
        "ndcg_at_k": round(statistics.fmean(ndcgs), 4) if ndcgs else 0.0,
        "recall_at_k": round(statistics.fmean(recalls), 4) if recalls else 0.0,
        "answer_relevancy_proxy": round(statistics.fmean(1.0 if item["relevant_gain"] > 0 else 0.0 for item in rows), 4) if rows else 0.0,
        "source_traceability_rate": round(sum(item["traceable_hits"] for item in rows) / max(1, sum(len(item["hit_ids"]) for item in rows)), 4) if rows else 0.0,
        "queries": rows,
        "collection": store.collection_name,
        "rrf_k": settings.milvus_rrf_k,
        "dense_recall_k": settings.milvus_dense_recall_k,
        "sparse_recall_k": settings.milvus_sparse_recall_k,
        "embedding_calls": embedding_calls,
        "milvus_candidate_count": round(statistics.fmean(item["milvus_candidates"] for item in rows), 2) if rows else 0.0,
        "rrf_candidate_count": round(statistics.fmean(item["rrf_candidates"] for item in rows), 2) if rows else 0.0,
        "rerank_p50_ms": round(statistics.median([item["rerank_ms"] for item in rows]), 2) if rows else 0.0,
        "rerank_p95_ms": round(sorted([item["rerank_ms"] for item in rows])[max(0, int(len(rows) * 0.95) - 1)], 2) if rows else 0.0,
        "rerank_status_counts": {status: sum(1 for item in rows if item["rerank_status"] == status) for status in sorted({item["rerank_status"] for item in rows})},
        "rerank_degradation_rate": round(sum(1 for item in rows if item["rerank_status"] in {"failed", "unavailable"}) / len(rows), 4) if rows else 0.0,
        "request_error_rate": 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", default="corpus/benchmarks/full-authorized-v1.yaml")
    parser.add_argument("--corpus-version", default="full-authorized-v1")
    parser.add_argument("--status", default="published")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None, help="run only the first N queries")
    parser.add_argument("--output", default="data/milvus-benchmark-latest.json")
    args = parser.parse_args()
    benchmark = load_benchmark(args.benchmark)
    report = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_revision": os.popen("git rev-parse HEAD 2>NUL").read().strip() or "unknown",
        "benchmark_version": benchmark.benchmark_version,
        "embedding_model": benchmark.embedding_model,
        "corpus_version": args.corpus_version,
        "status": args.status,
        "modes": [run_mode(mode, benchmark, args.corpus_version, args.status, args.top_k, args.limit) for mode in ("dense_only", "native_rrf", "native_rrf_dashscope")],
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(target), "modes": [{"mode": item["mode"], "samples": item["samples"], "p50_latency_ms": item["p50_latency_ms"], "p95_latency_ms": item["p95_latency_ms"]} for item in report["modes"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
