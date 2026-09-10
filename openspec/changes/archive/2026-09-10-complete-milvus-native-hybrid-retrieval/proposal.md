## Why

Milvus Standalone 已经接入 EasyOffer，并且公共知识库能够通过原生 BM25 Function 与向量检索返回结果，但当前实现还没有完全兑现设计目标：LangChain 默认使用 WeightedRanker，`MILVUS_RRF_K` 没有生效；每路混合检索的预召回数量仍受默认 `fetch_k=4` 限制；应用层 BM25 兼容代码仍保留；私有知识库也缺少真实写入、隔离和删除的端到端验证。现在需要把检索主线收敛为可观测、可复现、可回滚的 Milvus Standalone 原生混合检索，并补齐运行配置和验收证据。

## What Changes

- 显式使用 Milvus 原生 RRFRanker，并让 `MILVUS_RRF_K` 真正控制融合参数。
- 将 dense/BM25 每路预召回数量显式传入混合检索，避免 LangChain 默认 `fetch_k=4` 截断候选集。
- 固化公共和私有集合的 native hybrid schema、索引、加载和健康检查契约。
- 保证公共检索只读取符合状态、版本和岗位过滤条件的数据，私有检索始终执行 `owner_id` 隔离。
- 完成私有文档真实写入、检索、权限隔离、更新和删除的 smoke test，并保留可重复测试数据清理步骤。
- 将后端 `.env` 加载方式改为不依赖启动工作目录，避免从仓库根目录启动时丢失 Embedding/DashScope 配置。
- 将应用层 `rank-bm25` 标记为迁移兼容分支，生产主线不再启用；在确认所有运行环境均使用 Standalone native hybrid 后移除依赖和旧分支。
- 增强 Milvus 检索错误日志，记录集合、检索模式、过滤条件摘要和失败类型，但不得输出 API Key 或用户文档原文。
- 增加检索质量、延迟和运维验收记录，包括 native hybrid 与旧 dense-only 结果对比、p50/p95 延迟、集合行数和加载状态。

## Capabilities

### New Capabilities

- `milvus-native-hybrid-retrieval`: 定义基于 Milvus Standalone 原生 Dense + BM25 + RRF 的检索、过滤、配置和验证契约。

### Modified Capabilities

- None.

## Impact

- 后端：`app/services/knowledge_service.py`、`app/services/milvus_admin.py`、`app/core/config.py` 及启动配置。
- 测试：Milvus adapter/admin 测试、真实 Standalone smoke test、私有 owner 隔离和删除测试、检索 benchmark。
- 依赖：确认 `langchain-milvus`/`pymilvus` 兼容版本；完成迁移后清理 `rank-bm25` 生产依赖。
- 运维：继续使用 `http://127.0.0.1:19530` 的 Standalone；旧 Lite 数据只作为迁移备份，不参与线上查询。
- 兼容性：保持现有“答题”和“我的”页面、题目生成、答题进度和报告流程不变；检索接口返回结构保持兼容。
