# GitHub 同步变更说明

## 对比基线

- 远程仓库：`origin/main`
- 基线提交：`bb22400`（`feat(rag): add structured corpus ingestion and hybrid retrieval`）
- 本次同步内容：基线之后当前工作区的全部已完成改动

## 本次主要改动

### 1. Milvus 原生混合检索

- 使用 Milvus Standalone 原生 Dense + BM25 Function 检索。
- 使用显式 RRF ranker，`MILVUS_RRF_K` 真正生效。
- 配置 dense/BM25 预召回深度和 `fetch_k` 上限，避免默认 `fetch_k=4` 截断候选。
- 保留“宽召回 -> RRF -> DashScope 二阶段精排”的生产链路。
- 移除线上应用层 `rank-bm25`、全量语料扫描、应用层 RRF 和 Cohere 分支。
- `MILVUS_NATIVE_HYBRID_ENABLED=false` 时，在同一 native 集合上执行 dense-only 回退，不删除或切换数据。

### 2. Milvus 运维与隔离

- 完善 native 集合的 schema、BM25 Function、dense/sparse 索引、加载状态和向量维度检查。
- 增加幂等初始化和不兼容 schema 的显式失败保护。
- 健康接口返回脱敏的 Milvus 版本、集合、schema、索引、加载状态和行数摘要。
- 公共检索默认限制为 `published`，支持语料版本和岗位过滤。
- 私有知识库写入、检索、更新、删除均强制 `owner_id` 隔离。
- 增加真实 Standalone 私有知识库 smoke test、迁移脚本和回退演练记录。

### 3. 文档解析与知识库构建

- 增加文件类型识别和内容签名校验，支持 PDF、DOC/DOCX、Office、HTML、Markdown 和图片类型。
- 完善 MinerU 结构化解析流程及 OCR/视觉理解相关模型、数据结构和测试夹具。
- 保留结构化块、页码、章节、表格、代码、公式、图片和来源元数据。

### 4. 评测与可观测性

- 增强 Milvus benchmark：对比 dense-only、native RRF、native RRF + DashScope 三种模式。
- 记录 Hit@k、Recall@k、MRR、nDCG、答案相关性代理指标、来源可追溯性、P50/P95 延迟。
- 记录代码 revision、集合名、RRF 参数、召回深度、Embedding 调用次数、候选数量、精排耗时和降级状态。
- 本次 38 条 golden query 结果：生产路径 Hit@5 `1.0000`、Recall@5 `0.9649`、MRR `0.8649`、nDCG `0.8521`、P95 `580.82ms`，DashScope 精排成功率 `100%`。

### 5. 配置、文档与测试

- `.env` 从 backend 应用根目录稳定加载，并保留环境变量覆盖。
- 更新 Milvus 检索、运维、RAG 流程和迁移说明，移除过时的 Lite/应用层 BM25 主线描述。
- 新增发布基线、运行 smoke test、观察窗口和回滚演练文档。
- 新增及更新后端测试、配置测试、迁移测试、文件解析测试和视觉理解测试。

## 验证结果

- 后端：`pytest` 全部通过。
- 前端：TypeScript 检查、微信小程序构建、15 项前端测试全部通过。
- OpenSpec：严格校验通过，`25/26` 项完成。
- Milvus Standalone：`2.5.16`，公共集合 10,936 行、私有集合 6 行，native schema、BM25 Function、dense/sparse 索引和 loaded 状态正常。
- 真实异步出题：任务从 `queued` 到 `completed`，6/6 题生成成功。

## 尚未自动完成

OpenSpec 剩余 1 项为 6.2：需要在微信开发者工具中进行人工点击验证。该步骤依赖本机 IDE 会话，命令行测试无法替代，因此不会在本次说明中虚报为已完成。

## 隐私检查

本次提交不包含 `backend/.env`、数据库文件、Milvus 数据目录、运行日志、上传文件、微信开发者工具私有配置或真实 API 密钥。
