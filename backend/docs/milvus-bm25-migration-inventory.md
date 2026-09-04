# Legacy BM25 migration inventory

The production adapter is native Milvus hybrid and does not call the legacy
application BM25 path when `MILVUS_NATIVE_HYBRID_ENABLED=true`.

The online application BM25 path has been removed after the Standalone smoke
test and benchmark gates passed. The remaining migration artifact is isolated:

- `backend/scripts/migrate_milvus_hybrid.py` is an offline migration helper;
  it does not participate in request handling.
- The old Milvus Lite data directory, when present, is retained as a read-only
  operational backup and is not queried by the online adapter.

Static check command:

```text
rg -n "rank-bm25|_bm25_search|_rrf_merge|BM25Okapi" backend/app backend/tests backend/pyproject.toml --glob '!__pycache__/**'
```

Native requests use only `similarity_search_with_score(..., fetch_k=..., reranker=...)`;
they never issue a full-corpus `query()` to construct an application index or
perform a second application-side RRF merge. The migration script may still
read the legacy collection as part of an explicitly invoked offline operation.
