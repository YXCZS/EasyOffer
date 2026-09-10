## Purpose

为 EasyOffer 建立受权限、成本和时延约束的 Agentic RAG 检索流程，让 Agent 根据主题和证据质量动态选择知识库或 Tavily 工具，并在必要时改写查询继续检索。

## ADDED Requirements

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

