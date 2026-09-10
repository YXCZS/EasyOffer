## Purpose

为 EasyOffer 的联网出题流程提供稳定、可追溯且低噪声的研究证据，让用户不精确的技术表达也能得到覆盖充分的资料，同时避免无关搜索内容干扰题目生成。

## ADDED Requirements

### Requirement: Keyword research SHALL expand the user query before searching

当 Agentic RAG 路由选择关键词联网搜索时，系统 SHALL 在首次 Tavily Search 前调用一次查询规划能力，基于原始输入、岗位方向和难度生成规范主题及不超过 3 个语义互补的查询。扩展查询 SHALL 保留原始学习意图，不得引入用户未提及且无岗位关联依据的新技术主题。

#### Scenario: Informal topic produces complementary queries
- **WHEN** 用户输入口语化或包含多个知识点的程序员面试主题并进入关键词联网搜索
- **THEN** 系统 SHALL 生成 1-3 个不重复查询，覆盖规范术语、核心原理/用法和岗位面试语境，并将原始主题保留在研究上下文中

#### Scenario: Query planner returns invalid output
- **WHEN** 查询规划返回空内容、非法结构、重复查询或明显偏离原始主题的结果
- **THEN** 系统 SHALL 最多重试一次，仍失败时 SHALL 使用规范化后的原始主题作为唯一搜索查询，并记录查询扩展降级原因

### Requirement: Expanded keyword searches SHALL be bounded and failure tolerant

系统 SHALL 并行执行扩展查询，限制查询总数、单查询结果数、单次研究总超时和上下文长度。单个 Tavily 查询失败不得丢弃其他成功结果；只有所有查询均失败时才进入联网研究降级。

#### Scenario: Partial search failure
- **WHEN** 三个扩展查询中只有部分 Tavily Search 请求成功
- **THEN** 系统 SHALL 合并成功请求的结果继续执行去重和相关性过滤，并记录失败查询的错误类型，不得将整个任务标记为联网研究失败

#### Scenario: All searches fail
- **WHEN** 扩展查询和其重试请求全部无法获得 Tavily 结果
- **THEN** 系统 SHALL 不向出题 Prompt 注入空或伪造的联网证据，记录 `web_search_failed` 类降级原因，并允许基础模型继续生成题目

### Requirement: Search results SHALL be deduplicated before AI filtering

系统 SHALL 在相关性评分前对搜索结果执行 URL 规范化、相同 URL 去重、标题/正文指纹去重和明显无正文结果清理，并限制候选结果数量。去重 SHALL 保留来源元数据和可访问引用地址。

#### Scenario: Duplicate results from multiple queries
- **WHEN** 不同扩展查询返回相同 URL 或内容高度相似的页面
- **THEN** 系统 SHALL 只保留一个候选证据，优先保留内容更完整或来源质量更高的版本，并保留其标题、站点、URL 和检索时间

### Requirement: Candidate evidence SHALL pass AI relevance filtering before prompt injection

系统 SHALL 将原始用户输入、规范主题、岗位方向和去重后的候选结果交给一次结构化 AI 过滤，输出每个候选的相关性评分、是否保留、理由和可支持的知识主张。只有达到配置相关性阈值的候选证据 SHALL 进入题目生成上下文；未通过过滤的内容不得直接拼接到出题 Prompt。

#### Scenario: Relevant evidence is retained
- **WHEN** 候选结果直接解释用户主题并符合岗位方向
- **THEN** 过滤结果 SHALL 标记为保留并提取可用于出题的知识主张，最终上下文 SHALL 包含来源引用和过滤元数据

#### Scenario: Irrelevant evidence is removed
- **WHEN** 搜索结果只是关键词偶然命中、属于其他领域或与用户岗位无关
- **THEN** 过滤结果 SHALL 标记为不保留，题目生成 SHALL 不得看到该候选的正文内容

#### Scenario: Filtering returns no relevant evidence
- **WHEN** 所有候选结果低于相关性阈值或无法支持用户主题
- **THEN** 系统 SHALL 记录 `no_relevant_web_evidence`，不注入未过滤结果，并按现有基础模型降级策略继续或返回可重试状态

### Requirement: URL extraction SHALL filter page chunks before prompt injection

当用户输入 HTTP/HTTPS URL 并由 Tavily Extract 获取正文时，系统 SHALL 按章节或受限长度切分正文，将内容块连同用户主题和岗位方向提交相关性过滤。URL 流程 SHALL 不执行关键词查询扩展，但过滤后的证据契约与搜索结果一致。

#### Scenario: Long page contains relevant and irrelevant sections
- **WHEN** 提取页面同时包含目标技术正文、导航、广告或无关章节
- **THEN** 系统 SHALL 只保留高相关内容块，并在出题上下文中保留页面 URL 和对应片段引用

#### Scenario: Extraction fails
- **WHEN** URL 无法访问、Tavily Extract 超时或返回空正文
- **THEN** 系统 SHALL 记录 `web_extract_failed` 类原因，不得把错误响应当作证据，并按基础模型或可重试失败策略处理

### Requirement: Research-stage failures SHALL preserve the existing quiz flow

查询规划、Tavily 搜索/提取和 AI 过滤 SHALL 具有独立超时、最多一次重试和明确日志；任何研究阶段失败都不得删除已生成的增量题目、答题记录或改变“答题/我的”底部导航。研究成功时 SHALL 暴露工具、来源数量、过滤状态和降级原因等元数据。

#### Scenario: Research planner or filter times out
- **WHEN** 查询规划或相关性过滤超过其阶段超时时间
- **THEN** 系统 SHALL 停止该阶段的等待，记录超时原因，并使用允许的降级路径继续生成，不得让创建任务请求同步阻塞至整套题完成

#### Scenario: Research metadata is exposed
- **WHEN** 题目任务成功生成且使用了联网证据
- **THEN** 快照和最终题组 SHALL 保留研究工具、来源、过滤后证据数量、路由和降级字段，前端现有生成页和答题页 SHALL 能继续正常渲染

### Requirement: Personal knowledge-only mode SHALL remain isolated

当用户通过指定 `document_id` 进入个人知识库专属答题模式时，系统 SHALL 跳过查询扩展、Tavily Search 和 Tavily Extract；该模式只允许指定用户文档的证据或既有基础模型降级，不能将公共联网内容混入题目上下文。

#### Scenario: Document-only request
- **WHEN** 用户选择一个已准备好的个人知识库文档并开始答题
- **THEN** 系统 SHALL 只检索该文档内容并生成题目，研究元数据不得报告 Tavily 工具调用
