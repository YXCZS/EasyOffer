# Milvus Application Rollback Drill

The drill temporarily set `MILVUS_NATIVE_HYBRID_ENABLED=false` and
`MILVUS_RERANK_ENABLED=false` for one process only. It did not edit persisted
configuration or collection data.

Observed result:

- Collection remained `easyoffer_public_chunks_hybrid_v2`.
- Retrieval mode changed to `dense`.
- Query `RAG技术` returned five published AI-role results.
- Public/private row counts remained 10,936 and 6.
- Both native collections remained loaded and healthy after the process exited.

This proves the emergency rollback changes only the application query path and
does not delete native collections. Normal production configuration remains
`MILVUS_NATIVE_HYBRID_ENABLED=true` with DashScope reranking enabled.
