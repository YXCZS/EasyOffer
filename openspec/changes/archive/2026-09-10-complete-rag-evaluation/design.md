## Context

当前 `backend/app/corpus/evaluation.py` 已能加载 YAML benchmark，调用真实 corpus store，计算 Hit@5、MRR@5、nDCG@5、角色污染、重复、来源追溯、Parent 恢复、答案完整性和延迟，并通过 `DEFAULT_GATES` 做确定性门禁。`CorpusPipeline.evaluate` 将结果写入运行时 JSON，CLI 已支持 `evaluate` 和 `compare`。

现状缺口是：benchmark 只有检索相关字段，无法提供 Context Recall 所需的参考上下文；没有统一的生成回放接口；没有 RAGAS 生成指标、题目/报告业务规则或 Agent trace。线上检索链路已经确定为 Milvus Dense + 原生 BM25 + RRF + DashScope rerank，并由 Agent 在公共/私有知识库和 Tavily Search/Extract 之间路由。本变更只围绕离线评估建立适配层，不改变该生产链路。

## Goals / Non-Goals

**Goals:**

- 用 100 条可版本化、可审计的 Golden Dataset 覆盖稳定知识、复杂问题、新技术、URL、私有知识库和安全边界。
- 对同一条样本同时评估检索、真实生成、题目/报告业务质量和 Agent trace，区分指标来源与失败状态。
- 复用线上检索与 Agent 策略，保证离线结果能反映发布版本，而不是另写一套“理想检索器”。
- 让 RAGAS 依赖、评估密钥和耗时任务与线上服务隔离；支持报告、版本比较、门禁和 CI 哨兵集。

**Non-Goals:**

- 不把 RAGAS、DeepEval、TruLens 同时作为运行时框架；本变更只接入 RAGAS 作为生成指标实现。
- 不改动题目生成提示词、Milvus schema、BM25/RRF/rerank、Tavily 或 DeepSeek 的线上行为。
- 不在微信小程序或用户请求同步执行 100 条完整评估，不新增前端页面。
- 不把人工抽检自动伪装成标准答案；人工标注仍由版本化数据文件维护。

## Decisions

### 1. 采用“统一样本 + 分层评估”数据模型

在现有 benchmark 查询模型之上增加兼容字段，正式文件为 `backend/corpus/benchmarks/golden-v2.yaml`。每条样本同时保存 `reference_answer` 和 `reference_contexts` 原文，并用 `reference_context_ids` 连接已发布 corpus；这样 Context Recall 可判断信息覆盖，Faithfulness 可判断答案是否被证据支持。数据集按场景固定分布（65 稳定技术、10 复杂多意图、10 新技术、5 URL、5 私有、5 无关/越权），加载时验证总数、唯一 ID、枚举值和敏感字段。

备选方案是只保存 chunk ID 或只从线上 corpus 动态读取参考文本。前者无法评估生成忠实度，后者会随 corpus 变化导致历史结果不可复现，因此保留原文并记录 corpus 版本和哈希。

### 2. 抽象真实链路适配器，不复制检索逻辑

新增离线评估适配器，将样本映射到现有公共/私有检索和 Agent 入口，返回统一的 `RetrievalObservation` 与 `GenerationObservation`：问题、路由、工具调用、召回上下文（文本和 ID）、引用、最终答案、题目/报告载荷、耗时和错误。适配器只负责采集观察值，指标计算保持纯函数，便于使用 InMemory store 做单元测试并在 Milvus Standalone 上做真实回放。

检索观察必须带 `corpus_version` 和发布状态过滤；私有样本带用户/知识库作用域。适配器遇到 Tavily、DashScope 或 Milvus 错误时记录结构化错误并继续汇总其他样本，不能返回不完整的“成功”观察。

### 3. RAGAS 作为可选的生成评估后端

在 `pyproject.toml` 增加 `eval` optional dependency（锁定兼容范围），线上默认安装不导入 RAGAS。评估模块采用延迟导入，并按官方 Collections API 构造 `EvaluationDataset`，以异步 `aevaluate()` 执行 Context Precision、Context Recall、Faithfulness、Answer Relevancy；评估 LLM 和 Embedding 通过现有 DashScope/OpenAI-compatible 配置注入适配器。

RAGAS 输入统一为 `user_input`、`retrieved_contexts`、`reference`、`response`，并保留 `sample_id` 作为外部关联键。每个指标保存模型、版本、耗时和错误。RAGAS 不可用时不阻断 `--deterministic-only` 检索评估，但使用 `--ragas` 时命令必须明确失败或门禁失败。

备选方案是自写 LLM-as-a-Judge 或同时引入多个框架。自写实现难以复现，多个框架会造成成本和口径冗余；因此只保留 RAGAS，并把项目特有规则放在独立业务评估器中。

### 4. 业务评估采用确定性规则优先，模型判断仅作扩展

题目与报告评估先使用可重复的 Pydantic/schema、选项计数、答案解析、知识点字符串覆盖、重复相似度、引用存在性和必填字段规则。规则结果记录 `passed`、`score`、`rule_id`、`details`，不与 RAGAS 分数混合。后续若需要 LLM Judge，可新增指标版本，不改变本变更的门禁口径。

这样可以在无外部模型的 CI 环境验证结构与安全边界，也能清楚区分“格式错误”和“模型质量低”。

### 5. Agent trace 使用统一事件记录和四层聚合

每个样本写入不可变的 trace 事件：`route`、`tool_calls[]`、参数摘要、候选数、过滤数、confidence、coverage、fallback_reason、token_usage、retry_count、latency_ms、errors 和 policy findings。敏感参数在写入前统一脱敏，只保留是否调用、参数范围和结果计数。

聚合层分别计算结果（任务完成、证据/答案质量）、过程（路由/工具/参数/停止条件）、效率（P50/P95、Token、调用次数、成本）和风险（越权、数据混用、Prompt Injection、来源与版本污染）指标。风险违规采用硬失败，不因最终答案正确而抵消。

### 6. 报告与门禁采用稳定 JSON 结构，Markdown 只是渲染层

统一报告包含 `metadata`、`dataset`、`retrieval`、`ragas`、`quiz_quality`、`report_quality`、`agent`、`gates`、`samples` 和 `errors`。JSON 是唯一事实来源，Markdown 由同一对象渲染，避免两套口径。报告记录数据集哈希、corpus 版本、Top-K、模型/Embedding/Rerank 名称、代码版本和运行时间。

初始门槛沿用现有检索门禁，并新增 Context Precision >= 0.80、Context Recall >= 0.80、Faithfulness >= 0.85、Answer Relevancy >= 0.80、题目/报告有效率 1.0、题目重复率 <= 0.05、越权率 0 和高风险误放行率 0。阈值放入配置，可按场景覆盖；它们是项目工程门槛，不宣称行业强制标准。

### 7. CLI 分层执行，支持离线全量与 CI 哨兵

保留现有命令兼容性，并增加：

```text
python -m app.corpus.cli validate-golden <golden.yaml>
python -m app.corpus.cli evaluate <golden.yaml> <corpus-version> --deterministic-only
python -m app.corpus.cli evaluate <golden.yaml> <corpus-version> --ragas --include-generation --include-agent
python -m app.corpus.cli eval-report <report.json>
python -m app.corpus.cli compare <baseline.json> <candidate.json>
```

`--deterministic-only` 不需要 RAGAS；完整模式显式开启生成和 Agent 评估。CI 使用固定哨兵子集做快速回归，发布前再运行 100 条全量评估。比较要求数据集版本和 Top-K 一致，并输出指标 delta、回归项和样本结果漂移。

### 8. 采用文件报告，不增加线上数据库表

评估原始结果写入 `runtime_root/evaluations/<dataset>-<corpus>-<timestamp>.json`，汇总 Markdown 写入同目录；不把大体量 trace 写入 MySQL，避免线上 schema 和事务链路膨胀。报告路径、哈希和门禁摘要可由现有 registry 记录。文件写入采用临时文件替换，失败不覆盖上一次报告。

## Risks / Trade-offs

- **[RAGAS 依赖或 DashScope 限流]** → 评估依赖独立安装，增加超时、重试和并发上限；失败指标标记 unavailable，不伪造分数；确定性评估仍可单独运行。
- **[100 条样本标注成本高]** → 先复用现有 38 条并补齐参考原文，再按场景模板扩展；每条样本必须通过 schema 校验，发布前保留人工抽检记录。
- **[模型非确定导致报告抖动]** → 记录模型与参数，评估请求使用低温度/固定配置；门禁关注总体均值和硬风险指标，比较报告同时展示逐条漂移。
- **[离线适配器与线上链路漂移]** → 适配器调用现有入口而非复制算法，报告记录代码版本；CI 哨兵集在每次检索改动后运行。
- **[敏感数据进入 trace]** → 统一字段级脱敏、禁止真实用户样本进入 Golden Set，并在测试中注入密钥/Authorization 验证脱敏。
- **[评估耗时和成本增加]** → RAGAS 只在离线/发布前运行，支持哨兵集、并发上限、缓存和断点续跑；线上请求路径零新增评估调用。

## Migration Plan

1. 新增评估依赖组和数据模型，先让现有 38 条 benchmark 继续通过确定性评估。
2. 创建并校验 `golden-v2.yaml` 100 条样本，生成参考上下文和标准答案哈希；不替换历史 benchmark。
3. 接入真实检索/生成/Agent 观察适配器，先运行 deterministic-only 建立基线。
4. 安装 `eval` 依赖并执行 RAGAS，生成完整基线报告；确认指标口径后启用新增门禁。
5. 将完整评估接入发布前脚本，CI 只执行哨兵集；报告和门禁失败不会影响线上服务启动。

回滚时移除 CI 完整评估入口或关闭新增门禁配置即可；线上服务仍使用原有链路。评估报告和 Golden Dataset 是追加文件，不需要数据库回滚。若 RAGAS 版本不兼容，继续运行 deterministic-only 并锁定依赖版本，待修复后再启用生成门禁。

## Open Questions

无。模型具体名称、并发上限和阈值可在实现阶段通过配置调整，不改变规格和数据契约。
