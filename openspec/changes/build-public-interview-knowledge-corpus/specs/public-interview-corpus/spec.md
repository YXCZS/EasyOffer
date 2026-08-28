## Purpose

建立可重复、可审核、可追溯的公共技术面试知识库内容生命周期，使原始资料经过结构化解析、面试语义切分、质量控制和版本发布后，能够稳定为题目生成提供可信证据。

## ADDED Requirements

### Requirement: Public source manifest and batch intake

系统 MUST 使用显式资料清单批量接收公共知识源，并记录每份资料的唯一标识、文件位置或来源地址、技术方向、岗位标签、版本、语言、内容类型、许可状态和目标发布版本；未出现在清单中的文件不得被自动发布。

#### Scenario: Preview a declared source batch
- **WHEN** 管理员对一批已登记的 PDF、DOCX 或 Markdown 资料执行预览导入
- **THEN** 系统输出每份资料的解析状态、页数或正文长度、候选知识单元数、分块数、重复数和失败原因，但不写入可检索的已发布数据

#### Scenario: Block an undeclared or unlicensed source
- **WHEN** 资料未登记来源、许可状态未确认或标记为仅本地评估
- **THEN** 系统不得将其发布到正式公共知识库，并在处理结果中记录阻止原因

### Requirement: Structure-aware interview content extraction

系统 MUST 优先按照面试问题、答案、解析、章节、标题、列表和代码块等语义边界形成知识单元，不得把固定字符长度作为唯一切分依据；解析过程不得改写原始技术结论。

#### Scenario: Preserve a complete interview question and answer
- **WHEN** 原始资料中存在可识别的问题、答案和解析结构，且整体长度在配置上限内
- **THEN** 系统将其保存为一个完整父知识单元，并保留问题、答案、解析、章节路径和原始页码

#### Scenario: Split an oversized knowledge unit
- **WHEN** 一个完整问题或章节超过单个检索分块的配置上限
- **THEN** 系统按段落、列表、代码块和句子边界生成多个子分块，保留受限重叠，并让所有子分块引用同一个父知识单元

#### Scenario: Fall back for weakly structured text
- **WHEN** 资料无法可靠识别问题或章节结构
- **THEN** 系统使用递归文本边界切分作为兜底，同时保存字符起始位置、页码范围和低结构置信度标记

### Requirement: Searchable metadata and hierarchy

系统 MUST 为每个可检索分块保存文档标识、文档版本、父知识单元标识、子分块序号、技术方向、岗位标签、内容类型、章节路径、来源、页码、语言、内容哈希、审核状态和发布时间；检索结果 MUST 能追溯到原始资料位置。

#### Scenario: Retrieve a role-scoped chunk
- **WHEN** 公共检索以 Java 后端岗位查询 Redis 持久化主题
- **THEN** 返回分块包含匹配岗位与技术标签、父知识单元标识、来源名称和原始位置，且仅来自当前已发布版本

#### Scenario: Expand a child hit to its parent context
- **WHEN** 相似度检索命中一个超长知识单元的子分块
- **THEN** 系统能够通过父知识单元标识取得必要的同源上下文，不得使用文件名相似度搜索代替精确父子查询

### Requirement: Deterministic deduplication and idempotency

系统 MUST 在文档级和分块级执行规范化哈希去重，并为文档版本、父知识单元和子分块生成稳定标识；同一批次重复执行不得产生重复的可检索内容。

#### Scenario: Re-run the same import
- **WHEN** 管理员使用相同清单和相同文件重复执行摄取
- **THEN** 系统识别内容未变化，复用稳定标识并报告零新增重复分块

#### Scenario: Detect cross-document duplicate content
- **WHEN** 不同文件包含相同转载段落或同一题解的轻微格式变体
- **THEN** 系统将其标记为重复候选，只保留指定权威来源或人工确认的主记录参与发布

### Requirement: Quality review and publication gate

系统 MUST 在发布前检查正文完整性、结构置信度、答案缺失、异常乱码、重复比例、来源信息、岗位标签、版本冲突和许可状态；只有通过自动检查并获得人工批准的版本才能成为公共检索证据。

#### Scenario: Approve a qualified document version
- **WHEN** 一个文档版本通过自动质量检查且人工审核确认来源、标签和内容可用
- **THEN** 系统将该版本标记为已发布，公共检索仅返回该版本中状态为已发布的分块

#### Scenario: Reject a low-quality document
- **WHEN** 文档存在大面积乱码、关键答案缺失、重复比例超限或标签无法确认
- **THEN** 系统将该版本保持为未发布或失败状态，保存具体问题并允许修正后重新处理

### Requirement: Versioned replace and withdrawal

系统 MUST 支持以文档版本为单位发布、替换和撤回内容；新版本写入和验证完成前，旧版本保持可用，新版本发布后旧版本不得继续出现在默认公共检索中。

#### Scenario: Replace a published document version
- **WHEN** 管理员发布同一资料的新版本
- **THEN** 系统先完成新版本写入和验证，再切换默认发布版本，并将旧版本标记为非活动状态，避免新旧分块混合返回

#### Scenario: Withdraw problematic content
- **WHEN** 已发布资料出现版权、错误或过时问题并被撤回
- **THEN** 系统立即从默认公共检索中过滤该版本，同时保留审计元数据和撤回原因

### Requirement: Auditable processing output

系统 MUST 为每次批量处理生成不包含密钥和完整敏感正文的结果报告，至少包含输入清单版本、成功与失败文档、分块统计、重复统计、质量问题、发布动作和耗时。

#### Scenario: Complete a batch with partial failures
- **WHEN** 一批资料中部分文件解析失败而其他文件处理成功
- **THEN** 系统分别记录每个文件的结果，不因单个文件失败丢失整批统计，也不得自动发布失败文件的任何分块

