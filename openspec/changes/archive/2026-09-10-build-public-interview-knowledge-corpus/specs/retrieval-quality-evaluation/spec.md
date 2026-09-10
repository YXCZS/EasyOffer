## Purpose

为公共技术面试知识库提供可重复的离线检索评估和发布门禁，以真实面试查询验证相关性、覆盖度、完整性、岗位隔离、可追溯性和性能，避免仅凭成功写入向量数据库判断知识库可用。

## ADDED Requirements

### Requirement: Versioned retrieval benchmark set

系统 MUST 维护版本化的中文技术面试查询基准，每条查询至少包含主题、岗位、难度、期望技术标签、期望来源或知识单元以及人工相关性标签；首批基准 MUST 覆盖 Redis、MySQL 和 RAG/Milvus 试点资料。

#### Scenario: Add a representative benchmark query
- **WHEN** 评审者新增“Redis RDB 和 AOF 的区别”查询
- **THEN** 基准记录包含适用岗位、目标知识点、至少一个相关知识单元和可用于评分的期望结果

#### Scenario: Preserve benchmark history
- **WHEN** 查询集或人工标签发生变化
- **THEN** 系统生成新的基准版本并保留旧版本，使不同知识库版本的结果可以复现和比较

### Requirement: Automated retrieval metrics

系统 MUST 对候选公共知识库版本计算 Top-K 命中率、MRR、NDCG、知识点覆盖率、重复结果率、岗位污染率、来源可追溯率和检索延迟，并输出逐查询结果及汇总指标。

#### Scenario: Evaluate a candidate corpus version
- **WHEN** 管理员针对候选知识库版本运行基准评估
- **THEN** 系统使用固定 Embedding、过滤条件和 Top-K 参数执行全部查询，输出命中文档、分数、排名、元数据、耗时和汇总指标

#### Scenario: Detect role contamination
- **WHEN** 前端岗位查询的 Top-K 结果主要来自无关技术或错误岗位标签
- **THEN** 系统将该查询计入岗位污染，并在报告中列出污染来源和分块标识

### Requirement: Parent-context and answer integrity evaluation

系统 MUST 验证检索结果能保持完整面试问答语义；命中子分块时，评估过程 MUST 检查其父知识单元能否被精确恢复，并检查题目生成所需的答案或解释是否存在。

#### Scenario: Validate an oversized Q&A retrieval
- **WHEN** 基准查询命中一个被拆分为多个子块的长答案
- **THEN** 评估确认命中块可恢复正确父知识单元，且恢复内容包含对应问题、核心答案和来源信息

#### Scenario: Flag an answerless hit
- **WHEN** Top-K 结果只包含问题标题或零散定义而缺少可支持出题的答案信息
- **THEN** 系统将该结果标记为证据不完整并降低该查询的完整性评分

### Requirement: Publication quality gate

系统 MUST 使用可配置但版本受控的最低指标作为公共知识库发布门禁；候选版本任一强制指标未达标时不得切换为默认发布版本，除非有记录原因的人工豁免。

#### Scenario: Pass the publication gate
- **WHEN** 候选版本达到所有强制检索指标且人工抽检通过
- **THEN** 系统允许进入发布步骤，并将基准版本、参数、指标和批准人记录到发布报告

#### Scenario: Fail the publication gate
- **WHEN** 候选版本的相关性、岗位隔离、来源可追溯率或完整性低于阈值
- **THEN** 系统阻止默认版本切换，保留当前已发布版本并列出需要修复的查询和分块

### Requirement: Regression comparison

系统 MUST 能够在相同查询集和参数下比较当前已发布版本与候选版本，识别提升、退化、结果漂移和延迟变化；新增资料不得以明显降低已有领域质量为代价。

#### Scenario: Compare candidate and current versions
- **WHEN** 新增 Java 或 AI 资料后运行回归评估
- **THEN** 报告同时展示候选与当前版本的指标差异，并列出排名显著下降、来源变化或新增污染的查询

#### Scenario: Keep production retrieval unchanged after failure
- **WHEN** 候选版本未通过回归门禁
- **THEN** 现有已发布版本继续服务，Agentic RAG 的公共检索行为不切换到候选版本

### Requirement: Human relevance sampling

系统 MUST 对自动评估结果执行人工抽样，使用统一等级判断技术相关性、答案正确性、面试价值、版本适用性和来源质量；抽检记录 MUST 能定位到具体查询和分块。

#### Scenario: Review pilot retrieval results
- **WHEN** Redis、MySQL 和 RAG/Milvus 试点数据完成自动评估
- **THEN** 评审者抽检高分、低分、边界和冲突样本，记录分级与问题类型，系统将结果纳入最终发布判断

