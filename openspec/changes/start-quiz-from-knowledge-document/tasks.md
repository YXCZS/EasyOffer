## 1. 后端请求契约与文档校验

- [x] 1.1 在 `QuizGenerateRequest` 增加可选 `document_id` 字段并保持旧请求可解析；运行模型校验测试确认不带该字段的普通请求仍通过
- [x] 1.2 在题目生成服务入口查询当前用户文档并校验归属与 `ready` 状态；为跨用户、未知文档和 `processing`/`failed` 文档分别编写 pytest 并确认不会调用检索或模型
- [x] 1.3 定义专属模式的错误码/错误消息映射，接入现有 FastAPI 异常处理；运行接口测试确认前端可复用生成失败页面且不泄露他人文档信息

## 2. 单文档证据检索与题目生成

- [x] 2.1 扩展知识库服务和 Chroma 适配器的检索签名，支持按 `document_id` 使用 `where` 过滤，并增加结果元数据二次校验；运行检索单元测试确认不会混入其他文档分片
- [x] 2.2 在证据构建中增加 `document_only`/`document_id` 分支，专属模式优先使用当前文档 Chroma 证据，证据不足时切换基础模型，并显式跳过 Tavily Search、Tavily Extract 和其他文档；使用 mock 工具编写 pytest 验证外部工具未被调用
- [x] 2.3 对专属文档证据不足场景降级到基础模型生成，不触发联网降级且在 `evidence_meta` 记录 `fallback_reason=document_content_insufficient`；运行服务测试覆盖空检索、低置信度检索和基础模型生成三种情况
- [x] 2.4 在 DeepSeek 生成调用链中传递专属证据或基础模型降级标志，并在 `evidence_meta` 写入 `route=document_only`、`document_id`、`used_personal_kb`、`used_web=false`、`used_base_model` 与命中分片数；运行 schema/序列化测试确认元数据可持久化
- [x] 2.5 为未携带 `document_id` 的普通请求增加回归测试，确认原有 Agentic RAG 路由、Tavily 降级和题目保存行为不变

## 3. 前端知识库入口与生成上下文

- [x] 3.1 在知识库 `ready` 文档卡片按原型增加使用现有主题色的“开始闯关”按钮，并保持文档信息与删除操作布局；运行 Taro typecheck 确认类型和条件渲染无误
- [x] 3.2 点击按钮时保存当前 `documentId`、服务端文档名及默认岗位/难度上下文，直接跳转现有题目生成中页面；在页面级测试或手动检查中确认不会经过“我的”页面且 processing/failed 文档无可用按钮
- [x] 3.3 扩展前端 `generateQuiz` 请求参数和生成页读取逻辑，将 `document_id` 及专属标志发送给后端；运行请求 mock 测试确认普通模式不发送文档字段、专属模式携带正确 ID
- [x] 3.4 为 `PracticeSession` 增加可选文档来源字段并兼容旧版本地会话；运行 session 序列化/恢复测试确认普通练习和文档练习都能进入答题、断点续答及报告页面
- [x] 3.5 沿用现有生成失败、重试和返回答题首页交互，展示文档不可用或基础模型降级的可读提示；运行前端 lint/typecheck 并手动检查重试请求仍携带原文档 ID

## 4. 集成验证与交付

- [x] 4.1 运行后端完整 pytest（包含权限、检索隔离、工具调用和普通流程回归）并修复失败用例
- [x] 4.2 运行前端 TypeScript 检查和微信小程序构建，确认答题、我的、知识库页面均能编译
- [ ] 4.3 在微信开发者工具验证已登录用户从 ready 文档点击“开始闯关”到生成、答题、保存进度和报告的完整链路，并验证 processing/failed、游客和跨用户请求均被阻止
- [ ] 4.4 检查生成结果的 `evidence_meta` 与服务日志，确认专属练习全程没有 Tavily 请求且证据分片全部属于当前文档；记录验证结果作为变更交付说明
