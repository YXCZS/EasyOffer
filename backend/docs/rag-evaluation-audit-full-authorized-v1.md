# full-authorized-v1 RAG 评估审计记录

## 审计范围

- 语料版本：`full-authorized-v1`
- 发布状态过滤：`published`
- Golden Dataset：`golden-v2`，100 条
- Top-K：5
- 检索链路：当前生产 Milvus Standalone 混合检索与重排入口
- 基线报告：`data/public-corpus/evaluations/full-authorized-v1-golden-v2-deterministic-v2.json`
- 本记录只陈述真实运行结果；未完成的 RAGAS 全量评估不记为通过。

## 可复现结果

| 指标 | 实测值 |
| --- | ---: |
| Hit@5 | 1.000 |
| MRR@5 | 0.975 |
| nDCG@5 | 0.982 |
| Context Precision（确定性 ID 标注） | 0.708 |
| Context Recall（确定性文本覆盖） | 0.954 |
| 重复结果率（相同 Parent 或相同内容） | 0.020 |
| 角色污染率 | 0.000 |
| 来源可追溯率 | 1.000 |
| Parent 恢复率 | 1.000 |

## 人工抽检

### g-001：RAG 查询扩展

- 第 1 名精确命中目标 Parent，能够直接回答问题。
- 第 2 名“自查询”与查询扩展有语义关系，但不是 Golden 标注 Parent。
- 第 3、4 名是 RAG 分块和提示压缩，只属于同领域背景，不能直接回答。
- 结论：答案证据充分，但 Top-5 尾部有冗余；确定性 Precision=0.2 会低估第 2 名的部分相关性，需结合 RAGAS Context Precision 解读。

### g-017：JDK 与 JRE

- 第 1 名精确命中并完整解释 JDK/JRE 的组成和用途。
- 第 2～5 名分别是动态代理、接口/抽象类、JVM 执行方式和基本类型，不能直接回答问题。
- 结论：首条可用，尾部明显过宽；适合减少最终送入生成模型的上下文数量。

### g-081：操作系统分段与分页

- 第 1 名精确命中并覆盖定义、映射和碎片差异。
- 第 2 名因为“分页”一词召回 MySQL Cursor 分页，属于关键词歧义。
- 第 3 名为 RAG 分块，第 4、5 名为其他操作系统概念，均不能直接回答。
- 结论：存在跨技术域词义污染，最终重排对低分尾部过滤不足。

### g-085：MESI

- 第 1 名精确命中 MESI 四状态及一致性机制。
- 第 2 名是资料导航/推广样板内容，应在入库清洗阶段过滤。
- 第 3～5 名与 MESI 无直接关系，其中两条来自 AI 大模型资料。
- 结论：答案证据充分，但暴露了语料噪声和低分尾部跨域问题。

### g-013：logging write barrier

- 第 1 名精确命中。
- 第 3 名“CMS/G1 如何维持并发正确性”与写屏障强相关，但没有被 Golden ID 标为相关。
- 结论：确定性 ID Precision 对未完整标注的相关 Parent 会产生低估，RAGAS/人工抽检是必要补充。

### g-027：Spring 启动过程代码片段

- 第 1 名命中目标 Parent，第 2 名是同问题的另一份有效资料。
- 第 3、5 名来自同一个 Parent，但由不同 Child 命中，形成重复上下文。
- 该样本的 Context Recall=0.833，为本轮最低值，但核心答案仍在第 1 名。
- 结论：检索返回层需要按 Parent 去重；此前只按 `content_hash` 统计会漏报，评估器现已同时按 Parent 和内容检测重复。

## 基线复跑与漂移

- 同一数据集、语料版本和 Top-K 的复跑保持 Hit@5、MRR、nDCG、Context Precision、Context Recall 完全一致。
- 曾观察到 `g-073` 第 2、3 名互换；两项分数相同，内容集合未改变，属于并列排序抖动。
- 修正重复指标定义后，识别出 10 个样本存在重复 Parent，共占 500 个 Top-K 结果的 2%。该变化是评估器纠错，不是检索链路突然回归。

## 审计结论

1. 当前检索在“核心答案能否进入 Top-5”方面表现稳定，100 条全部命中。
2. 当前问题集中在 Top-5 尾部冗余、相同 Parent 重复、跨技术域词义污染和资料模板噪声。
3. 不能只用 Hit@5 宣称检索完整；Context Precision=0.708 和重复率 0.020 必须保留为真实问题。
4. 在 RAGAS 四指标完成 100 条真实全量评估前，不应宣称生成质量门禁已经通过。

## Full replay audit (2026-09-04)

The real published Milvus Standalone corpus (`full-authorized-v1`, status
`published`) was replayed with all 100 `golden-v2` samples. Milvus smoke
verification found 1,283 published records and returned a published hit.

Replay artifacts:

- `data/public-corpus/evaluations/full-authorized-v1-golden-v2-full-rerun.json`
- `data/public-corpus/evaluations/full-authorized-v1-golden-v2-full-rerun-corrected.json`

Results:

- Retrieval: Hit@5 `1.000`, MRR@5 `0.975`, nDCG@5 `0.982`, deterministic
  Context Precision `0.708`, Context Recall `0.954`, P50/P95 latency
  `501.47/610.24 ms`.
- All 100 samples reached the real production generator and Agent adapter;
  the runner recorded zero runner exceptions.
- RAGAS status is `partial`: 99/100 samples succeeded. DashScope-backed means
  are Faithfulness `0.9566`, Context Recall `0.9424`, Context Precision
  `0.9528`, and Answer Relevancy `0.8050`.
- The only RAGAS failure is `g-093`: the model returned an extra
  `options_order` field rejected by the strict quiz schema. It remains an
  explicit generation failure with no fabricated score.
- The original `quiz_valid_rate=0` was an evaluator defect: answer keys were
  compared directly with option dictionaries. After fixing that mapping and
  re-evaluating persisted real observations, validity is `0.71` (71/100) and
  duplicate rate is `0.0`; the corrected gate still fails honestly because
  knowledge-point coverage failures remain.
- Agent traces show `base_model` fallback with no tool calls and
  `agent_disabled_or_missing_model` for these samples. This process result is
  retained and is not counted as successful Milvus/Tavily routing.

Manual spot checks covered `g-001`, `g-017`, `g-045`, `g-081`, `g-085`,
`g-093`, `g-055`, and `g-030`. Expected document/parent IDs and the published
corpus version were present in the inspected contexts. The comparison command
reported result drift for `g-017` and `g-045` and Agent latency increases;
these remain audit findings rather than waivers.

The prior timeout report is preserved as historical external-service evidence.
Neither the prior failure nor this partial RAGAS run is treated as a passing
release gate.
