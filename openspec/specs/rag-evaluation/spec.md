# rag-evaluation Specification

## Purpose
为 EasyOffer 建立可复现、可审计且不影响线上答题的完整 RAG 评估能力，覆盖检索质量、生成质量、题目与报告业务质量，以及 Agent 的结果、过程、效率和风险。

## Requirements

### Requirement: Golden Dataset SHALL be versioned and complete

评估系统 MUST 使用版本化 Golden Dataset；正式评估数据集 MUST 恰好包含 100 条唯一样本。每条样本 MUST 包含用户问题、岗位、难度、标准答案、参考上下文原文、参考上下文标识、期望知识点、期望路由、期望工具和安全标签。数据集校验失败时 MUST 阻止评估启动并报告具体样本和字段错误。

#### Scenario: Valid 100-sample dataset is accepted
- **WHEN** 评估命令加载一个版本号明确且包含 100 条唯一样本、必填字段齐全的数据集
- **THEN** 系统接受数据集并记录数据集版本、样本数量和内容哈希

#### Scenario: Missing reference context blocks evaluation
- **WHEN** 某条样本只有参考上下文 ID 而没有参考上下文原文
- **THEN** 系统拒绝运行生成质量评估，并指出该样本缺少参考上下文原文

#### Scenario: Duplicate sample IDs are rejected
- **WHEN** 数据集中出现重复的样本 ID 或样本数量不是 100
- **THEN** 系统拒绝数据集并返回重复 ID 或数量不符合要求的错误明细

### Requirement: Retrieval evaluation SHALL preserve deterministic metrics

系统 MUST 对每条样本调用与线上一致的知识检索链路，并记录排序后的上下文、上下文标识、来源、章节、Parent 恢复状态和检索耗时。系统 MUST 计算并输出 Hit@5、MRR@5、nDCG@5、Context Precision、Context Recall、角色污染率、重复结果率、来源可追溯率、Parent 恢复率以及 P50/P95 延迟。确定性检索指标与生成质量指标 MUST 分开呈现。

#### Scenario: Retrieval result is traceable
- **WHEN** 检索返回候选上下文
- **THEN** 逐条结果包含排名、分数、来源标识、章节或页码（若有）、Parent 标识和可追溯状态，并可通过样本 ID 定位

#### Scenario: No relevant context is retrieved
- **WHEN** Top-5 结果均未命中样本的参考上下文或相关标识
- **THEN** Hit@5、Context Precision 和 Context Recall 按评估规则计为失败或低分，并在失败样本清单中列出，不得使用生成答案掩盖检索失败

#### Scenario: Version filter is applied
- **WHEN** 评估指定一个候选知识库版本
- **THEN** 评估只读取该版本允许的状态和数据，不得混入其他版本的上下文

### Requirement: Generation evaluation SHALL calculate grounded quality

系统 MUST 在检索结果和真实生成答案的基础上计算 Context Precision、Context Recall、Faithfulness 和 Answer Relevancy 四项生成质量指标。评估结果 MUST 同时保留每条样本的答案、证据和指标明细；任一评估模型、依赖或调用失败时 MUST 标记该指标为 unavailable/failed 并记录错误，不得写入伪造的 0 分或代理分数冒充真实指标。

#### Scenario: Grounded answer is evaluated
- **WHEN** 样本成功完成检索并生成答案，且评估模型调用成功
- **THEN** 系统输出四项指标的逐条分数、总体均值和按场景分组均值，并保存所使用的模型和评估时间

#### Scenario: Evaluation provider fails
- **WHEN** 评估模型、Embedding 或 RAGAS 运行时发生超时、鉴权或解析错误
- **THEN** 系统保留检索结果和错误信息，将受影响指标标记为失败/不可用，命令返回非成功状态或门禁失败，且不声称生成质量评估通过

#### Scenario: Proxy metric is not accepted as Answer Relevancy
- **WHEN** 评估报告包含“命中相关文档”等检索代理指标
- **THEN** 该指标只能显示为检索代理，不能填充或替代 Answer Relevancy

### Requirement: Quiz and report business quality SHALL be evaluated

系统 MUST 对 AI 生成题目执行业务规则检查：程序员面试相关性、主题一致性、题型结构、选项与答案一致性、知识点覆盖、难度符合度、重复题和证据支持。系统 MUST 对答题报告执行业务规则检查：总结、薄弱点、可执行建议、错题知识点覆盖、主题相关性、证据支持和字段完整性。业务评估 MUST 输出逐条通过/失败及失败原因。

#### Scenario: Valid question set passes business checks
- **WHEN** 生成题目包含合法题型、唯一答案规则正确、覆盖期望知识点且有证据支持
- **THEN** 题目业务评估标记通过并记录结构、覆盖和重复检查结果

#### Scenario: Invalid question structure fails
- **WHEN** 单选题存在多个正确答案、多选题没有足够正确选项、判断题选项不规范或答案无法解析
- **THEN** 题目评估失败并指出题目 ID、规则名称和具体原因

#### Scenario: Incomplete report fails
- **WHEN** 报告缺少薄弱点、建议、错题覆盖或必要字段
- **THEN** 报告评估失败并将失败原因加入汇总报告和门禁结果

### Requirement: Agent evaluation SHALL cover four observable layers

系统 MUST 为每个 Agent 样本记录可审计 trace，至少包含路由、工具名称和参数、调用顺序、候选数、过滤数、置信度、覆盖度、回退原因、每次调用耗时、总耗时、Token/调用成本（可获得时）、重试次数和错误。系统 MUST 分别输出：结果层（任务完成、证据和答案质量）、过程层（路由与工具选择、参数和停止条件）、效率层（延迟、Token、调用次数和成本）以及风险层（越权、数据混用、Prompt Injection、未授权来源、参数越界、版本污染和来源缺失）。

#### Scenario: Correct public knowledge route passes
- **WHEN** 公共知识问题选择公共知识库检索，工具参数合法，证据充分且答案完成
- **THEN** 结果层和过程层通过，并记录工具调用、延迟和成本数据

#### Scenario: Private knowledge boundary is violated
- **WHEN** 私有知识库样本调用公共 Web 工具或混入其他用户数据
- **THEN** 风险层标记越权失败，即使答案看似正确也不得通过安全门禁

#### Scenario: Tool call exceeds policy
- **WHEN** Agent 调用次数、参数范围或停止条件超过策略限制
- **THEN** 过程层和风险层失败，并记录违规工具、参数和触发的策略

### Requirement: Evaluation reports SHALL be auditable and comparable

系统 MUST 生成包含总体指标、分场景/岗位/难度指标、逐条结果、失败样本、Agent trace 摘要、延迟与成本、门禁结果、运行配置、数据集版本、知识库版本和代码/配置版本标识的 JSON 报告，并提供可读 Markdown 摘要。系统 MUST 支持在相同数据集版本和 Top-K 下比较两个报告，输出指标差异、回归项、结果漂移和门禁变化；数据集或 Top-K 不一致时 MUST 拒绝比较。

#### Scenario: Report is generated after a complete run
- **WHEN** 100 条样本评估完成或部分样本失败
- **THEN** 系统写入可审计 JSON 和 Markdown 报告，失败样本不被丢弃，并保留运行元数据

#### Scenario: Incompatible reports are compared
- **WHEN** 两份报告的数据集版本或 Top-K 不一致
- **THEN** 比较命令拒绝执行并说明不兼容字段

#### Scenario: Regression is detected
- **WHEN** 候选版本的任一门禁指标相对基线发生超过配置阈值的回归
- **THEN** 比较结果列出回归指标和样本漂移，发布门禁标记失败

### Requirement: Quality gates SHALL be configurable and isolated from online traffic

系统 MUST 保留现有检索门禁，并允许配置 Context Precision、Context Recall、Faithfulness、Answer Relevancy、题目/报告有效率、越权率和高风险误放行率等门槛。完整评估 MUST 作为离线命令或 CI 任务运行，不得在用户生成题目、答题或报告请求期间同步执行。评估依赖缺失或评估失败 MUST 不阻止线上服务启动。

#### Scenario: Gate blocks an underperforming candidate
- **WHEN** 候选报告的任一强制门禁低于最小值或高于最大值
- **THEN** 门禁结果为失败并列出实际值、阈值和操作符

#### Scenario: Explicit override is audited
- **WHEN** 维护者使用覆盖理由继续发布未达标版本
- **THEN** 系统要求非空理由并将维护者、时间、版本和理由写入审计报告

#### Scenario: Online service starts without evaluation extras
- **WHEN** 未安装评估专用依赖或未配置评估密钥时启动线上服务
- **THEN** 线上服务正常启动，离线评估命令明确报告缺少依赖/配置并退出失败

### Requirement: Evaluation data SHALL protect secrets and user privacy

评估报告和日志 MUST 脱敏 API Key、Token、密码、Authorization 和用户身份信息；评估样本 MUST 使用固定或合成输入，禁止默认导出真实用户答案。报告保存失败时 MUST 不泄露原始密钥或完整敏感请求头。

#### Scenario: Sensitive trace fields are written
- **WHEN** trace 或异常对象包含密钥、Token 或 Authorization 字段
- **THEN** 持久化报告使用 `[REDACTED]` 或等价脱敏值

#### Scenario: Real user data is not part of the golden set
- **WHEN** 运行 Golden Dataset 校验
- **THEN** 系统拒绝包含未标记脱敏用户标识或真实凭证字段的样本
