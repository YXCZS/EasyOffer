# EasyOffer RAG Retrieval

EasyOffer uses a production-style two-stage retrieval pipeline on Milvus
Standalone (and the same schema is compatible with Milvus Distributed):

```text
query
  -> Milvus native dense + BM25 hybrid recall (top 50 per route)
  -> Milvus RRFRanker fusion (k=60)
  -> DashScope TextReRank (top 8)
  -> parent chunk recovery
  -> DeepSeek generation
```

`MILVUS_NATIVE_HYBRID_ENABLED=true` is the production setting. Native
collections contain a `text` field, a BM25 Function output `sparse` field,
and a sparse inverted index. The old dense-only collections are retained only
as a migration backup and are not queried by the application.

The one-time migration helper is `python scripts/migrate_milvus_hybrid.py`.
It reads the old collections without deleting them, writes the native
collections, and can be removed after the backup retention period.

## Configuration

```dotenv
MILVUS_DENSE_RECALL_K=50
MILVUS_SPARSE_RECALL_K=50
MILVUS_FETCH_K_MAX=200
MILVUS_RRF_K=60
MILVUS_RERANK_ENABLED=true
MILVUS_RERANK_MODEL=gte-rerank-v2
MILVUS_RERANK_TOP_K=8
DASHSCOPE_API_KEY=...
```

Milvus' BM25 Function analyzes the `text` field and builds the sparse inverted
index inside Standalone. This keeps lexical retrieval close to the data and
avoids pulling the full corpus into the application process. Technical
identifiers and Chinese terms are therefore handled by the configured Milvus
analyzer rather than an application-side `rank-bm25` index.

Milvus RRFRanker uses `sum(1 / (k + rank))`, so dense and lexical scores do
not need unsafe normalization. DashScope's official `TextReRank.call` is the
default second-stage cross-encoder/API reranker. If the reranker is
unavailable or fails, the service returns the Milvus fused order and logs
`reranker_unavailable` or `reranker_failed`.

The public adapter applies `status=published` when no lifecycle status is
explicitly supplied. Candidate and inactive versions remain queryable only by
release/evaluation tooling. `MILVUS_FETCH_K_MAX` bounds per-route prefetch
depth; the effective value is the maximum of dense/sparse recall and requested
top-k, capped by this limit.

## Accuracy Evaluation

The benchmark must distinguish document hit from answer hit. For every query record top-k text, source, section, parent id, dense rank, BM25 rank, RRF score, rerank score, and a human/label-based `answers_question` flag. Report Recall@5, Hit@1, Hit@3, MRR, nDCG@5, content precision, source traceability, and p50/p95 latency.

Recommended comparison is dense-only, native dense+BM25+RRF, and native
dense+BM25+RRF+DashScope reranker on the same published corpus and query
labels. Do not compare raw scores from different reranker providers.
