# EasyOffer 公共面试语料架构清单

## 边界

公共语料是离线治理流程。它不新增 MySQL 业务表，不改变 COS 用途，不增加小程序页面，也不修改 Agentic RAG 路由。COS 仍只保存头像和题目图片；公共和个人向量仍存 Milvus；未确认许可的第三方资料只能本地评估。

## 现有扩展点

| 责任 | 文件与符号 | 本变更的接入方式 |
| --- | --- | --- |
| 公共/个人向量适配 | `backend/app/services/knowledge_service.py`：`MilvusVectorStore`、`get_public_vector_store` | 使用稳定 `chunk_id`、动态元数据、状态和岗位过滤；公共写入前校验许可与元数据 |
| 公共证据检索 | `backend/app/research/agentic_graph.py`：`public_milvus_search` | 路由不变；只读取 `status=published` 的公共分块，并精确恢复父级证据 |
| 个人知识库 | `backend/app/services/knowledge_service.py`：`get_vector_store` | 不接入公共语料；用户专属模式仍只读个人集合和基础模型 |
| 主题准备和联网降级 | `backend/app/research/evidence.py`、`agentic_router.py` | 不改变查询扩展、Tavily 或基础模型降级策略 |
| 离线治理管线 | `backend/app/corpus/pipeline.py`：`CorpusPipeline` | 负责预览、候选摄取、质量检查、评估、审批、发布、撤回和补偿回滚 |
| 资料清单 | `backend/app/corpus/manifest.py`、`models.py` | YAML 显式登记来源、版本、岗位、技术、许可和目标语料版本 |
| 解析和父子切分 | `backend/app/corpus/parsers.py`、`chunking.py` | PDF/DOCX/Markdown 解析；结构优先，递归切分兜底，保留页码和父子关系 |
| 去重和质量 | `backend/app/corpus/dedup.py`、`quality.py` | 稳定哈希、精确/近重复检测、许可/乱码/答案/元数据检查 |
| 检索评估 | `backend/app/corpus/evaluation.py` | 固定查询集和 Top-K，输出排名、来源、延迟及发布门禁指标 |
| 运维入口 | `backend/app/corpus/cli.py` | `python -m app.corpus.cli`，输出 JSON，阻断操作返回非零退出码 |

## 运行时事实源

- 版本控制事实源：`backend/corpus/config.yaml`、`manifests/`、`benchmarks/`、`reviews/`。
- 运行产物：`backend/data/public-corpus/`，包含批次、评估、审批和发布报告，不提交 Git。
- 检索事实源：Milvus `easyoffer_public_chunks`，正式检索只读取已发布状态。
- 原始第三方正文不写入 MySQL、COS 或审计报告。

