# Retrieval Benchmark (2026-08-30)

This smoke benchmark was run against the current published public collection (`easyoffer_public_chunks`, 1,284 published chunks) on the local Milvus Lite instance. Queries covered RAG, HashMap, Spring Boot auto-configuration, message delivery guarantees, Redis persistence, Milvus hybrid retrieval, and an unseen topic (`Harness Engineering`). The content label requires the expected concepts to appear in the returned evidence; the unseen topic is correct only when no local evidence is returned.

| Pipeline | Hit@1 | Hit@3 | Hit@5 | Content coverage | Unseen topic rejected | p50 latency | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense only | 0.67 | 0.67 | 0.67 | 0.75 | 0% | 1.31 s | 1.32 s |
| Dense + BM25 + RRF | 0.83 | 0.83 | 0.83 | 0.83 | 0% | 1.43 s | 1.48 s |
| Dense + BM25 + RRF + DashScope | 0.50 | 0.67 | 0.83 | 0.83 | 100% | 1.70 s | 1.78 s |

Interpretation:

- Application-layer BM25 + standard RRF improves broad recall and content coverage over dense-only without requiring Milvus Standalone.
- DashScope rerank plus a minimum score gate rejects the unseen topic, preventing low-score adjacent documents from being treated as an answer. It also keeps Hit@5 at the best observed value, but the current small benchmark shows lower Hit@1 for multi-intent queries. This is a measured limitation, not hidden as a success claim.
- The message-queue query is intentionally multi-intent. The returned Top-5 contains separate direct evidence for duplicate consumption/idempotency and message loss. The Agentic RAG layer additionally uses bounded compound queries to cover both aspects.

The benchmark is a smoke test, not a statistically significant quality study. Before production rollout, expand the labeled query set and tune `MILVUS_RRF_K`, recall depths, reranker model/instruction, and `MILVUS_RERANK_MIN_SCORE` against Recall@k, MRR, nDCG@k, answer faithfulness, and p95 latency.
