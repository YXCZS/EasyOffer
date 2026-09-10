## Context

现有 Milvus Standalone 已有两套 `_hybrid_v2` 集合，schema 包含 `pk`、`text`、dense `vector`、BM25 输出 `sparse` 和 `text_bm25` Function。公共集合已迁移 10,936 条数据，私有集合已创建但当前为空。`MilvusVectorStore.search()` 已经能够调用 LangChain Milvus 的多向量检索，随后执行 DashScope 二阶段重排。

本变更只收敛 Milvus 检索和运维能力，不改变 Taro 页面、题目生成接口、答题进度或报告接口。动机和范围见 `proposal.md`，外部行为契约见 `specs/milvus-native-hybrid-retrieval/spec.md`。

## Goals / Non-Goals

**Goals:**

- 让 native hybrid 明确执行 dense + BM25，并显式使用配置的 RRF。
- 让预召回数量真正传到 Milvus，保留“先广召回、再 RRF、再 DashScope rerank”的质量策略。
- 保证公共版本过滤、岗位过滤和私有 owner 隔离在 Milvus 端和应用端都可验证。
- 完成从配置加载、集合健康、真实写入到删除的可重复验收。
- 让旧 Lite 和应用层 BM25 只作为有边界的迁移备份，不成为生产隐式依赖。

**Non-Goals:**

- 不在本变更中改为 Milvus Distributed、引入 Kubernetes 或实现高可用集群。
- 不重建已有公共集合，不删除 `data/milvus-lite` 备份，也不改变现有 chunk ID 和 metadata 契约。
- 不替换 DashScope Embedding 或 DashScope TextReRank 模型。
- 不把前端检索参数暴露给微信小程序用户。

## Decisions

### 1. 在 native hybrid 调用中显式指定 RRF

优先使用当前 `langchain-milvus` 支持的 `reranker=Function(... FunctionType.RERANK ...)` 表达 Milvus RRF；初始化时验证安装的 `langchain-milvus`/`pymilvus` 版本和函数参数。如果当前版本的 Function RERANK API 不兼容，则在短期兼容适配器中使用 `pymilvus.RRFRanker(k)`，并通过测试确认传给 `hybrid_search` 的 strategy 为 `rrf`、k 为配置值。

选择显式 RRF 是为了避免 LangChain 在 `ranker_type=None` 时默认创建 `WeightedRanker`。不选择继续使用默认加权排序，因为它会使 `MILVUS_RRF_K` 失效，并且 dense 与 BM25 的分数尺度难以直接比较。

### 2. 在 Milvus 请求层保留广召回

检索适配器计算一个经过边界校验的 `fetch_k`，至少覆盖 `MILVUS_DENSE_RECALL_K`、`MILVUS_SPARSE_RECALL_K` 和最终请求 k；在 LangChain 能分别表达每路 limit 时分别传入，在只能使用统一 `fetch_k` 时传入两者最大值，并在日志中记录实际值。候选融合后才截断到最终 k，再调用 DashScope rerank。

这样可以修复当前 `_collection_hybrid_search()` 默认 `fetch_k=4` 导致的候选截断。相比直接把最终 k 调大，单独记录每路召回深度可以继续支持质量评测和成本调节。

### 3. 保留现有集合和 metadata，禁止隐式旧集合查询

继续使用 `easyoffer_public_chunks_hybrid_v2` 和 `easyoffer_private_chunks_hybrid_v2`。启动初始化只做存在性、schema、索引和加载状态检查；发现 dense 维度、BM25 Function 或 sparse 索引不兼容时失败并给出修复提示，不自动创建同名错误集合。公共查询默认附加 `status=published`（调用方显式要求草稿时才允许特殊模式），私有查询始终追加当前 `owner_id`。

### 4. 分阶段下线应用层 BM25

第一阶段将 native 路径和兼容路径的 feature flag、日志和指标分离，并增加测试证明 native 模式不会调用全量 `query()` 构建 BM25 索引。第二阶段在所有运行环境完成 Standalone smoke test 后，删除 `rank-bm25` 依赖、缓存和旧 `_bm25_search/_rrf_merge` 测试；若仍需本地离线迁移工具，迁移工具独立保留，不进入在线 adapter。

不直接删除兼容代码的原因是需要保留一次可回滚窗口，避免 Standalone 服务临时不可用时让答题主流程完全中断。

### 5. 用稳定路径加载后端配置

将设置模型的 `.env` 路径解析为相对于 backend 应用根目录的绝对路径，并继续允许进程环境变量覆盖文件值。启动时只输出非敏感配置摘要，例如 Milvus URI、集合名、native 开关和模型名；任何密钥只输出是否存在，不输出值。

### 6. 用真实 Standalone smoke test 作为发布门禁

测试使用唯一前缀创建临时私有文档，写入最小但包含明确技术词的 chunk，验证 dense/BM25 命中、owner 隔离、更新替换和删除清理。公共集合只读验证，不修改已发布数据。测试失败时必须执行 finally 清理临时记录，并将集合行数恢复到测试前状态。

评测报告固定记录代码 revision、集合名/版本、RRF k、每路召回深度、rerank 配置、Recall@k、Hit@k、MRR、nDCG、答案相关性、来源可追溯性及 p50/p95 延迟；不把一次小样本 smoke test 宣称为统计显著结论。

## Risks / Trade-offs

- [RRF API 版本差异] → 启动时做版本和 ranker 构造检查；优先新 Function API，保留短期 `RRFRanker` 适配，并用调用拦截测试确认实际 strategy。
- [召回深度增大带来延迟和内存] → 对 recall/fetch_k 设置上限，记录 p50/p95，先以 50/50 为基线再通过 golden set 调参。
- [中文 BM25 analyzer 效果不稳定] → 先保持现有 Standalone schema，使用中文技术词 golden set 验证；需要换 analyzer 时新建版本化集合并走迁移，不原地破坏线上集合。
- [DashScope 不可用] → native RRF 结果仍可返回，记录 reranker 失败；不回退到应用层全量 BM25，避免不可控延迟。
- [私有 smoke test 污染数据] → 使用随机 document_id/chunk_id、显式 owner_id 和 finally 删除；测试前后比较集合行数。
- [配置路径改动影响部署] → 同时支持环境变量注入，先在仓库根目录和 backend 目录分别启动配置检查，再重启 API。
- [删除 rank-bm25 破坏旧脚本] → 在清理前扫描引用并更新测试/迁移说明；应用层兼容分支只有在 Standalone 门禁通过后才删除。

## Migration Plan

1. 记录当前 Standalone 版本、集合 schema、行数、加载状态和基线检索指标；保留 Lite 目录作为只读备份。
2. 部署显式 RRF 和 fetch_k 代码，先保持 `MILVUS_NATIVE_HYBRID_ENABLED=true`，运行单元测试及真实 Standalone smoke test。
3. 在同一公共集合和 golden query 集上执行 dense-only、native hybrid+RRF、native hybrid+RRF+DashScope 三组对比，确认质量和 p95 延迟门禁。
4. 验证从仓库根目录启动后仍能读取 Embedding、DashScope 和 Milvus 配置，再重启后端并检查健康接口。
5. 发布后观察检索错误率、rerank 降级次数、召回深度和延迟；出现问题时只回退代码/feature flag，不删除 native 集合。
6. 稳定运行一个观察窗口后移除在线 `rank-bm25` 兼容依赖和代码；旧 Lite 数据仍按运维保留周期保存。

回滚策略：恢复上一版应用代码和配置即可继续读取现有 `_hybrid_v2` 集合；若需完全回退到旧 dense-only 集合，必须显式切换集合名并先通过召回一致性验证，禁止自动回退。

## Open Questions

- 无需阻塞本变更的问题。Milvus Distributed、高可用备份和中文 analyzer 的进一步调优属于后续独立变更。
