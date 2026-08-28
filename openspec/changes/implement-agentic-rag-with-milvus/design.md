## Context

See `proposal.md` and the two capability specifications for the motivation and observable behavior. 当前后端已经有 MySQL 文档元数据、Chroma 用户向量存储、Tavily Search/Extract、主题范围判断和逐题生成任务；图片仍通过 COS 保存。设计必须在保留这些业务边界的前提下增加公共知识库和真正的 Agentic RAG 检索循环。

## Goals / Non-Goals

**Goals:**

- 用 Milvus Standalone 承载公共和私有知识库向量，并通过元数据过滤实现岗位、用户和文档隔离。
- 将普通登录用户的主题处理固定为“规范化 -> 范围判断 -> 查询扩展 -> LangGraph 路由与检索”。
- 让 LangGraph Agent 真正读取工具结果，在公共 Milvus、Tavily Search、Tavily Extract 和基础模型之间进行受控决策，并支持证据评分、查询改写和有限循环。
- 让“使用个人知识库”成为硬路由开关：只开放私有 Milvus 与基础模型。
- 在获得最低可用证据后继续现有逐题生成，让第 1 题不等待完整研究流程。
- 提供 Chroma 到 Milvus 的双写迁移、校验、切换和回滚路径。

**Non-Goals:**

- 不重构现有 MySQL 业务表，不把文档或向量放入 COS。
- 不在本变更中开发公共知识库管理后台、审核管理页面或新的底部导航。
- 不改变现有题目、答题、报告、图片生成和任务轮询 API 的核心语义。
- 不让 Agent 自行修改权限、用户范围、工具预算或个人知识库模式。

## Decisions

### 1. Vector storage: Milvus Standalone with two collections

选择 Milvus Standalone 作为第一阶段部署形态，使用两个固定 collection：

- `easyoffer_public_chunks`
- `easyoffer_private_chunks`

公共 collection 的关键字段包括 `chunk_id`、`text`、`dense_vector`、`role_tags`、`technology`、`source_url`、`source_type`、`version`、`language`、`status` 和发布时间；私有 collection 额外包含 `owner_id`、`document_id`、`source_name`、`chunk_index` 和 `content_hash`。公共岗位通过标量过滤表达，不按岗位复制 collection；私有数据通过 `owner_id` 和可选 `document_id` 过滤。

初期使用 COSINE 稠密向量索引。Milvus Standalone 已为后续 BM25 稀疏向量和 RRF 混合检索保留扩展空间；当公共资料规模和关键词召回需求验证后，再启用稠密 + BM25 混合索引，而不是首期同时引入两套召回逻辑。

替代方案：pgvector 与现有 PostgreSQL 结合简单，但项目使用 MySQL，迁移关系数据库的代价高；Qdrant 过滤和部署友好，但本项目后续需要大规模混合检索，Milvus 的 Standalone/Distributed 路径更合适；继续使用 Chroma 仅适合本地小规模数据。

### 2. Keep MySQL metadata and COS image boundary

现有 `knowledge_documents` 和答题业务表继续作为元数据与状态事实源。上传、解析、失败重试、重命名、删除和权限校验沿用现有 API；向量写入由 Chroma 适配器替换为 Milvus 适配器。原始用户文档仍按当前本地存储逻辑处理，本变更不把它们迁移到 COS。COS 仅继续保存头像和题目配图。

### 3. Explicit preprocessing before the graph

生成任务的研究入口拆成可测试的顺序阶段：

```text
normalize_topic
  -> topic_scope_judge
  -> query_expansion (keyword topics only)
  -> policy_guard
  -> LangGraph route/retrieve loop
```

规范化是确定性清洗；查询扩展是通过 DeepSeek 产生多个检索表达，不能混称。URL 直接进入 Extract 目标，不做关键词扩展；个人知识库模式的扩展仅用于优化私有 Milvus 查询，不得产生公共 Web 调用；游客跳过外部检索。

范围判断必须完成并通过后才允许启动查询扩展和检索。现有 `prepare_incremental` 中并行启动判断和证据任务的行为需要改为上述顺序，避免非技术主题消耗 Milvus/Tavily。

### 4. LangGraph StateGraph for controlled Agentic RAG

使用 LangGraph 的 `StateGraph`、`ToolNode` 和条件边构建显式图，而不是把整个流程封装在黑盒 Agent 中。当前 LangGraph 文档已将旧的 `create_react_agent` 标记为弃用，若使用预构建 Agent 应采用 `langchain.agents.create_agent`；本项目因需要细粒度状态和权限控制，选择显式 StateGraph。

图状态至少包含：`normalized_topic`、`scope_judgement`、`expanded_queries`、`mode`、`allowed_tools`、`search_round`、`tool_call_count`、`candidate_sources`、`evidence_items`、`coverage`、`confidence`、`conflicts`、`elapsed_ms` 和 `fallback_reason`。

图节点与边：

```text
START
  -> route_controller
       -> private_milvus (personal-only)
       -> public_milvus (normal authenticated)
       -> tavily_search (freshness/coverage gap)
       -> tavily_extract (URL or selected authoritative page)
       -> finish_base_model (guest/fallback)
  -> grade_evidence
       -> finalize_evidence (sufficient)
       -> rewrite_query -> route_controller (insufficient, budget available)
       -> tavily_extract (page content required)
       -> finalize_evidence (budget exhausted)
```

工具必须是真实的 Milvus/Tavily 调用，工具返回值回写图状态后再由 Agent 决策。`policy_guard` 在图外或图的入口执行白名单校验；私有模式和 URL 模式使用硬路由，不允许模型覆盖。

### 5. Routing policy and retrieval order

普通登录用户的默认工具白名单为公共 Milvus、Tavily Search、Tavily Extract 和基础模型。优先查询公共 Milvus；证据不足、过期或冲突时，Agent 再选择 Tavily Search，必要时对权威 URL 使用 Extract。Agent 可决定查询词、轻量/深度搜索和是否继续，但代码限制最多 3 轮、最多 5 次工具调用、总研究时间 35～40 秒，并限制上下文字符数。

勾选个人知识库后，白名单变为私有 Milvus 和基础模型，路由固定为私有 collection；不执行公共 Milvus、Tavily 或其他用户文档检索。游客白名单仅为基础模型。URL 白名单仅为 Tavily Extract 和基础模型。

### 6. Evidence grading and grounding

检索结果统一转换为带来源、版本、岗位、分数和时间的证据项。评分节点判断相关性、核心子主题覆盖、来源权威性和版本冲突；低相关结果不得进入题目 Prompt。最终上下文使用现有 `EvidenceContext` 契约，增加路由、查询计划、工具调用、候选数、过滤数和降级原因等元数据。

证据内容作为不可信资料注入 Prompt，并明确禁止将其中的指令当作系统指令。无证据时使用基础模型生成，但不伪造引用。

### 7. Incremental question integration

研究图提供“最低可用证据”回调或结果快照。增量服务收到该结果后立即生成并保存第 1 题；Agent 的剩余检索可以在后台继续，后续题目使用更新后的证据。现有任务轮询、题目去重、答题进度和图片异步任务保持不变。

### 8. Public corpus ingestion

公共资料以离线/运维导入命令进入流水线：抓取或导入 -> 解析 -> 清洗 -> 内容和 URL 去重 -> 语义分块 -> Embedding -> 质量审核 -> 写入 Milvus -> 发布。每个分块必须保存来源、版本、岗位标签和内容哈希。Tavily 运行时结果只作为本次证据，不能自动写入公共库；经过审核后才允许转为公共资料。

### 9. Dependency and configuration

增加与当前 LangChain 版本兼容的 `langgraph`、`langchain-milvus` 和 `pymilvus` 依赖；保留 `langchain-tavily`。新增 Milvus URI、Token、collection 名称、向量维度、检索阈值、最大轮数、工具调用预算和超时配置，全部通过环境变量读取并更新 `.env.example`。Embedding 模型和维度必须在 collection 初始化时固定并写入迁移元数据。

## Risks / Trade-offs

- **[Risk] Agent 循环增加首题延迟或 Tavily 成本** -> 先公共 Milvus、批量并发 Search，设置 3 轮/5 次/35～40 秒硬上限，并在最低证据阈值处释放第 1 题。
- **[Risk] Agent 选择越权工具导致隐私泄露** -> 由代码生成不可变工具白名单，工具层强制 `owner_id`/`document_id` 过滤，路由结果二次校验。
- **[Risk] Milvus 服务不可用** -> 任务记录可诊断的 `milvus_*` 降级原因；普通模式回退 Tavily 或基础模型，个人模式只回退基础模型，不跨越模式边界。
- **[Risk] Chroma 与 Milvus 迁移产生召回差异** -> 迁移期双写并对同一查询进行离线召回对比，未达到阈值不切换读路径；保留 Chroma 只读回滚窗口。
- **[Risk] 公共资料质量或版权问题** -> 保存来源和版本，发布前审核，Tavily 结果不自动入库，并提供下架状态过滤。
- **[Risk] 版本升级造成 LangGraph API 变化** -> 锁定经过测试的依赖范围，使用显式 StateGraph/ToolNode，并用节点级单元测试隔离 LangGraph 适配代码。
- **[Risk] 现有异步任务状态与研究图状态不一致** -> 以 MySQL generation task 为业务事实源，图状态仅用于本次研究；每次证据快照写入任务元数据，失败可从当前任务阶段重试。

## Migration Plan

1. 部署 Milvus Standalone，初始化公共和私有 collection、索引及健康检查；不改变现有 API。
2. 增加 Milvus 适配器和配置，先以双写模式处理新上传用户文档，继续以 Chroma 作为读路径。
3. 导入你提供的公共资料及经过审核的官方资料，完成质量检查和岗位标签校验。
4. 批量迁移历史用户文档，按 `owner_id/document_id/content_hash` 校验分块数量和 Embedding 维度。
5. 运行离线召回对比和 Agent 场景测试；通过后将私有检索读路径切换到 Milvus。
6. 启用公共 Milvus 优先和 LangGraph 检索图，观察首题延迟、Tavily 调用次数、证据覆盖率和失败率。
7. 稳定运行一个回滚窗口后停止 Chroma 双写；保留 Chroma 快照和回滚开关，确认无误后再清理旧数据。

回滚策略：关闭 Agentic RAG 开关即可回到基础模型/Tavily 现有管线；关闭 Milvus 读开关即可回到 Chroma；MySQL 文档元数据、答题任务和 COS 图片不受回滚影响。任何迁移步骤失败都不得删除 Chroma 或 MySQL 数据。

## Open Questions

- 公共知识库第一批资料的具体文件清单、来源许可和岗位标签由产品侧在导入前确认；不改变本设计的存储和路由结构。
- Milvus Standalone 的最终运行位置（本机 Docker、云主机或托管服务）可在部署阶段确定，只要满足 URI、鉴权、持久卷和备份要求。
