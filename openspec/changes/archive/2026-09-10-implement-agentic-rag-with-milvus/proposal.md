## Why

EasyOffer 当前的联网检索主要由固定流程和受限路由完成，无法根据检索结果动态决定继续搜索、改写查询或提取网页全文；同时，用户知识库仍依赖 Chroma，项目缺少可按岗位过滤的公共技术知识库。现在需要在不改变 MySQL 业务表、COS 图片存储和现有逐题答题流程的前提下，建立可扩展的 Milvus 知识库，并用 LangGraph 实现真正受控的 Agentic RAG。

## What Changes

- 新增项目公共技术面试知识库，使用 Milvus 保存向量分块，支持按岗位方向、技术名称、版本和发布状态过滤。
- 将用户上传文档的向量存储从 Chroma 迁移到 Milvus 私有知识库；保留现有 MySQL 文档元数据、处理状态和用户权限逻辑。
- 在普通登录用户流程中引入 LangGraph 检索图，让 Agent 在公共 Milvus、Tavily Search、Tavily Extract 和基础模型之间进行受控选择。
- 固化主题处理顺序：确定性规范化 -> DeepSeek 技术面试范围判断 -> 查询扩展 -> LangGraph 路由与检索。
- 增加检索结果评分、查询改写、重复结果去除、证据冲突识别和有限次数的循环检索。
- 支持用户勾选“使用个人知识库”；勾选后只允许检索当前用户的私有 Milvus 和使用基础模型，不允许访问公共 Milvus 或 Tavily。
- 游客继续只使用基础模型；URL 主题继续只允许 Tavily Extract。
- 保留现有异步任务、逐题生成、答题进度、报告生成、图片生成和 COS 流程，首题达到最低证据阈值后即可生成。
- 增加 Milvus 配置、索引初始化、数据迁移、回滚和检索链路测试。
- **不做** MySQL 业务表结构重设计，不将文档或向量存入 COS，不改动底部“答题/我的”导航，不在本变更中增加知识库管理后台。

## Capabilities

### New Capabilities

- `project-knowledge-base`: 建立按岗位和技术元数据组织的公共 Milvus 知识库，并将用户文档存入带用户隔离的私有 Milvus 知识库。
- `agentic-rag-retrieval`: 使用 LangGraph 编排主题判断后的智能检索，让 Agent 在允许的数据源之间选择、循环检索并输出经过评分的证据上下文。

### Modified Capabilities

无。当前仓库没有已发布的主规格文件；现有答题和知识库行为将在新能力规格中以兼容约束描述。

## Impact

- 后端：`app/research/`、`app/services/knowledge_service.py`、向量存储适配器、配置和依赖；需要新增 LangGraph/Milvus 集成。
- API：保留现有生成任务和知识库 API 契约，仅增加知识库模式和检索元数据所需的兼容字段（如确有必要）。
- 数据：MySQL `knowledge_documents` 等现有表保持不变；Milvus 新增公共和私有 collection 及索引，原始文件仍按现有逻辑保存，COS 仍只用于图片。
- 前端：答题首页增加/接入个人知识库选择状态，并保持现有生成、答题、进度恢复和报告流程不变。
- 运维：新增 Milvus Standalone 配置，后续可升级 Distributed；需要提供初始化、双写迁移、校验和回滚步骤。
- 性能与成本：Agent 检索循环必须受最大轮数、工具调用次数、总耗时和上下文长度限制，避免影响首题延迟和 Tavily 成本。
