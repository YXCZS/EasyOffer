## 1. 评估数据与依赖准备

- [x] 1.1 扩展 Golden Dataset 数据模型，兼容现有 benchmark 字段并增加标准答案、参考上下文、期望路由、工具和安全标签；使用 Pydantic 单元测试覆盖合法样本、缺字段、非法枚举和敏感字段。
- [x] 1.2 创建 `backend/corpus/benchmarks/golden-v2.yaml`，包含正好 100 条唯一且按场景分布的样本；通过 `validate-golden` 验证数量、唯一性、字段完整性和内容哈希。
- [x] 1.3 为历史 38 条样本补充人工可审计的参考上下文原文和标准答案，保留原 benchmark 不变；运行迁移与转换测试确认历史 benchmark 仍可加载。 
- [x] 1.4 在 `backend/pyproject.toml` 增加独立 `eval` 可选依赖组并约束 RAGAS 兼容范围；验证未安装该组时 FastAPI 不导入 RAGAS 且可以启动。

## 2. 统一观察模型与真实链路适配

- [x] 2.1 定义检索、生成和 Agent trace 的统一观察模型，包含上下文、来源、引用、路由、工具调用、耗时、Token、重试和错误；使用 Pydantic 测试验证序列化、默认值和错误状态。
- [x] 2.2 实现离线评估适配器，调用现有公共/私有 Milvus 检索、Tavily Search/Extract、题目生成与 Agent 入口，不复制生产检索算法；用 InMemory store 测试验证调用契约。
- [x] 2.3 为适配器增加 corpus 版本、发布状态和私有作用域过滤；通过跨版本、跨用户夹带数据测试，验证结果不会混入其他版本或用户数据。
- [ ] 2.4 增加 Milvus Standalone 真实回放配置与故障恢复；在测试 corpus 上实际验证 Milvus、Tavily、DashScope 错误被记录且不伪造成成功结果。

## 3. 确定性检索评估

- [x] 3.1 保留并整理 Hit@5、MRR@5、nDCG@5、角色污染率、重复结果率、来源可追溯率、Parent 恢复率和 P50/P95 延迟；使用边界测试验证不回归。
- [x] 3.2 实现基于参考上下文的确定性 Context Precision、Context Recall，并与 RAGAS 指标分栏输出；用全命中、部分命中、无命中样本验证分数和失败明细。
- [x] 3.3 确保评估按指定 corpus 版本与发布状态执行，并记录数据集、代码与配置版本；通过双版本同题回归测试验证没有跨版本召回。

## 4. RAGAS 生成质量评估

- [x] 4.1 新增 RAGAS Collections API 适配器，构建 `EvaluationDataset` 并异步执行四项核心指标；用 stub LLM/Embedding 测试输入映射与 sample_id 关联。
- [x] 4.2 接入 DashScope 评估 LLM 与 Embedding 配置，具备超时、重试、并发上限和缓存策略；使用可控 mock 验证成功、超时、鉴权失败和解析失败。
- [x] 4.3 实现 RAGAS 逐条结果、总体均值和按场景聚合，并保存模型、评估时间和耗时元数据；通过报告快照测试验证四项指标可审计。
- [x] 4.4 明确 RAGAS 不可用、部分指标失败和代理指标的状态语义；验证 `answer_relevancy_proxy` 不会填充 Answer Relevancy，且 `--ragas` 失败时门禁失败。

## 5. 题目与报告业务评估

- [x] 5.1 实现题目结构、题型、答案解析、主题/岗位相关性、知识点覆盖、难度与重复题规则；为合法题目及各类非法题目 fixture 验证 rule_id 与失败原因。
- [x] 5.2 实现题目证据支持和未授权来源检查，并将安全违规与普通质量问题分开统计；覆盖公共、私有、无来源与跨版本样本门禁行为。
- [x] 5.3 实现答题报告字段完整性、总结、薄弱点、建议、错题覆盖、主题相关性和证据支持检查；覆盖完整、空与缺字段报告。
- [x] 5.4 聚合题目有效率、报告有效率、题目重复率和高风险误放行率；测试分母、空样本与部分失败样本的一致性。

## 6. Agent 四层评估与安全

- [x] 6.1 在 Agent/RAG 入口采集不可变 trace 事件和工具调用摘要，记录路由、参数范围、候选/过滤数、置信度、覆盖度、回退、Token、重试和耗时；验证调用顺序与字段完整性。
- [x] 6.2 实现结果层与过程层指标，包含任务完成、证据/答案质量、路由正确性、工具选择、参数合法性与停止条件；覆盖正确路由、错误路由和过早结束。
- [x] 6.3 实现效率层指标，包含总耗时 P50/P95、Token、Embedding/Rerank/Tavily 调用次数、重试与成本估算；使用固定 trace 验证聚合值和单位。
- [x] 6.4 实现风险层检测，包含私有知识库越权、公共/私有混用、URL Prompt Injection、未授权来源、参数越界、版本污染和来源缺失；高风险样本必须硬失败。
- [x] 6.5 实现 trace 和报告字段级脱敏，覆盖 API Key、Token、密码、Authorization 和用户标识；持久化 JSON/Markdown 不得含明文机密。

## 7. 报告、门禁与 CLI

- [x] 7.1 定义统一 JSON 报告 schema，覆盖 metadata、dataset、retrieval、ragas、quiz_quality、report_quality、agent、gates、samples 和 errors；以 schema/快照测试保证字段稳定。
- [x] 7.2 从同一 JSON 渲染 Markdown 汇总，包含总体、分场景/岗位/难度、失败样本、延迟/成本和 trace 摘要；验证 JSON 与 Markdown 指标一致。
- [x] 7.3 扩展 CLI 的 `validate-golden`、分层 `evaluate`、`eval-report` 和 `compare` 命令，并保持旧命令兼容；验证参数、退出码、错误信息和输出路径。
- [x] 7.4 将检索、RAGAS、业务与安全门禁配置化，并支持记录明确 override 理由、维护者与时间；验证达标、不达标和 override 行为。
- [x] 7.5 支持相同数据集版本与 Top-K 下的报告比较，输出指标 delta、回归项、结果漂移和门禁变化；拒绝不兼容报告并支持配置回归阈值。
- [x] 7.6 通过临时文件替换写入 JSON/Markdown，并把路径、哈希和门禁摘要写入 registry；模拟写入失败时保留上一份报告。

## 8. 集成验证与发布准备

- [x] 8.1 为完整评估建立端到端离线入口，并对已发布的真实 corpus 执行 100 条 deterministic-only 评估，保存可审计基线报告。
- [x] 8.2 在已安装 eval 依赖、DashScope 凭证可用的环境，对 100 条样本完成真实 RAGAS、业务和 Agent 全量评估；四项 RAGAS 指标必须为真实值或明确失败。
- [x] 8.3 增加 CI 哨兵集任务，仅运行固定小样本的检索、结构和安全门禁；无 RAGAS 依赖的默认 CI 与线上服务启动不受影响。
- [x] 8.4 执行后端完整 `pytest -q`、评估 CLI 与报告脱敏测试，记录命令、版本和结果；全部通过后才允许启用发布前完整评估。
- [x] 8.5 实际执行一次 Milvus Standalone 回放和一次候选/基线报告比较，并人工抽检失败样本的上下文、答案和 trace，形成审计结论。
- [x] 8.6 更新评估运行与回滚说明，验证评估失败不阻止 FastAPI 启动，关闭新增门禁即可恢复原发布流程。
