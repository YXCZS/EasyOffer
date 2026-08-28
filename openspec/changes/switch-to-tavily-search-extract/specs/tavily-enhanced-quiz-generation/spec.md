## Purpose

让 EasyOffer 由 AI 研究 Agent 自主编排 Tavily Search 和 Tavily Extract，兼容关键词与网页输入，动态获取国内外最新资料，并在联网服务失败时自动回退到原有 Prompt。

## ADDED Requirements

### Requirement: AI 可以自主编排 Tavily 工具

系统 MUST 将 Tavily Search 和 Tavily Extract 同时提供给研究 Agent。Agent MUST 根据用户输入、岗位方向、难度、研究目标和已有工具结果决定调用哪个工具、调用顺序、是否需要再次调用以及每次调用的合法参数。后端 MUST 不使用固定的“文本必 Search、URL 必 Extract”单一路由替代 Agent 决策。

#### Scenario: 关键词主题调用搜索工具

- **WHEN** 用户输入 `Harness Engineering` 或 `Java HashMap 扩容机制`
- **THEN** Agent MUST 能调用 `tavily_search` 获取相关资料，并将有效结果交给后续题目生成流程

#### Scenario: 网页地址获取完整页面

- **WHEN** 用户输入一个网页地址
- **THEN** Agent MUST 能调用 `tavily_extract` 获取该页面的正文内容；Agent MAY 在提取后继续调用 `tavily_search` 补充独立资料或验证关键事实

#### Scenario: Agent 根据结果决定追加工具调用

- **WHEN** 首次搜索结果不足以解释主题、存在版本冲突或缺少完整正文
- **THEN** Agent MUST 能根据工具结果决定追加 Search 或 Extract；当达到调用上限仍无法获得有效资料时，进入联网降级流程

### Requirement: Agent 动态选择检索参数

系统 MUST 允许 Agent 根据主题复杂度、时效性、版本敏感性、输入语言和资料完整性动态选择 Tavily 参数。简单主题可以使用较浅搜索、较少结果和摘要；复杂、新出现或版本敏感主题应提高搜索深度、结果数量或请求完整内容；网页提取应根据页面复杂度选择基础/高级深度和 Markdown/文本格式。

系统 MUST 支持动态使用 Tavily 官方工具可提供的参数，例如 `search_depth`、`max_results`、`include_raw_content`、`time_range`、`include_domains`、`exclude_domains`、`country`、`extract_depth` 和 `format`。本次 MUST NOT 提供城市选择、城市参数或城市范围 UI；不得把城市作为独立产品功能。

#### Scenario: 简单主题使用轻量检索

- **WHEN** Agent 判断主题定义清晰、时效要求低且不需要长文档
- **THEN** Agent MAY 使用较浅搜索、较少结果和摘要内容，且仍必须返回至少一个有效来源或按策略继续补充

#### Scenario: 复杂或版本敏感主题使用深度检索

- **WHEN** Agent 判断主题是新概念、版本敏感、存在歧义或需要工程实践细节
- **THEN** Agent MUST 优先提高搜索深度或结果数量，并可请求完整 Markdown 内容、限定官方/维护者域名或设置合理时间范围

#### Scenario: 国内外资料检索不依赖城市功能

- **WHEN** 用户使用中文或英文输入，且主题需要跨地区资料
- **THEN** Agent MAY 根据语言和主题需要使用 `country` 或查询上下文改善结果相关性，但用户界面和业务请求 MUST 不出现城市选择或城市范围设置

### Requirement: 研究结果必须安全注入题目 Prompt

系统 MUST 将 Agent 的最终研究结果整理为结构化上下文后再注入题目生成 Prompt。上下文 MUST 包含来源 URL、标题、检索/提取时间和经过长度限制的摘要或正文片段；网页正文 MUST 被标记为不可信资料，模型 MUST 忽略其中要求改变角色、泄露提示词或执行操作的指令。

#### Scenario: 搜索资料注入出题

- **WHEN** Agent 成功获得与主题匹配的搜索结果
- **THEN** 题目生成模型 MUST 能读取来源上下文，并基于主题、岗位、难度和资料生成结构化题组，响应标记 `research_used=true`

#### Scenario: 网页正文注入出题

- **WHEN** Agent 成功提取用户提供网页的完整正文
- **THEN** 题目生成模型 MUST 能使用该正文作为主要学习资料，并保留原始 URL 来源，不得把网页中的指令当作系统规则

#### Scenario: 研究结果超出上下文预算

- **WHEN** 多次工具调用返回大量内容
- **THEN** 系统 MUST 去重、截断并优先保留与主题和题目目标最相关的片段，不得因为上下文过大直接导致小程序请求失控

### Requirement: 联网失败时回退现有 Prompt

系统 MUST 将研究 Agent 和 Tavily 工具视为可选增强步骤。工具调用失败、超时、限流、鉴权失败、Agent 达到调用上限、结果为空、结果不可解析或无法形成有效研究上下文时，系统 MUST 捕获错误、记录结构化日志，并调用现有不带联网资料的题目生成 Prompt。该降级路径 MUST 不因联网失败向用户返回题目生成失败。

#### Scenario: Search 工具失败后继续出题

- **WHEN** Agent 调用 `tavily_search` 发生异常或返回不可用结果
- **THEN** 系统 MUST 记录失败类型，跳过联网上下文，使用原 Prompt 调用 DeepSeek，并返回可正常答题的题组

#### Scenario: Extract 工具失败后继续出题

- **WHEN** Agent 调用 `tavily_extract` 失败或所有目标 URL 都提取失败
- **THEN** 系统 MUST 记录失败原因，使用原 Prompt 继续生成题目；用户不得因为网页提取失败被强制停留在生成失败页面

#### Scenario: Agent 达到调用上限

- **WHEN** Agent 已达到本轮最大工具调用次数仍未形成有效资料
- **THEN** 系统 MUST 停止继续调用工具，记录 `research_budget_exhausted`，并回退原 Prompt

### Requirement: 区分联网降级与模型生成失败

系统 MUST 在日志和题组元数据中区分“联网研究未使用但题组生成成功”和“DeepSeek 题组生成失败”。只有原 Prompt 的模型调用或结构化校验也失败时，才进入现有题组生成失败流程。

#### Scenario: 联网失败但题组成功

- **WHEN** Agent 或 Tavily 失败且原 Prompt 成功返回合法六道题
- **THEN** 系统 MUST 返回题组并标记 `research_used=false` 或等价降级状态，生成中页面 MUST 正常进入答题页

#### Scenario: 联网成功但模型失败

- **WHEN** Agent 产生有效研究上下文，但 DeepSeek 生成或 Pydantic 校验失败
- **THEN** 系统 MUST 按现有模型生成失败流程处理，不得把研究成功误报为题组成功

### Requirement: 配置和安全边界

系统 MUST 从后端环境变量读取 `TAVILY_API_KEY`，不得把密钥编译进 Taro 前端、写入 API 响应或记录到日志。Agent 工具调用次数、单次超时、最大结果数和最大上下文长度 MUST 可配置；未配置 Tavily Key 或联网开关关闭时，系统 MUST 跳过研究 Agent 并直接使用原 Prompt。

#### Scenario: 未配置 Tavily Key

- **WHEN** 后端没有配置 `TAVILY_API_KEY`
- **THEN** 系统 MUST 记录配置缺失并直接回退原 Prompt，现有核心出题接口仍可用

#### Scenario: Tavily 限流或超时

- **WHEN** Tavily 返回限流或超时异常
- **THEN** 系统 MUST 在配置的有限时间内结束研究步骤，记录可聚合的错误类型，并回退原 Prompt，不得无限重试阻塞小程序请求

### Requirement: 保持现有答题和报告兼容

系统 MUST 保持 `POST /api/v1/quiz/generate` 路径、六道题结构、答案字段、即时反馈、报告生成和底部“答题/我的”导航兼容。新增联网元数据 MUST 使用可选字段或默认值，旧题组和旧历史记录 MUST 能正常渲染。

#### Scenario: 研究增强题组进入答题流程

- **WHEN** Agent 成功完成 Search/Extract 研究并生成合法题组
- **THEN** 用户 MUST 能按现有流程进入答题、提交答案、查看解释和生成报告

#### Scenario: 降级题组进入答题流程

- **WHEN** Agent 或 Tavily 失败但原 Prompt 生成合法题组
- **THEN** 用户 MUST 能按现有流程答题和查看报告，且不需要重新输入主题或重新登录
