## Context

现有 EasyOffer 已有 FastAPI 用户系统、DeepSeek 题目/报告生成、Tavily 搜索与网页提取，以及 Taro 微信小程序的“答题 / 我的”导航。此次变更需要在不改变既有生成请求和答题状态流转的前提下，增加用户私有文档处理和多源检索编排。具体行为以 `specs/user-document-knowledge-base/spec.md` 和 `specs/agentic-rag-retrieval/spec.md` 为准。

## Goals / Non-Goals

**Goals:**

- 建立可持久化、按用户隔离的 Chroma 个人知识库。
- 支持 PDF、Word、Markdown 的可追踪处理流水线和失败重试。
- 通过 LangChain Agent 统一编排 Chroma 检索、Tavily Search、Tavily Extract 和证据上下文构造。
- 在题目生成和报告生成中复用同一检索上下文协议，并保持无知识库时的降级兼容。
- 让用户在小程序内看到文档状态、来源类型和必要的失败提示。

**Non-Goals:**

- 不实现团队共享、跨用户检索、知识库导出或多设备文件同步。
- 不支持图片 OCR、扫描件、音频、视频和超大压缩包解析。
- 不重做登录、XP、题目生成 Prompt、答题状态或报告数据模型。
- 不把原始文档全文直接写入 MySQL；MySQL 只保存元数据和处理状态。

## Decisions

### 1. 使用 MySQL 元数据 + 文件存储 + Chroma 向量存储

新增 `knowledge_documents` 表保存 `user_id`、原始文件名、存储路径、文件哈希、MIME、大小、状态、错误信息、分块数量、Embedding 模型版本和时间戳。原文件保存于受控上传目录（后续可替换为对象存储），文本分块和向量保存到 Chroma `persist_directory`。

每个用户使用独立 collection（命名规则 `easyoffer_user_<user_id>`），向量 metadata 必须包含 `document_id`、`chunk_index`、`source_name` 和 `content_hash`。API 先校验 JWT 的用户归属，再访问对应 collection；删除文档时按 `document_id` 删除向量。选择用户 collection 是为了降低误用 metadata filter 的越权风险；替代方案是共享 collection + `user_id` filter，资源更集中但更依赖所有查询路径正确带过滤条件，本阶段不采用。

### 2. 文档处理采用可重试的后台流水线

上传接口只负责校验、落盘、创建 `processing` 记录并投递后台任务，避免微信请求超时。后台任务按“解析 -> 清洗 -> 分块 -> Embedding 批处理 -> Chroma 写入 -> 状态 ready”执行，每一步记录结构化日志和可定位错误。任务使用 `document_id` 作为幂等键：相同文件哈希重复上传可提示已有文档，重试先删除该文档此前写入的向量再重新写入，避免重复 chunk。

解析器优先使用 LangChain 内置 `PyPDFLoader`、`Docx2txtLoader` 和 `UnstructuredMarkdownLoader`，按扩展名和 MIME 双重判断；解析结果为空、页数异常或超过配置上限时进入 `failed`。

### 3. Embedding 与 Chroma 集成保持可配置

默认使用百炼 `text-embedding-v4`，通过环境变量配置 API 地址、密钥、批大小和维度；Embedding 接口封装在独立 provider 中，避免把供应商调用散落到业务服务。Chroma 使用持久化客户端，应用启动时检查目录和 collection 可用性；Embedding 失败不写入半成品向量，文档保持 `failed`。

### 4. 使用统一的检索上下文协议

新增内部 `EvidenceContext` 结构，包含 `evidence[]`、`source_types`、`citations`、`used_personal_kb`、`used_web`、`fallback_reason` 和检索耗时。题目生成服务和报告生成服务只消费该结构，不直接依赖 Chroma 或 Tavily 的返回格式。每条 evidence 设最大字符数、来源标识和相关性分数，超过上下文预算时按分数截断。

### 5. Agent 使用工具调用而不是硬编码关键词

向 LangChain Agent 暴露三个工具边界：个人知识库检索、Tavily Search、Tavily Extract。Agent 输入包含用户主题、岗位方向、难度、用户是否有 ready 文档和可用工具状态；由模型决定调用一个或多个工具。URL 输入优先允许 Extract，概念型输入允许 Search；工具参数（最大结果数、搜索深度、提取页面数量和上下文预算）由服务端配置和请求复杂度共同限制，避免无限调用。

Agent 输出必须经过结构化校验：来源类型、引用、片段和相关性字段缺失时视为无有效证据；工具异常只记录日志并交给降级编排。Agent 不直接生成最终题目或报告，最终内容仍由现有 DeepSeek 生成服务负责。

### 6. 检索降级顺序

正常路径为“Agent 选择工具 -> 获取 evidence -> 构造 Prompt -> DeepSeek 生成”。个人知识库失败时尝试 Tavily；Tavily 失败时使用另一已成功来源；所有来源均失败或为空时沿用当前基础 Prompt。上下文中显式写入 `source_types`，前端只根据后端返回的来源字段展示提示，禁止将降级结果显示为联网或个人资料结果。

### 7. API 与前端边界

新增鉴权接口：上传文档、查询文档列表、查询单文档状态、重试处理、删除文档。上传使用 multipart，返回 `document_id`；状态轮询使用轻量 GET，前端在“我的”页面展示列表，不增加底部导航项。题目/报告接口继续使用原请求结构，可在响应中追加可选 `evidence_meta` 字段，旧客户端忽略该字段也能正常工作。

### 8. 配额、清理与安全

通过配置限制单文件大小、单用户文档数、单文档分块数、Embedding 批大小和每日处理次数；上传文件名不直接作为路径，使用随机 ID 存储并校验路径归属。删除用户或文档时执行 MySQL 元数据、原文件和 Chroma 向量的补偿清理；清理失败进入重试队列并告警。日志只记录 document_id、user_id 和错误摘要，不记录完整文档内容或敏感 Prompt。

## Risks / Trade-offs

- [本地 Chroma 磁盘损坏或多进程并发写入] -> 单写入队列、持久化目录健康检查、定期备份；生产部署时将 Chroma 目录放在独立持久卷。
- [Embedding 或 Tavily 配额耗尽] -> 批量调用、并发上限、指数退避和基础 Prompt 降级；在文档状态和日志中保留可读错误。
- [Agent 选择错误工具] -> 工具描述、结构化输出校验、来源相关性阈值和多源回退；不满足证据条件时不得标记为已联网。
- [长文档造成处理超时或上下文膨胀] -> 页数/字符/分块上限、批处理、Top-K 和上下文预算截断。
- [用户隔离失误] -> collection 按用户拆分、所有 API 强制 JWT 归属校验、跨用户和删除幂等测试。
- [上传恶意文件或路径穿越] -> MIME/扩展名双校验、随机存储名、路径归一化、病毒扫描接口预留和下载接口默认关闭。

## Migration Plan

1. 增加 MySQL 幂等迁移，创建文档元数据表和索引；不修改现有用户、题组、报告表。
2. 发布文档上传/列表/状态/删除 API、文件存储配置和 Chroma 健康检查，但暂不接入题目生成。
3. 发布文档处理后台任务与 Embedding provider，使用测试用户验证解析、重试、删除和用户隔离。
4. 发布统一 EvidenceContext 和 Agent 路由，默认开启降级；题目和报告响应追加来源元数据。
5. 发布小程序“我的知识库”UI，先以灰度配置开放；观察处理失败率、检索命中率和降级率。
6. 回滚时关闭 Agent 增强开关，题目/报告回到原 Prompt；文档表、文件和 Chroma 数据保留，重新开启后可继续处理。

## Open Questions

- 生产环境原始文件最终使用本地磁盘还是对象存储，需要在部署阶段根据容量和备份策略确定；接口和处理服务按抽象存储接口设计，不改变本次规格。
