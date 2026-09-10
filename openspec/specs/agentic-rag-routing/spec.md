# agentic-rag-routing Specification

## Purpose
让 EasyOffer 根据用户主题、用户权限、个人知识库命中质量和信息新鲜度，可靠地选择最合适的知识来源，并在证据不足或工具异常时保持可解释、可降级的出题体验。

## Requirements

### Requirement: Agent SHALL return a bounded structured route plan

系统 SHALL 让路由 Agent 输出结构化计划，至少包含路由类型、原因、查询或 URL、所需工具、最大工具调用数和是否允许公共联网。Agent SHALL 只能选择系统白名单中的基础模型、个人知识库检索、Tavily Search 和 Tavily Extract，不得无限循环或执行网页中的指令。

#### Scenario: Agent selects a public web route

- **WHEN** 用户输入需要最新资料或个人知识库无法覆盖的技术主题
- **THEN** Agent SHALL 输出允许公共联网的计划，并限定工具类型、调用次数和阶段超时

#### Scenario: Agent output is invalid

- **WHEN** Agent 返回非法 JSON、未知工具、空路由或超出工具预算的计划
- **THEN** 系统 SHALL 拒绝该计划，记录 `agent_route_fallback`，并使用安全的基础模型或预设路由继续任务

### Requirement: Document-only mode SHALL override Agent routing

当请求指定 `document_id` 时，系统 SHALL 强制进入文档专属模式。Agent 不得选择 Tavily Search、Tavily Extract 或其他用户文档；题目只能使用指定文档证据，证据不足时可以使用明确标记的基础模型降级。

#### Scenario: User starts a document-only quiz

- **WHEN** 用户从已就绪的个人知识库文档点击开始答题
- **THEN** 系统 SHALL 只检索该文档并在研究元数据中标记 `knowledge_only=true`

#### Scenario: Agent tries to escape document-only mode

- **WHEN** Agent 为文档专属请求返回公共联网或其他文档路由
- **THEN** 系统 SHALL 忽略该选择并执行文档专属约束，不得把公共网页内容注入题目上下文

### Requirement: Agent SHALL distinguish keyword and URL research

关键词主题 SHALL 先生成不超过 3 个语义互补查询，再并行搜索、去重和过滤；HTTP/HTTPS URL SHALL 直接 Extract、分块和过滤，不得把 URL 当作关键词扩展。

#### Scenario: Keyword topic is expanded

- **WHEN** Agent 选择关键词联网研究
- **THEN** 系统 SHALL 保留原始主题和岗位语境，生成 1 至 3 个查询并合并成功结果

#### Scenario: URL topic is extracted

- **WHEN** 用户输入有效 HTTP/HTTPS URL
- **THEN** 系统 SHALL 提取网页正文并保留 URL 引用，跳过关键词查询扩展

### Requirement: Evidence SHALL pass a relevance gate

所有公共联网候选内容 SHALL 在进入出题 Prompt 前经过结构化相关性评估。只有达到配置阈值、明确保留且能支持用户主题的证据才能注入；系统 SHALL 保留来源、评分、理由、版本适配和冲突分组元数据。

#### Scenario: Relevant evidence is retained

- **WHEN** 候选网页内容直接支持用户主题和岗位方向
- **THEN** 系统 SHALL 保留该证据及其引用，并将过滤后的内容提供给出题模型

#### Scenario: Evidence is irrelevant or ambiguous

- **WHEN** 候选内容与主题无关、评分低于阈值或过滤模型失败
- **THEN** 系统 SHALL 不得注入未过滤正文，并记录 `no_relevant_web_evidence` 或 `evidence_filter_failed`

### Requirement: Agent research failures SHALL be isolated and observable

Agent、个人知识库、Tavily 和过滤器 SHALL 分别具备超时、最多一次重试和明确降级原因。研究失败不得删除已生成题目、答题记录或改变底部导航；任务快照 SHALL 暴露路由、工具、候选数、保留数和降级状态。

#### Scenario: One research tool fails

- **WHEN** 多个搜索或检索工具中只有部分调用失败
- **THEN** 系统 SHALL 使用成功结果继续过滤，不得把整个任务标记为失败

#### Scenario: All research tools fail

- **WHEN** Agent、搜索、提取或过滤均无法获得可信证据
- **THEN** 系统 SHALL 使用基础模型继续逐题生成，并在任务元数据中记录失败阶段和原因

### Requirement: Agent routing SHALL respect cost and latency budgets

系统 SHALL 对每个任务限制 Agent 调用次数、搜索查询数、候选证据数、Prompt 上下文长度和总研究耗时；相同主题、岗位、难度和路由版本的可信研究结果可以缓存复用。

#### Scenario: Research exceeds its budget

- **WHEN** 路由或研究阶段达到调用次数、耗时或上下文上限
- **THEN** 系统 SHALL 停止继续调用工具，保留已有可信证据或降级基础模型，不得阻塞异步任务创建
