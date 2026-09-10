## Context

当前 `POST /api/v1/quiz/generate` 由 `QuizService` 调用 `DeepSeekQuizGenerator`：先用一次模型调用判断主题范围，再直接让 DeepSeek 生成六道题。`Quiz`、`Question` 和 `QuizGenerateOutput` 已经通过 Pydantic 做结构校验，但题目没有来源、检索时间或逐题证据引用，因此模型训练数据过时或主题含义变化时无法被发现。

本变更需要保持现有 Taro 页面、FastAPI 接口入口、题目字段、答题状态和报告流程兼容，同时把 Firecrawl 放在服务端，避免小程序暴露密钥。根据当前官方用法，Firecrawl Python SDK 提供 `Firecrawl.search()` 和 `scrape()`，可返回网页结果与 Markdown；LangChain 的 `ChatPromptTemplate`、`ChatOpenAI(base_url=...)` 和 `with_structured_output(PydanticModel)` 继续作为 DeepSeek 的编排方式；Taro 端继续使用 `Taro.request` 和微信小程序构建流程。

## Goals / Non-Goals

**Goals:**

- 在题目生成前检索最新公开资料，并形成可追溯、可评分的证据包。
- 让新概念和英文术语先经过检索证据判断，避免固定词表和模型旧知识导致误拒或误解。
- 只生成能被来源支持、答案可判定、版本前提明确的题目。
- 对来源不足、来源冲突、Firecrawl 失败和模型校验失败提供可靠拒答与可恢复重试。
- 以向后兼容方式扩展题组响应，支持前端展示来源和时效信息。
- 通过配置化超时、缓存、重试和日志控制外部服务成本与故障影响。

**Non-Goals:**

- 不在本次变更中引入向量数据库、企业知识库 RAG、LangGraph、Agent 或多轮自主工具调用。
- 不支持文档、URL、视频上传；用户输入仍为文本主题。
- 不重做用户系统、底部导航、答题判题、报告评分或历史记录数据模型。
- 不把 Firecrawl 或 DeepSeek API Key 放入前端，也不让小程序直接请求第三方服务。
- 不把“检索成功”当成内容绝对正确；仍需保留 AI 生成标识、来源展示和评估限制。

## Decisions

### 1. 采用证据优先的串行生成管线

生成链路调整为：

```text
输入校验
  -> 主题轻量规范化
  -> Firecrawl 搜索与抓取
  -> 来源清洗、去重、分级和新鲜度计算
  -> 证据包构建
  -> 基于证据的领域判断/歧义判断
  -> 基于证据的题组生成
  -> 独立质量校验
  -> 返回题组或可靠失败
```

初始模型判断只作为软信号，不能在检索前单独拒绝新术语。搜索查询包含用户原文、岗位方向和“software engineering/programming interview”等上下文；最终是否支持由检索证据、岗位方向和模型判断共同决定。这样 `Harness Engineering` 即使不在既有词表中，也有机会通过官方或维护者资料进入正常流程。

备选方案是继续先调用一次领域分类模型，再决定是否搜索；该方案成本略低，但会复现当前“新概念被旧模型误判”的主要问题，因此不采用。

### 2. 使用 Firecrawl 服务端适配层，而不是在业务服务中直接拼第三方请求

新增 `WebResearchProvider` 抽象和 `FirecrawlResearchProvider` 实现。适配层负责：

- 使用 `FIRECRAWL_API_KEY` 初始化官方 Python SDK `Firecrawl`。
- 调用 `search(query, limit, timeout, scrape_options)` 获取候选结果；对入选 URL 再调用 `scrape(..., formats=["markdown", "links"])` 获取正文。
- 在 FastAPI 异步请求中通过异步 HTTP 客户端或线程包装避免阻塞事件循环；具体实现优先复用当前 `httpx` 依赖，SDK 仅作为协议/字段参考。
- 将第三方异常统一转换为内部的搜索不可用、超时、限流和结果不可解析状态。

直接在 `QuizService` 中调用 Firecrawl 会让业务层绑定供应商，后续切换自建搜索或其他服务时会扩大改动面，因此不采用。

### 3. 以证据包作为 LLM 链的唯一事实输入

新增内部数据结构（先以内存对象实现，不新增数据库表）：

```text
ResearchQuery
- raw_topic, normalized_topic, role, difficulty
- queries[], requested_at

SourceEvidence
- source_id, canonical_url, title, site_name
- published_at?, version?, fetched_at
- authority_level, freshness_status
- excerpt, content_hash, supported_claims[]

EvidencePack
- topic, role, evidence[]
- conflict_notes[], research_status, retrieved_at
```

来源处理规则：

1. 规范化 URL，去掉追踪参数，并按 URL 与正文哈希去重。
2. 按官方规范/官方文档、维护者/厂商、高质量专业文章、论坛问答分级。
3. 版本敏感主题优先保留官方或维护者来源；同一站点的重复转载不计为独立来源。
4. 只保留能定位到支持片段的短摘录，不把整页内容发送给模型。
5. 记录抓取时间、发布时间或版本信息，计算 `freshness_status`（`fresh`、`aging`、`unknown`、`stale`）。
6. 至少两个独立来源且版本敏感主题至少一个权威来源时，证据包才进入题目生成；否则可靠拒答。

### 4. 使用 LangChain 结构化输出，但保留 JSON 降级路径

在现有 `DeepSeekQuizGenerator` 中新增基于证据的 Prompt 版本，例如 `quiz-grounded-v1`：

- `ChatPromptTemplate` 注入主题、岗位、难度、证据摘要和来源 ID。
- 通过 `ChatOpenAI(model, base_url, api_key, temperature, timeout, max_retries)` 调用 DeepSeek OpenAI 兼容接口。
- 优先使用 `with_structured_output(QuizGenerateOutput)` 绑定 Pydantic 模型；如果当前 DeepSeek 模型/接口不兼容 JSON Schema，则使用 JSON Object 模式后调用 `model_validate_json()`。
- Prompt 明确禁止使用证据之外的事实，要求每题返回 `source_ids`、`version_context` 和错误选项解释。

报告链仍保持现有实现，不把来源内容重复注入报告请求；报告只消费已经生成的题组和答题记录。

备选方案是把整个网页正文直接拼进 Prompt。该方案会导致 Token、成本和上下文噪声快速增长，不利于移动端请求稳定性，因此只发送短证据片段和结构化元数据。

### 5. 将质量检查分为确定性校验和独立模型校验

确定性校验复用并扩展现有 Pydantic 规则：题量为六道、题目 ID 唯一、题干不重复、答案存在于选项、单选/判断答案唯一、多选答案数量合法、每个选项有解释、来源 ID 存在。

独立模型校验使用低温度、独立 Prompt 检查：

- 核心答案是否被对应证据片段支持；
- 题目是否引入证据之外的关键断言；
- 是否遗漏版本或前提；
- 是否存在多解、歧义或错误选项；
- 题目难度和岗位方向是否匹配。

生成失败时最多进行一次有上下文的修正生成；修正仍不通过则返回失败，不返回未验证题组。校验模型不能修改服务端计算的答题分数，也不能替代来源证据。

### 6. 兼容地扩展领域模型和 API 响应

在现有 `Quiz` 上增加可选字段，旧题组读取时使用默认值：

```text
sources: list[QuizSource] = []
retrieved_at: datetime | None = None
freshness_status: FreshnessStatus = "unknown"
ai_generated: bool = True
research_mode: Literal["grounded", "legacy"] = "grounded"
```

在 `Question` 上增加可选 `source_ids: list[str] = []`。原有 `questions`、`answer`、`explanation`、`version_context` 等字段和 `POST /api/v1/quiz/generate` 路径保持不变，前端可先忽略新增字段而不影响答题。

新增错误状态建议使用独立错误码，保留现有 `4001`、`5001`、`5003` 语义：

| 错误码 | 含义 |
|---:|---|
| 4004 | 主题语境不明确，需要补充信息 |
| 4005 | 没有足够可靠来源 |
| 5021 | Firecrawl 搜索/抓取不可用或超时 |
| 5022 | 来源冲突无法安全生成 |
| 5004 | 题组证据校验失败 |

错误响应继续使用现有 `{code, message, data}` 结构，`data` 中可包含 `retryable`、候选解释和用户可执行的补充提示。

### 7. 使用进程内短期缓存，暂不引入数据库或 Redis

以规范化主题、岗位、难度和版本条件生成缓存键，缓存内容包括证据包和已验证题组。默认只在当前后端进程内使用有上限的 TTL/LRU 缓存：

- 普通主题缓存 7 天；明确版本主题缓存 1 天；
- 缓存命中时返回 `retrieved_at` 和 `cache_hit=true`；
- 不缓存包含用户隐私或敏感信息的原始输入；
- 多进程部署或命中率不足时，再迁移到 Redis，不改变 `EvidencePack` 接口。

这样首版无需新增数据库迁移，也不会把搜索缓存和用户历史记录耦合。

### 8. 前端复用现有生成中页面和题目页面

不新增独立业务页面：

- `quiz-generating` 页面将现有步骤扩展为“理解主题 -> 检索最新资料 -> 校验来源 -> 组织面试题 -> 准备答题环境”，仍由真实 API 请求驱动，不使用固定等待时间伪装完成。
- 失败页面根据错误码显示“补充主题”“重新检索”或“稍后重试”，保留返回修改主题入口。
- 题目讲解区域增加轻量来源入口和“检索于/适用版本”信息，答案提交前不展示来源正文或引用内容。
- 现有底部“答题/我的”、答题进度、即时反馈和报告跳转不变。

### 9. 配置、日志和安全边界

新增配置项：

```text
firecrawl_api_key
firecrawl_base_url (默认官方服务地址)
firecrawl_timeout_ms (默认 30000)
firecrawl_result_limit (默认 5)
research_cache_ttl_seconds
quiz_evidence_mode (默认 required)
```

所有密钥只从后端 `.env` 读取；日志记录请求 ID、规范化主题、来源数量、来源等级、缓存命中、各阶段耗时和失败类型，不记录 API Key、完整网页正文或用户身份信息。只允许用户打开 `https` 来源 URL，来源正文按最小必要片段保存，遵循现有内容安全、版权和隐私约束。

## Risks / Trade-offs

- [Firecrawl 额度或网络不稳定] -> 设置 30 秒超时、有限重试、缓存和明确的可重试错误；监控搜索失败率和单次成本。
- [搜索结果仍然包含 SEO 垃圾或错误转载] -> 域名/站点分级、正文可访问性检查、内容去重、最低来源门槛和独立质量校验；来源不足时拒答。
- [新概念搜索结果不足导致误拒] -> 采用原文 + 岗位上下文 + 软件工程语境的多查询策略，并把拒答原因展示给用户，允许补充关键词重试。
- [模型把证据片段拼接成错误结论] -> 题目生成和独立验证分离，要求逐题 `source_ids`，验证失败不下发。
- [新增来源字段导致旧数据或前端类型不兼容] -> 字段全部可选并提供默认值，先更新后端模型和 API 测试，再更新前端类型与展示。
- [同步请求耗时超过小程序体验或网关限制] -> 复用现有生成中页面，后端设置阶段超时和可观测耗时；本次仍保持单请求，超过稳定阈值后再拆异步任务。
- [用户误把来源支持当作绝对正确] -> 显示“AI 生成并经自动校验”、检索时间、版本前提和评估限制，不宣称内容绝对无误。
- [回滚时退回旧的无来源生成] -> 默认 `quiz_evidence_mode=required`；只有运维明确设置紧急 `legacy` 模式才允许临时回滚，并在日志和响应中标记，恢复后立即关闭。

## Migration Plan

1. 增加 Firecrawl 配置、后端依赖和 `WebResearchProvider`，默认不开启新链路的生产流量。
2. 增加来源、证据、错误状态和题组扩展模型；旧题组缺少新增字段时使用兼容默认值。
3. 在测试环境开启 `quiz_evidence_mode=required`，用 `Harness Engineering`、TCP 三次握手、Java HashMap 和一个非技术主题执行回归。
4. 通过 pytest、前端类型检查、微信小程序构建和开发者工具手动流程后，再逐步放量。
5. 若 Firecrawl 或证据链出现阻断性问题，将开关临时设为 `legacy` 以恢复服务，同时保留告警和问题记录；修复并回归后恢复 `required`。
6. 本次不需要数据库迁移。未来将缓存迁移到 Redis 或保存来源审计记录时，另起独立 OpenSpec 变更。

## Open Questions

无。Firecrawl 已确认作为首版搜索/抓取服务；具体额度和生产域名可通过配置在部署阶段调整，不改变本设计和行为规格。
