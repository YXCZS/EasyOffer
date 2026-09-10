# milvus-native-hybrid-retrieval Specification

## Purpose
为 EasyOffer 提供稳定、可复现且可审计的 Milvus Standalone 原生混合检索能力，让技术面试知识同时获得向量召回与关键词召回，并在公共、私有知识库之间保持严格的数据隔离。

## Requirements

### Requirement: Native hybrid retrieval uses explicit rank fusion

系统 MUST 在启用 Milvus native hybrid 模式时，同时执行 dense 向量检索和 BM25 关键词检索，并使用显式配置的 RRF 参数进行融合；不得依赖客户端库的隐式默认排序策略。融合参数 MUST 可由 `MILVUS_RRF_K` 配置，并在检索日志或诊断结果中可确认实际生效值。

#### Scenario: Dense and lexical candidates are fused with configured RRF

- **WHEN** 用户提交一个同时包含语义表达和明确技术标识符的查询
- **THEN** 系统从 dense 和 BM25 两条检索路径获取候选，使用配置的 RRF `k` 融合后再进入二阶段重排

#### Scenario: Ranker configuration is observable

- **WHEN** native hybrid 检索成功或失败
- **THEN** 系统记录集合、检索模式、RRF 参数和候选数量等诊断信息，且不记录 API Key、完整用户文档或完整查询敏感内容

### Requirement: Hybrid retrieval preserves broad recall

系统 MUST 对 dense 和 BM25 分别使用可配置的预召回数量，并将该数量实际传入 Milvus hybrid search；客户端默认值不得将每路候选静默限制为 4 条。预召回数量必须经过正数校验，并在超过 Milvus 或系统上限时使用明确的上限策略。

#### Scenario: Configured recall depth reaches Milvus

- **WHEN** `MILVUS_DENSE_RECALL_K` 和 `MILVUS_SPARSE_RECALL_K` 配置为有效值
- **THEN** 每条检索路径按配置值或明确计算出的统一 `fetch_k` 召回候选，融合前不会被客户端默认值覆盖

#### Scenario: Invalid recall configuration is rejected safely

- **WHEN** 预召回配置为零、负数或非数字
- **THEN** 系统在启动配置校验或首次检索前报告可诊断错误，不发起不可控的 Milvus 请求

### Requirement: Public retrieval honors publication and version filters

公共知识库检索 MUST 默认只返回已发布且符合请求版本、岗位和状态过滤条件的 chunk。旧版本可以保留用于回滚或审计，但不得在默认线上检索中与当前发布版本混合返回。

#### Scenario: Published version excludes inactive version

- **WHEN** 同一文档存在一个 `published` 版本和一个 `inactive` 版本，用户按默认方式检索
- **THEN** 返回结果只包含 `published` 版本

#### Scenario: Role and corpus filters are enforced

- **WHEN** 用户指定岗位或公共 corpus 版本
- **THEN** 系统在 Milvus 过滤和结果防御性校验后，只返回匹配岗位或版本的内容

### Requirement: Private retrieval enforces owner isolation

私有知识库的每条写入、检索、更新和删除操作 MUST 绑定用户身份。任何用户不得通过查询参数、文档 ID 或过滤表达式读取、修改或删除其他用户的 chunk。

#### Scenario: User retrieves only own document

- **WHEN** 用户 A 检索私有知识库
- **THEN** 结果只包含 `owner_id=A` 的 chunk，即使查询词命中用户 B 的文档也不得返回

#### Scenario: Cross-owner document operation is denied

- **WHEN** 用户 A 尝试更新或删除用户 B 的文档
- **THEN** 系统拒绝操作并记录安全事件，不改变用户 B 的数据

### Requirement: Native collections have a stable operational contract

系统 MUST 使用固定、可识别的 native hybrid 集合命名和 schema，集合必须包含主键、原文检索字段、dense 向量字段、BM25 sparse 输出字段及对应索引。应用启动或运维初始化 MUST 可幂等执行，并提供集合存在、加载状态和服务版本的健康检查。

#### Scenario: Initialization is idempotent

- **WHEN** 运维命令对已存在的 native 集合重复执行初始化
- **THEN** 不删除已有数据、不重复创建冲突 schema，并返回集合已存在且可加载的结果

#### Scenario: Missing or incompatible schema is detected

- **WHEN** 目标集合缺少 BM25 Function、sparse 字段、索引或 dense 维度不匹配
- **THEN** 系统报告明确的不兼容错误，并阻止静默写入错误集合

### Requirement: Runtime configuration is independent of working directory

后端 MUST 从稳定的应用配置根目录加载 `.env` 或等价环境变量，使从仓库根目录、backend 目录或服务管理器启动时使用同一套 Milvus、Embedding 和 DashScope 配置。敏感配置 MUST 只通过环境变量或未提交的本地配置提供。

#### Scenario: Backend starts from repository root

- **WHEN** 服务进程的工作目录是仓库根目录
- **THEN** 能正确读取 backend 的配置文件或已注入环境变量，Milvus 检索不会因 API Key 未加载而退化为空结果

#### Scenario: Secrets are not exposed

- **WHEN** 记录启动配置、健康检查或检索异常
- **THEN** 日志和 Git 变更中不包含 API Key、Token 或完整用户文档内容

### Requirement: Legacy application BM25 is not the production path

当 native hybrid 模式可用时，系统 MUST 不在应用进程中加载完整 Milvus 文本集合来构建 `rank-bm25` 索引，也不得对 native 结果再做第二次应用层 BM25 融合。兼容分支必须有明确的开关、日志和下线条件。

#### Scenario: Native mode avoids application corpus scan

- **WHEN** native hybrid 模式开启且集合 schema 兼容
- **THEN** 检索只调用 Milvus native dense/BM25 hybrid，不执行应用层 BM25 全量 query 或 RRF 合并

#### Scenario: Compatibility fallback is explicit

- **WHEN** native 模式被显式关闭或检测到不兼容环境
- **THEN** 系统才允许进入兼容路径，并记录降级原因；生产默认配置不得静默降级

### Requirement: Retrieval quality and operational acceptance is reproducible

系统 MUST 提供可重复执行的检索验收流程，至少覆盖 dense-only、native dense+BM25+RRF 和加 DashScope rerank 三种模式，并记录 Recall@k、Hit@k、MRR、nDCG、答案相关性、来源可追溯性以及 p50/p95 延迟。验收数据 MUST 标注代码版本、集合版本和关键检索配置。

#### Scenario: Benchmark compares the same corpus and queries

- **WHEN** 运维人员使用同一 golden query 集执行三种检索模式
- **THEN** 报告按相同问题、相同发布版本和相同评测口径输出可比较指标

#### Scenario: Regression gate catches quality or latency loss

- **WHEN** 新实现的核心指标低于设定阈值，或 p95 延迟超过门禁
- **THEN** 验收失败并阻止将新检索配置标记为生产通过
