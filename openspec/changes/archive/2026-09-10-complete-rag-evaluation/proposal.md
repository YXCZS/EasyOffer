## Why

EasyOffer 当前已经有版本化 Golden Set、Milvus 检索回归和发布门禁，但评测仍主要停留在 Hit@K、MRR、nDCG、延迟、来源追溯以及规则化 `answer_integrity`。这无法回答“召回内容是否足够、答案是否忠实于证据、答案是否真正回答问题、Agent 是否正确选择工具”等核心质量问题，尤其无法支撑 100 条样本的可复现面试项目评审。

现在需要把离线评测扩展为三层 RAG 评测（检索、生成、端到端业务）和 Agent 四层评测（结果、过程、效率、风险），同时保留已有确定性指标，形成可审计、可比较、可在 CI 中执行的评估体系。

## What Changes

- 将现有版本化 Golden Set 扩展为正好 100 条，并为每条样本补充标准答案、参考上下文原文、期望知识点、期望路由/工具和安全标签。
- 新增评估专用依赖组，接入 RAGAS Collections API、`EvaluationDataset` 和 `aevaluate()`，真实计算 Context Precision、Context Recall、Faithfulness、Answer Relevancy。
- 抽象真实 EasyOffer 检索链路适配器，记录每条样本的召回上下文、上下文 ID、引用和生成输入；RAGAS 失败时保留失败状态，不伪造分数。
- 新增题目业务质量评估：主题相关性、题型结构、答案一致性、知识点覆盖、难度符合度、重复题和证据支持等规则。
- 新增报告业务质量评估：总结、薄弱点、可执行建议、错题覆盖、主题相关性、证据支持和字段完整性等规则。
- 扩展 Agent trace，统一记录路由、工具调用、参数、候选数、过滤数、置信度、覆盖度、回退原因、耗时、Token、重试和错误。
- 新增 Agent 结果、过程、效率、风险四层指标，并覆盖私有知识库越权、公共/私有数据混用、URL Prompt Injection、未授权来源、参数越界、版本污染和来源缺失。
- 扩展 CLI，支持完整评估、报告查看、Golden Set 校验和版本报告对比；输出 JSON/Markdown 逐条结果、分场景统计、失败样本、成本/延迟和门禁结果。
- 在保留现有 Hit@5、MRR@5、nDCG@5、角色污染率、重复率、来源可追溯率、Parent 恢复率等门禁的基础上，增加 RAGAS、题目、报告和安全门禁；阈值作为项目初始工程门槛并允许配置。
- 增加 pytest 单元测试、评估数据校验测试和轻量 CI 哨兵集入口；完整评估为离线任务，不在用户请求期间执行。

## Capabilities

### New Capabilities

- `rag-evaluation`: 提供 100 条版本化 Golden Set、三层 RAG 质量评估、题目/报告业务评估、Agent 四层评估、报告生成、版本对比和发布门禁。

### Modified Capabilities

无。现有题目类型和线上答题流程的需求契约不变；本变更只新增离线评估与质量门禁能力。

## Impact

- 后端：`backend/app/corpus/evaluation.py`、`backend/app/corpus/cli.py`、`backend/app/corpus/pipeline.py`、Agent/RAG trace 相关模块及新增评估模块。
- 数据：新增 `backend/corpus/benchmarks/golden-v2.yaml`（100 条）及逐条参考上下文/答案字段；保留现有 benchmark 作为历史基线。
- 依赖：在 `backend/pyproject.toml` 增加独立 `eval` 可选依赖组（RAGAS 及其兼容适配），不改变线上默认安装和启动依赖。
- 报告：在运行时目录生成逐条评估结果、汇总报告、门禁结果和版本差异报告；不得写入密钥或未脱敏用户数据。
- 运行链路：不改变 Milvus、BM25/RRF、DashScope rerank、Tavily、DeepSeek 的生产调用逻辑，不在在线请求中运行完整 RAGAS。
- 验证：后端通过 pytest；评估 CLI、数据校验和 CI 哨兵集可重复运行。微信小程序前端无需改动，现有“答题/我的”导航和答题报告流程必须保持可用。
