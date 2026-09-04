# Milvus Native Hybrid Operations

## Production contract

EasyOffer production retrieval uses Milvus Standalone/Distributed native
hybrid search. Each request performs dense vector recall and server-side BM25
recall, then Milvus applies an explicit RRF ranker (`k` from
`MILVUS_RRF_K`). DashScope `TextReRank` is optional second-stage precision
ranking. The old Milvus Lite directory is a migration backup only.

Required settings:

```dotenv
MILVUS_URI=http://127.0.0.1:19530
MILVUS_NATIVE_HYBRID_ENABLED=true
MILVUS_DENSE_RECALL_K=50
MILVUS_SPARSE_RECALL_K=50
MILVUS_FETCH_K_MAX=200
MILVUS_RRF_K=60
```

The two `_hybrid_v2` collections must contain `pk`, `text`, `vector` and
`sparse`, a `text_bm25` Function, and `vector`/`sparse` indexes. Public online
queries automatically add `status == 'published'`; release tooling must pass
an explicit lifecycle status to evaluate candidates. Private queries always
add the authenticated `owner_id` expression.

## Initialization and health

Run from either the repository root or `backend`; configuration resolves
`backend/.env` by package path and still allows process environment overrides:

```text
python -m app.services.milvus_admin
python -c "from app.services.milvus_admin import health_check; print(health_check())"
```

Initialization is idempotent. Existing collections are loaded and their native
schema/index contract is checked; incompatible collections fail explicitly.
Health output includes Milvus version, collection existence, loaded state,
schema version, field/index names and row count. It never includes credentials
or document contents.

## Reversible private smoke test

```text
python scripts/milvus_native_smoke.py
```

The script creates a random temporary owner/document, verifies native hybrid
recall, cross-owner isolation, replacement and deletion, then compares the
private collection row count and cleans up in `finally`.

## Application rollback

Set `MILVUS_NATIVE_HYBRID_ENABLED=false` to use dense-only retrieval against
the same `_hybrid_v2` collections. This is an emergency application rollback:
it does not rename, delete, rebuild, or switch back to a retired Lite
collection. Restore `true` after diagnosing the native hybrid path.
