# Milvus Native Hybrid Retrieval Benchmark

## Scope

- Benchmark set: `full-authorized-v1`, 38 golden queries
- Corpus: `full-authorized-v1`, `published` only
- Collection: `easyoffer_public_chunks_hybrid_v2`
- Top-k: 5
- Embedding: `text-embedding-v4`
- Native recall depth: dense 50, BM25 50, RRF `k=60`
- Revision: `bb22400f79f11f682246c4f1739e8beceec8ece7`
- Run time (UTC): `2026-09-04T01:32:23Z`

## Results

| Mode | Hit@5 | Recall@5 | MRR@5 | nDCG@5 | Answer relevancy proxy | Source traceability | P50 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense-only | 1.0000 | 1.0000 | 0.9693 | 0.9759 | 1.0000 | 1.0000 | 453.40 ms | 603.07 ms |
| Native Dense + BM25 + RRF | 0.7105 | 0.6447 | 0.6026 | 0.5697 | 0.7105 | 1.0000 | 229.97 ms | 344.27 ms |
| Native RRF + DashScope rerank | 1.0000 | 0.9649 | 0.8649 | 0.8521 | 1.0000 | 1.0000 | 451.54 ms | 580.82 ms |

## Runtime Diagnostics

Each mode issued 38 query embedding calls and no document embedding calls. Native modes returned an average of 50 Milvus candidates per query and retained those candidates for the second stage. All 38 DashScope rerank calls were applied successfully; request error rate and rerank degradation rate were both zero.

## Acceptance Decision

The production path is **native Dense + BM25 + explicit RRF followed by DashScope rerank**. Native RRF alone is fast but does not meet the retrieval quality gate on this corpus. The selected path meets the current quality and traceability gates in this run; the latency baseline to observe after release is P95 580.82 ms.

`answer_relevancy_proxy` means that the top-k result set contains at least one golden-relevant identity. It is a retrieval proxy, not an LLM-as-a-Judge or RAGAS generation-quality score.

The machine-readable source is `backend/data/milvus-benchmark-full.json`. Re-run with:

```text
python scripts/benchmark_milvus_retrieval.py --benchmark corpus/benchmarks/full-authorized-v1.yaml --corpus-version full-authorized-v1 --status published --top-k 5 --output data/milvus-benchmark-full.json
```
