## 1. 游客会话与访问控制

- [x] 1.1 增加匿名会话标识生成、服务端哈希绑定和任务/快照/进度校验，并用游客越权测试验证任务 ID 不能跨会话访问
- [x] 1.2 增加游客生成开关、并发/每日额度和 MySQL 原子计数迁移，验证超限返回明确错误且不影响已开始任务
- [x] 1.3 修改生成任务依赖，使游客可以创建普通主题任务；验证游客不能提交 `document_id`、访问知识库或用户历史

## 2. Agentic RAG 路由核心

- [x] 2.1 定义 `PolicyEnvelope`、Agent 状态和结构化 `RouteDecision` Schema，验证未知工具、越权路由、非法 JSON 和超预算输出都会被拒绝
- [x] 2.2 使用 LangChain v1 `create_agent`、动态工具白名单和 `ToolStrategy` 接入路由 Agent，并用 `ToolCallLimitMiddleware` 验证全局及按工具调用上限
- [x] 2.3 实现登录用户、游客、URL 和 `document_id` 四类工具白名单，验证文档专属模式永不暴露 Tavily，游客永不暴露 Chroma
- [x] 2.4 将 Query Expansion、个人知识库检索、Tavily Search 和 Tavily Extract 注册为受控工具，验证参数、超时、重试和不可信内容包装

## 3. 证据与出题集成

- [x] 3.1 将 Agent 路由接入现有证据上下文，保留去重、相关性过滤、来源引用、冲突分组和最多 5 条证据限制
- [x] 3.2 将游客和登录用户的 ResearchProvider 注入增量生成服务，验证研究失败时基础模型仍能生成第一题
- [x] 3.3 保持逐题追加、重复题校验、后台继续生成和答题记录恢复，验证 Agent 研究不会覆盖已有题目或答案
- [x] 3.4 增加 Agent、Query Expansion、过滤器和工具版本到缓存键与任务元数据，验证缓存版本变化不会复用旧证据

## 4. 前端与错误体验

- [x] 4.1 适配游客任务创建、匿名会话持久化和限流错误提示，验证游客可从生成页进入答题页
- [x] 4.2 保持现有生成页 6 秒轮询、首题跳转和后续题追加，验证任务失败、重试和研究降级不会出现空白页
- [x] 4.3 保持文档专属入口、答题恢复、报告入口和“答题/我的”导航，验证登录用户现有流程无回归

## 5. TDD 与质量验证

- [x] 5.1 增加游客鉴权、匿名额度、文档隔离和越权访问后端测试，运行 `pytest -q backend/tests`
- [x] 5.2 增加 Agent 路由决策、工具白名单、调用预算、Query Expansion、部分失败和基础模型降级测试
- [x] 5.3 使用 React Hooks、Harness Engineering、RAG、URL 文档和多知识点主题验证 Agent 路由、来源引用和题目唯一性
- [x] 5.4 运行 `python -m compileall -q app`、前端 `npm run typecheck` 和 `npm run build:weapp`
- [x] 5.5 在微信开发者工具验证游客生成、登录生成、文档专属答题、首题跳转、后续题追加、限流提示、答题恢复和报告流程
