# Milvus Test Observation Window

The test observation window ran the same 38-query golden set through three
retrieval modes, producing 114 real retrieval requests against Milvus
Standalone.

- Request error rate: 0% in all modes.
- DashScope rerank: applied 38/38 times.
- DashScope rerank degradation rate: 0%.
- Selected production path P50/P95: 451.54/580.82 ms.
- Selected path Hit@5: 1.0000; Recall@5: 0.9649; MRR@5: 0.8649; nDCG@5: 0.8521.
- Public/private row counts after the window: 10,936/6.
- Both collections remained loaded with native-hybrid-v2 schema and dense/sparse indexes.

Result: the native hybrid + DashScope configuration is accepted for the local
test environment. This is a controlled local observation window, not a claim
about production traffic volume or long-duration availability.
