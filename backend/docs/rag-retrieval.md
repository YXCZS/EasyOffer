# EasyOffer RAG Retrieval

EasyOffer uses a production-style two-stage retrieval pipeline that runs in the local Milvus Lite environment:

```text
query
  -> Milvus dense ANN recall (top 50)
  -> application BM25 lexical recall (top 50)
  -> standard RRF fusion (k=60)
  -> DashScope TextReRank / Cohere Rerank (top 8)
  -> parent chunk recovery
  -> DeepSeek generation
```

The `MILVUS_HYBRID_ENABLED` setting means application-layer hybrid retrieval. It does not enable `BM25BuiltInFunction`; that server-side function requires Milvus Standalone or Distributed and is intentionally not used here. The same dense collection therefore works with Milvus Lite and can later be moved to a server deployment without a schema migration.

## Configuration

```dotenv
MILVUS_HYBRID_ENABLED=true
MILVUS_DENSE_RECALL_K=50
MILVUS_SPARSE_RECALL_K=50
MILVUS_RRF_K=60
MILVUS_RERANK_ENABLED=true
MILVUS_RERANK_PROVIDER=dashscope
MILVUS_RERANK_MODEL=gte-rerank-v2
MILVUS_RERANK_TOP_K=8
DASHSCOPE_API_KEY=...
```

`rank-bm25` implements standard Okapi BM25. Chinese text contributes character unigrams and bigrams; technical identifiers such as `HashMap`, `ConcurrentHashMap`, and `Spring Boot` remain searchable as tokens. Indexes are cached per collection and scalar scope and invalidated after upsert/delete.

RRF uses `sum(1 / (k + rank))`, so dense and lexical scores do not need unsafe normalization. DashScope's official `TextReRank.call` is the default second-stage cross-encoder/API reranker. Cohere remains an optional provider. If a reranker is unavailable or fails, the service returns the RRF order and logs `reranker_unavailable` or `reranker_failed`.

## Accuracy Evaluation

The benchmark must distinguish document hit from answer hit. For every query record top-k text, source, section, parent id, dense rank, BM25 rank, RRF score, rerank score, and a human/label-based `answers_question` flag. Report Recall@5, Hit@1, Hit@3, MRR, nDCG@5, content precision, source traceability, and p50/p95 latency.

Recommended comparison is dense-only, dense+BM25+RRF, and dense+BM25+RRF+reranker on the same published corpus and query labels. Do not compare raw scores from different reranker providers.
