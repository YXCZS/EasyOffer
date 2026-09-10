## Purpose

为 EasyOffer 提供可按岗位检索的项目公共技术知识库和严格隔离的用户私有知识库，使题目生成既能复用经过审核的技术资料，也能支持用户仅基于自己的文档学习。

## ADDED Requirements

### Requirement: Public knowledge corpus lifecycle

系统 MUST 支持将公共技术资料依次经过抓取或导入、解析、清洗、去重、分块、向量化、质量审核和发布，只有已发布且通过审核的内容才能参与普通用户检索。

#### Scenario: Publish an approved public document
- **WHEN** 管理流程完成资料解析、去重、分块、向量化和质量审核
- **THEN** 系统将文档分块及其来源、技术名称、岗位标签、版本和发布状态写入公共知识库，并允许检索到已发布分块

#### Scenario: Reject an unapproved document
- **WHEN** 公共资料未通过质量审核或处理失败
- **THEN** 系统不得将其作为可用公共证据返回，并保留失败原因供后续处理

### Requirement: Role-scoped public retrieval

系统 MUST 支持按岗位方向、技术名称、语言、版本和发布状态过滤公共知识库检索结果；一份资料可以同时归属多个岗位方向。

#### Scenario: Retrieve backend evidence
- **WHEN** 登录用户选择后端岗位并输入 Redis 持久化主题
- **THEN** 系统只返回与该主题相关且状态为已发布、岗位标签匹配的公共知识片段，并保留来源和版本信息

#### Scenario: Shared document across roles
- **WHEN** 一份公共资料同时标记为通用基础和后端岗位
- **THEN** 通用基础和后端检索均可使用该资料，系统不要求为每个岗位复制一份物理文档

### Requirement: Private knowledge isolation

系统 MUST 将用户私有文档分块与当前用户和文档标识绑定；任何私有检索都 MUST 在数据查询层限制当前用户标识，不能仅依赖提示词完成隔离。

#### Scenario: Search own private documents
- **WHEN** 已登录用户启用个人知识库并提交主题
- **THEN** 系统只返回该用户有权访问的私有文档分块，并携带文档名称、分块位置和来源信息

#### Scenario: Prevent cross-user access
- **WHEN** 请求中的文档标识属于其他用户或不存在
- **THEN** 系统拒绝访问或返回空结果，不泄露文档内容、名称或元数据

### Requirement: Personal-knowledge-only mode

系统 MUST 在用户勾选“使用个人知识库”时启用仅个人知识库模式；该模式只能使用当前用户的私有知识库和基础模型，不能访问公共知识库、联网搜索或其他用户文档。

#### Scenario: Generate from personal knowledge only
- **WHEN** 用户勾选个人知识库且存在可用私有文档
- **THEN** 题目生成使用私有知识库证据和基础模型，题目来源元数据明确标记为个人知识库

#### Scenario: Private evidence is insufficient
- **WHEN** 用户勾选个人知识库但私有文档没有足够相关内容
- **THEN** 系统仍可使用基础模型生成题目，但不得调用公共知识库或 Tavily，也不得声称缺失事实来自用户文档

### Requirement: Storage compatibility boundary

系统 MUST 保持现有 MySQL 业务表和 COS 图片用途不变；知识库向量和分块内容写入向量数据库，MySQL 继续保存文档元数据、处理状态和权限关联，COS 不得被用作知识库向量存储。

#### Scenario: Process an uploaded user document
- **WHEN** 用户上传 PDF、Word 或 Markdown 文档并处理成功
- **THEN** 系统更新现有文档元数据状态和分块数量，并将对应分块向量写入用户私有知识库

