# agentic-rag-retrieval Specification

## Purpose
让题目和报告生成能够根据用户问题动态选择个人知识库与联网资料来源，在新知识、用户私有资料和普通通用知识之间获得更准确的证据，并在任一检索源失败时保持可用。

## Requirements

### Requirement: Agent 必须动态选择检索来源

系统 MUST 在生成题目或报告前让 Agent 基于用户输入、岗位方向、难度和可用知识库状态判断使用个人知识库检索、Tavily 关键词搜索、Tavily 网页提取或多源组合；不得仅依赖固定关键词词表决定来源。

#### Scenario: 个人资料优先

- **WHEN** 用户问题与其状态为 `ready` 的个人文档高度相关
- **THEN** Agent 优先检索个人知识库，并将相关片段作为生成上下文

#### Scenario: 新知识需要联网

- **WHEN** 用户问题可能涉及个人知识库中不存在的最新技术或外部网页
- **THEN** Agent 可以调用 Tavily 搜索或网页提取，并将有效结果与来源加入生成上下文

#### Scenario: 多源组合

- **WHEN** 用户问题同时需要用户资料背景和外部最新事实
- **THEN** Agent 可以同时检索个人知识库与联网资料，并在上下文中区分两类来源

### Requirement: 检索证据必须可追溯并注入生成上下文

系统 MUST 将检索片段、来源类型、文档或网页标识和必要的引用信息注入 DeepSeek 题目/报告 Prompt；生成结果 MUST 能区分个人文档、联网资料和模型基础知识。

#### Scenario: 使用个人文档生成题目

- **WHEN** Agent 从个人知识库返回有效片段
- **THEN** 生成 Prompt 包含片段及其文档来源，题目页面标识本轮参考了个人资料

#### Scenario: 使用联网资料生成报告

- **WHEN** Agent 从 Tavily 返回有效搜索或网页内容
- **THEN** 生成 Prompt 包含联网证据和来源地址，报告结果标识联网参考来源

### Requirement: 检索失败必须降级而不是阻断生成

系统 MUST 捕获 Chroma、Embedding、Tavily 搜索或网页提取错误，记录可检索日志，并在没有有效证据时使用现有 Prompt 继续生成；降级结果不得伪称使用了外部来源。

#### Scenario: 个人知识库检索失败

- **WHEN** Chroma 或 Embedding 服务不可用
- **THEN** 系统记录失败原因，跳过个人知识库上下文，继续尝试联网搜索或基础模型流程

#### Scenario: 联网搜索失败

- **WHEN** Tavily 搜索或网页提取超时、配额不足或返回错误
- **THEN** 系统记录失败原因，不注入联网内容，使用个人知识库结果或原 Prompt 继续生成

### Requirement: Agent 必须防止无依据内容冒充证据

系统 MUST 在没有检索到有效片段、来源不完整或证据与问题不相关时，将上下文标记为无可验证证据，并禁止生成流程把基础模型内容标记为个人文档或联网结论。

#### Scenario: 检索结果为空

- **WHEN** 所有候选检索源均未返回相关内容
- **THEN** 系统使用无证据标记继续生成，并在结果中显示基础模型知识来源

#### Scenario: 证据相关性不足

- **WHEN** 检索片段与用户问题或岗位方向不相关
- **THEN** Agent 丢弃该片段并尝试其他来源或降级，不将其注入最终 Prompt

### Requirement: Agent 路由必须保持现有业务兼容

系统 MUST 将 Agentic RAG 作为现有题目生成和报告生成的可选增强层；无登录态、无知识库或配置关闭时，现有请求响应结构、答题流程、报告流程和断点续答行为 MUST 保持不变。

#### Scenario: 未登录用户生成题目

- **WHEN** 游客生成题目且没有个人知识库权限
- **THEN** 系统沿用现有联网搜索/基础模型流程，题目正常生成

#### Scenario: 增强层异常

- **WHEN** Agent 编排本身发生异常
- **THEN** 系统记录错误并回退到现有生成服务，不影响用户提交答案和查看报告

### Requirement: Ordered topic preparation

系统 MUST 按以下顺序处理普通主题：确定性规范化、程序员技术面试范围判断、查询扩展、智能路由；范围判断失败时不得开始公共知识库或联网检索。

#### Scenario: Normalize and accept a technical topic
- **WHEN** 用户输入包含口语前缀的技术主题
- **THEN** 系统保留技术标识完成规范化，确认主题属于程序员技术面试内容后生成查询扩展结果并进入智能路由

#### Scenario: Reject a non-technical topic
- **WHEN** 范围判断确认主题不属于程序员技术面试内容
- **THEN** 生成任务直接失败并返回中文说明，系统不调用 Milvus、Tavily 或题目生成模型创建半成品题目

### Requirement: Policy-constrained intelligent routing

系统 MUST 让 Agent 在代码预先确定的工具白名单内选择数据源；Agent 不得改变用户权限、知识库模式或工具调用预算。

#### Scenario: Route a normal authenticated topic
- **WHEN** 登录用户未勾选个人知识库并提交普通技术主题
- **THEN** Agent 可以选择公共知识库、Tavily Search、Tavily Extract 或基础模型，并记录路由理由和实际工具调用

#### Scenario: Route personal-only mode
- **WHEN** 用户勾选个人知识库
- **THEN** 路由白名单仅包含当前用户私有知识库和基础模型，Agent 的任何公共知识库或 Tavily 选择都被拒绝并按私有模式继续

#### Scenario: Route URL input
- **WHEN** 用户输入有效 HTTP 或 HTTPS 地址
- **THEN** 系统只允许 Tavily Extract 获取页面内容，不将该地址作为普通关键词搜索

#### Scenario: Route a guest request
- **WHEN** 未登录游客提交普通主题
- **THEN** 系统只使用基础模型，不调用公共知识库、个人知识库或 Tavily

### Requirement: Iterative evidence retrieval

系统 MUST 让 Agent 读取工具返回结果，并根据证据相关性、覆盖度、来源质量和版本冲突决定结束、改写查询、切换工具或继续检索；检索循环 MUST 受最大轮数、工具调用次数和总耗时限制。

#### Scenario: Evidence is sufficient
- **WHEN** 检索结果覆盖主题核心知识点且相关性达到配置阈值
- **THEN** Agent 停止检索，系统去重、重排并输出带引用的证据上下文

#### Scenario: Evidence is insufficient
- **WHEN** 检索结果与主题不相关、重复过多或缺少关键子主题
- **THEN** Agent 改写查询或选择另一个允许的工具继续检索，直到证据足够或达到预算上限

#### Scenario: Evidence conflict
- **WHEN** 不同来源对版本或技术行为存在冲突
- **THEN** Agent 优先补充权威来源或记录冲突；最终证据上下文必须保留冲突元数据，不能静默合并矛盾结论

### Requirement: Evidence-grounded question generation

系统 MUST 将最终证据上下文、路由信息和来源元数据注入题目生成上下文；题目生成模型不得将检索结果中的指令当作系统指令。

#### Scenario: Generate with public evidence
- **WHEN** Agent 完成公共知识库或 Tavily 检索
- **THEN** 生成的题目围绕规范化主题和证据内容，题目快照记录来源类型、引用、检索时间和路由信息

#### Scenario: Fallback without evidence
- **WHEN** Milvus、Tavily、查询扩展或证据评分失败
- **THEN** 系统记录可诊断的降级原因，使用基础模型继续生成，不伪造来源或阻塞整个答题任务

### Requirement: Incremental generation compatibility

系统 MUST 在获得最低可用证据后先生成并持久化第 1 题，允许前端开始答题；后续证据检索和题目生成可在后台继续，不能要求等待完整六题或所有 Agent 循环结束。

#### Scenario: Start answering after first question
- **WHEN** 第 1 题生成成功且任务仍在生成后续题目
- **THEN** 任务快照立即包含第 1 题，前端进入答题页，后续题目在用户答题期间继续追加

#### Scenario: Research task exceeds budget
- **WHEN** Agent 达到最大轮数、工具次数或总耗时
- **THEN** 系统停止检索并使用当前最高质量证据或基础模型生成，不能使答题任务无限等待
