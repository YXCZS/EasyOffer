# EasyOffer RAG 评估功能开发记录

## 1. 文档目的

本文记录 EasyOffer RAG 评估功能的实际开发过程、技术实现、验证方式、
真实运行结果和遗留问题。本文只记录已经写入代码并实际执行过的内容，
不把规划中的能力当作已完成能力。

评估系统是离线工具，不参与微信小程序的在线请求，也不会在 FastAPI
启动时强制导入 RAGAS。线上出题、答题和报告流程因此不依赖评估专用依赖。

## 2. 最终评估链路

```text
Golden Dataset v2
        |
        v
加载与严格校验（100 条、唯一 ID、参考答案/上下文、路由与安全标签）
        |
        v
真实生产检索适配器
        |
        +--> Milvus Standalone 版本/状态/作用域过滤
        |       |
        |       +--> 确定性检索指标
        |
        +--> 真实 DeepSeek 出题
        |       |
        |       +--> 题目业务规则评估
        |
        +--> 真实 Agent/RAG 入口
                |
                +--> 四层 Agent trace 评估

检索上下文 + 真实生成响应
        |
        +--> DashScope qwen-plus / text-embedding-v4
                |
                +--> RAGAS Collections API 四项指标

统一 JSON 报告 --> Markdown 汇总 --> 门禁 --> registry / 比较 / 审计
```

## 3. 第一阶段：建立可复现的 Golden Dataset

### 3.1 数据模型

实现位置：`backend/app/corpus/evaluation.py`。

新增 `GoldenDataset` 和扩展后的 `BenchmarkQuery`，每条样本包含：

- 用户问题、主题、岗位和难度；
- 期望知识点与技术标签；
- 标准答案 `reference_answer`；
- 参考上下文原文 `reference_contexts` 和上下文 ID；
- 期望路由和工具；
- 场景类型、知识库作用域和安全标签；
- 可选用户作用域字段。

数据集加载时强制检查：

- 样本数量必须正好是 100；
- `query_id` 必须唯一；
- 参考答案、参考上下文、期望路由和工具不能为空；
- 参考上下文 ID 与原文数量必须一一对应；
- 内容按规范化 JSON 计算 SHA-256，作为审计标识。

历史 38 条 benchmark 保持兼容，没有被删除；新增的
`backend/corpus/benchmarks/golden-v2.yaml` 是正式的 100 条版本化数据集。

### 3.2 为什么保留参考上下文原文

只保存 chunk ID 无法计算上下文覆盖质量，也无法人工核对“召回到了相似
内容，但不是目标内容”的情况。因此 Golden Dataset 同时保存 ID 和原文，
评估结果才能复现、审计和比较。

## 4. 第二阶段：复用真实生产链路

实现位置：

- `backend/app/corpus/evaluation_runner.py`
- `backend/app/corpus/pipeline.py`

### 4.1 适配器原则

`ProductionEvaluationAdapter` 只负责调用生产入口和采集观察值，不重新实现
一套检索算法。它调用当前项目实际使用的：

- Milvus 公共/私有检索；
- Agent/RAG 路由入口；
- DeepSeek 题目生成入口；
- 生产中的 Tavily、DashScope 和 rerank 调用边界。

这样离线指标反映的是线上真实实现，而不是测试代码自己的“理想算法”。

### 4.2 版本、发布状态和权限隔离

每次评估必须显式传入 corpus version 和状态过滤条件，默认回放
`published`。私有样本还会带用户作用域，并在适配器层再次过滤，防止底层
存储适配器未实现过滤时混入其他版本或其他用户数据。

### 4.3 统一观察模型

评估层统一保存以下对象：

- `RetrievalObservation`：上下文、上下文 ID、来源、引用、版本、耗时和错误；
- `GenerationObservation`：真实响应、题目载荷、报告载荷、耗时和错误；
- `AgentTrace`：路由、工具调用、候选/过滤数量、置信度、覆盖度、回退、
  Token、重试、耗时、策略风险和最终状态。

错误按样本保留，单条失败不会被转换成成功结果，也不会阻止其他样本继续。

## 5. 第三阶段：确定性检索评估

确定性指标不调用大模型，使用 Golden Dataset 的参考上下文和实际召回结果
直接计算：

- Hit@5：Top-5 是否命中目标上下文；
- MRR@5：第一个目标上下文的倒数排名；
- nDCG@5：考虑相关性等级的排序质量；
- Context Precision：Top-K 中目标上下文的比例；
- Context Recall：参考上下文被覆盖的比例；
- 角色污染率、重复结果率；
- 来源可追溯率、Parent 恢复率；
- P50/P95 检索延迟。

确定性 Context Precision/Recall 与 RAGAS 指标分栏保存，不能互相覆盖。
例如确定性 Precision 较低时，不能用 RAGAS 的高分掩盖召回结果中的尾部
冗余。

## 6. 第四阶段：RAGAS 生成质量评估

### 6.1 技术选型

RAGAS 被放在独立的 `eval` 可选依赖组中，使用 RAGAS 0.4.x Collections API：

- `EvaluationDataset`；
- `SingleTurnSample`；
- `ContextPrecision`；
- `ContextRecall`；
- `Faithfulness`；
- `AnswerRelevancy`。

评估模型使用 DashScope OpenAI-compatible 接口：

- LLM：`qwen-plus`；
- Embedding：`text-embedding-v4`。

实现位置：`backend/app/corpus/ragas_evaluation.py`。

### 6.2 运行策略

RAGAS 指标异步执行，带有并发上限、单指标超时、总超时、有限重试和错误
保留。每条样本保存四项指标的真实值或失败原因，并记录模型名、Embedding
模型、评估状态和耗时。

RAGAS 不可用、鉴权失败、超时或解析失败时，指标标记为 `failed` 或
`unavailable`，不会写入伪造的 0 分，也不会用项目内部 proxy 指标冒充
Answer Relevancy。

## 7. 第五阶段：题目与报告业务评估

实现位置：`backend/app/corpus/evaluation.py`。

### 7.1 题目规则

题目业务评估使用确定性规则检查：

- 是否有题目；
- 题目是否重复；
- 单选、多选、判断题结构是否正确；
- 答案是否存在于选项；
- 知识点覆盖；
- 难度是否符合请求；
- 是否有证据支持；
- 是否存在未授权来源或跨版本证据。

### 7.2 报告规则

报告评估器检查总结、薄弱点、建议、错题知识点覆盖、主题相关性、证据
支持和字段完整性。当前真实全量回放使用的是出题入口，未生成答题后的
报告载荷，因此本轮 `report_quality` 没有可计入的报告样本；报告评估代码
本身通过了完整、空报告和缺字段 fixture 测试。

## 8. 第六阶段：Agent 四层评估与安全

Agent 评估不只看最终答案，而是分成四层：

1. 结果层：任务是否完成、是否有证据和答案；
2. 过程层：路由、工具选择、参数范围和停止条件；
3. 效率层：耗时、Token、工具次数、重试和成本估算；
4. 风险层：越权、公共/私有混用、Prompt Injection、未授权来源、参数越界、
   版本污染和来源缺失。

Agent trace 在落盘前进行字段级脱敏，API Key、Token、密码、Authorization
和用户标识不会以明文写入 JSON 或 Markdown。

## 9. 第七阶段：报告、门禁和比较

统一 JSON 是唯一事实来源，包含：

`metadata`、`dataset`、`retrieval`、`ragas`、`quiz_quality`、
`report_quality`、`agent`、`gates`、`samples` 和 `errors`。

Markdown 由同一 JSON 渲染，避免两套统计口径。报告写入使用临时文件替换，
替换失败时保留上一份报告；registry 记录路径、哈希和门禁摘要。

门禁包含检索、RAGAS、题目、报告和安全指标。比较命令只接受相同数据集版本
和 Top-K 的报告，并输出：

- 指标 delta；
- 回归项；
- 结果漂移样本；
- 门禁变化。

门禁 override 必须提供非空理由、维护者和时间，并写入审计结果。

## 10. CLI 与测试入口

主要命令：

```powershell
python -m app.corpus.cli validate-golden corpus/benchmarks/golden-v2.yaml
python -m app.corpus.cli evaluate corpus/benchmarks/golden-v2.yaml <corpus-version> --deterministic-only
python -m app.corpus.cli evaluate corpus/benchmarks/golden-v2.yaml <corpus-version> --include-generation --include-agent --ragas
python -m app.corpus.cli eval-report <report.json>
python -m app.corpus.cli compare <baseline.json> <candidate.json>
```

测试覆盖 Pydantic 数据模型、Golden Dataset 校验、版本和权限过滤、指标边界、
RAGAS mock/失败状态、业务规则、Agent 四层指标、脱敏、报告快照、CLI 和
临时文件回滚。

实际验证结果：

- 后端 `pytest -q`：303 项通过；
- 前端 `npm run typecheck`：通过；
- 前端 `npm run build:weapp`：通过；
- `openspec validate complete-rag-evaluation --strict`：通过。

## 11. 真实全量回放结果

回放对象：已发布 `full-authorized-v1`，Milvus Standalone，100 条 `golden-v2`。

### 11.1 检索

- Hit@5：`1.000`；
- MRR@5：`0.975`；
- nDCG@5：`0.982`；
- 确定性 Context Precision：`0.708`；
- 确定性 Context Recall：`0.954`；
- P50/P95：`501.47 / 610.24 ms`；
- 来源可追溯率：`1.000`；
- Parent 恢复率：`1.000`。

### 11.2 RAGAS、题目和 Agent

- 100 条样本均进入真实出题和 Agent 适配器；
- RAGAS 为 `partial`，99 条成功、1 条失败；
- Faithfulness：`0.9566`；
- Context Recall：`0.9424`；
- Context Precision：`0.9528`；
- Answer Relevancy：`0.8050`；
- 修正评估器后的题目有效率：`0.71`（71/100）；
- 题目重复率：`0.0`；
- Agent trace 显示本轮走 `base_model` fallback、无工具调用，不能宣称
  Milvus/Tavily Agent 路由评估通过。

### 11.3 评估适配器修复后的单样本复核

全量报告生成后发现，公共 Golden 样本没有 `user_id` 时，Agent 评估适配器
没有使用评估专用身份 `0`，因此把公共样本误当成游客，所有工具都被策略
禁止。修复后用真实 Milvus Standalone 对 `g-001` 做了单样本回放，结果为：

- route：`public_kb`；
- tool：`public_milvus_search`；
- candidate/filtered：`5/5`；
- completed：`true`；
- fallback_reason：空；
- policy_findings：空。

这次修复只改变评估适配器的身份映射和 Agent 终止状态归一化，不改变线上
检索算法。此前保存的 100 条全量报告仍作为修复前历史审计证据；若要发布
修复后的 Agent 全量指标，需要重新执行完整离线回放。

## 12. 开发过程中遇到的问题与解决方式

### 问题一：第一次全量回放在中途连续超时

第一次真实回放前 6 条成功，之后出现 DeepSeek `Request timed out`。旧报告
没有被覆盖，保留为外部服务故障的历史证据。随后单条真实生成和前 10 条
连续回放恢复成功，再重新执行 100 条全量回放，最终 100 条均完成出题入口。

结论：不能因为重试后成功就删除历史失败记录；故障必须留在审计链路中。

### 问题二：g-093 返回多余的 `options_order`

计算机网络样本的模型输出包含严格 schema 未声明的 `options_order` 字段，
导致 Pydantic 校验失败。该样本被明确标记为生成失败，RAGAS 不分配分数，
最终为 99/100 成功。这个问题仍属于真实生成质量/契约问题，不被评估器
吞掉。

### 问题三：题目有效率最初错误显示为 0

生产题目选项是 `{key, text}` 对象，答案是 `['A']` 这样的选项 key。原评估器
把答案 key 直接与选项对象比较，导致所有题目被误判为答案不在选项中。
修复后增加了结构化选项 key 映射回归测试，重新评估持久化真实观察值，
题目有效率从错误的 `0` 更正为 `0.71`。剩余失败是实际知识点覆盖不足，
因此门禁仍然失败。

### 问题四：Agent 没有产生工具调用

真实 trace 显示 `agent_disabled_or_missing_model`，路由回退到 `base_model`，
工具调用数为 0。评估器保留了这个过程结果，并将 Agent 过程层判定为未通过，
没有因为最终任务完成就把它包装成成功的 Agentic RAG。

### 问题五：相似内容命中但尾部存在冗余

确定性评估显示 Hit@5 很高，但 Context Precision 只有 `0.708`，重复结果率
为 `0.020`。人工抽检发现部分 Top-K 尾部是同 Parent、跨技术域词义相近或
资料模板噪声。这说明不能只用 Hit@5 判断检索质量，必须同时保留 Precision、
Recall、重复率和人工抽检结论。

## 13. 当前状态与后续边界

评估框架、100 条数据集、确定性指标、RAGAS 适配、业务评估、Agent trace、
报告、CLI、门禁和真实回放均已实现并验证。当前真实报告门禁未通过，原因是
题目有效率不足、g-093 生成失败以及 Agent 工具路由未启用；这些是需要继续
优化产品链路的问题，不是评估系统可以忽略的问题。

OpenSpec `complete-rag-evaluation` 仍保留一项未完成任务：Milvus/Tavily/
DashScope 的主动故障回放。该项此前已明确暂缓，因此没有伪造为已完成。

## 14. 相关文件

- 评估核心：`backend/app/corpus/evaluation.py`
- 生产适配器：`backend/app/corpus/evaluation_runner.py`
- RAGAS 适配器：`backend/app/corpus/ragas_evaluation.py`
- 评估编排：`backend/app/corpus/pipeline.py`
- CLI：`backend/app/corpus/cli.py`
- Golden Dataset：`backend/corpus/benchmarks/golden-v2.yaml`
- 操作手册：`backend/docs/rag-evaluation-operations.md`
- 真实审计：`backend/docs/rag-evaluation-audit-full-authorized-v1.md`
- 全量报告：`backend/data/public-corpus/evaluations/full-authorized-v1-golden-v2-full-rerun.json`
- 修正报告：`backend/data/public-corpus/evaluations/full-authorized-v1-golden-v2-full-rerun-corrected.json`
