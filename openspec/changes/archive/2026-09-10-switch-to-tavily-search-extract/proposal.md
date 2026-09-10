## Why

EasyOffer 需要同时处理“用户输入技术关键词”和“用户输入网页地址”两类学习材料。固定由后端判断输入类型并调用单一工具，难以覆盖复杂知识、网页内容补充和跨语言资料场景；因此需要让 AI 同时使用 Tavily Search 和 Tavily Extract，自主决定工具、调用顺序和检索参数。

联网增强仍然不能成为核心出题流程的硬依赖。Tavily 调用失败时，系统必须记录失败并回退到现有 Prompt，保证用户仍能完成题目生成。

## What Changes

- **BREAKING（内部实现）**：移除待实施方案中的固定 URL 路由和 Firecrawl 选型，改为 LangChain Tavily 工具驱动的研究 Agent。
- 同时向研究 Agent 提供 `TavilySearch` 和 `TavilyExtract`，由 AI 根据用户输入和研究目标决定何时调用哪个工具、是否调用多个工具以及调用顺序。
- 普通关键词必须支持 Tavily Search；用户提供网页地址时，Agent 必须能够使用 Tavily Extract 获取页面正文，并可根据需要追加 Search 进行交叉补充。
- 允许 Agent 动态调整 Tavily 参数：简单主题优先摘要和少量结果，复杂/新/版本敏感主题提高搜索深度、结果数量并请求完整内容；网址内容根据页面复杂度选择提取深度和格式。
- 支持国内外资料检索，但本次不增加城市选择、城市参数或城市范围 UI；地区相关性由语言、查询上下文和 Tavily 可用的国家参数自行处理。
- 将 Agent 研究结果清洗、截断、去重后注入题目生成 Prompt，并保留来源标题、URL、摘要/正文片段和检索时间。
- 正常路径：研究 Agent 成功调用工具 -> 研究结果注入 Prompt -> DeepSeek 生成更准确的题目。
- 降级路径：工具调用失败、超时、限流、鉴权失败或研究结果不可用 -> 捕获错误并记录日志 -> 不注入研究结果 -> 使用原 Prompt 照常出题。
- 将联网降级成功与模型生成失败区分开，响应中标记本轮是否使用联网资料。
- 保持现有 `POST /api/v1/quiz/generate`、题目结构、答题流程、报告流程和底部“答题/我的”导航兼容。
- 本次不引入城市功能、向量数据库、用户系统重构、异步任务队列、其他搜索供应商自动切换或文档上传流程。

## Capabilities

### New Capabilities

- `tavily-enhanced-quiz-generation`: 由 AI 研究 Agent 自主编排 Tavily Search/Extract，为题目生成提供可选的最新网页上下文，并在外部服务失败时可靠降级到原有 Prompt。

### Modified Capabilities

无。当前 `openspec/specs/` 中尚无已归档的题目生成能力规格；本变更会替代尚未实施的 `improve-ai-question-generation` 变更中的 Firecrawl 和固定工具路由方案。

## Impact

- 后端：新增 LangChain Tavily 研究 Agent、工具调用限制、研究结果结构化输出、Prompt 上下文注入和降级编排。
- 依赖：使用 `langchain-tavily` 提供 `TavilySearch` 和 `TavilyExtract`，按官方方式配置 `TAVILY_API_KEY`。
- API：保持生成接口兼容，可新增 `research_used`、`research_mode`、`sources`、调用摘要和 fallback 原因元数据。
- 前端：生成中页面展示“正在查找或提取资料”；题组可显示“已参考联网资料”或“本轮使用基础模型知识”，工具失败不阻断进入答题页。
- 测试：覆盖 Agent 选择 Search、Agent 选择 Extract、Agent 多工具调用、动态参数、工具失败回退和原 Prompt 失败等场景。
- 运维：记录工具调用次数、参数摘要、耗时、失败分类和降级率；不记录密钥、完整网页正文或用户身份信息。
