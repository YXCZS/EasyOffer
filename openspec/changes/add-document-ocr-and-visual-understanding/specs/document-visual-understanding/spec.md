## Purpose

让复杂版面、图片表格、图表、流程图和 Word 内嵌图片得到可验证的视觉语义描述，并以带页码和来源的文本证据参与现有知识库检索。

## ADDED Requirements

### Requirement: 视觉内容必须按类型和价值分流

系统 SHALL 根据 MinerU 节点类型、图注、OCR 文本和版面信息选择 OCR 或视觉模型，不得对所有装饰图片、Logo 或头像调用视觉模型。

#### Scenario: Word 内嵌文字图片
- **WHEN** Word 图片主要包含截图、票据或扫描文字
- **THEN** 系统独立抽取该图片并执行 OCR，结果继承所属段落、章节和媒体来源

#### Scenario: 图表或流程图
- **WHEN** 节点被识别为 chart、flowchart 或高价值技术图片
- **THEN** 系统向视觉模型提供图片、OCR 文本、章节上下文和可用坐标

#### Scenario: 装饰图片
- **WHEN** 图片没有技术图注、有效文字或结构信息
- **THEN** 系统跳过视觉模型，仅保存媒体路径和来源元数据

### Requirement: 复杂图片表格必须组合 OCR、坐标和 VLM

对于扫描表格、表格截图、多级表头、合并单元格、无边框表格或 MinerU 行列异常的内容，系统 SHALL 先获取 OCR 文本，再结合 bbox、图片和章节上下文调用视觉模型恢复表格语义。

#### Scenario: 复杂表格增强
- **WHEN** 表格结构复杂或基础 OCR 行列关系不可靠
- **THEN** 系统请求视觉模型输出表头、行、合并关系、备注和不确定性

#### Scenario: 表格增强校验通过
- **WHEN** 视觉结果与 OCR 文本、坐标和页码能够一致校验
- **THEN** 系统创建带来源的 table Parent，并将规范化表格文本用于 Embedding

#### Scenario: 表格增强校验失败
- **WHEN** 视觉结果与 OCR 或坐标冲突
- **THEN** 系统不覆盖原始结果，保留 MinerU/OCR 内容并标记 degraded

### Requirement: 视觉分析必须输出结构化、可追溯结果

系统 SHALL 保存 visual_type、title、summary、elements、relations、uncertainties、confidence、model_version、page、bbox 和 media_path，并将可信摘要和关系转成文本证据。

#### Scenario: 流程图分析成功
- **WHEN** 视觉模型返回合法结构化结果
- **THEN** 系统创建 image/chart Parent 和 Child，文本包含章节、标题、摘要和节点关系，并可回溯原图

#### Scenario: 视觉模型返回非法结果
- **WHEN** 响应不是合法 JSON 或缺少必要字段
- **THEN** 系统丢弃不可信结论，保留 OCR/图注并记录 visual_analysis_invalid

### Requirement: 视觉增强必须隔离失败

视觉模型超时、限流或不可用时，系统 SHALL 继续完成可用文本的知识库构建，不得写入未经验证的视觉事实。

#### Scenario: 单图超时
- **WHEN** 单个图片分析超过配置超时时间
- **THEN** 系统标记 visual_analysis_failed，继续处理其他节点和正文

#### Scenario: 多图并发
- **WHEN** 文档包含多个待分析图片
- **THEN** 系统使用有界并发、有限重试和调用预算，超出预算后停止新增调用并记录原因

### Requirement: 视觉证据必须继承权限和版本

视觉 Parent/Child SHALL 继承源文档的 owner、document、corpus、version、license 和发布状态，并遵循现有 Milvus 过滤条件。

#### Scenario: 公共旧版本
- **WHEN** 源文档版本为 inactive
- **THEN** 其视觉证据不得出现在 published-only 检索结果中
