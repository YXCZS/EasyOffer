## Purpose

让用户可以从一份已处理完成的个人面试文档直接开始闯关，并确保本轮题目严格以该文档的知识片段为依据，不混入其他文档或联网内容。

## ADDED Requirements

### Requirement: 已就绪文档必须提供单文档开始闯关入口

系统 MUST 在知识库页面的每个 `ready` 文档卡片中展示“开始闯关”操作，并将该操作与当前文档 ID 绑定。`processing`、`failed` 文档不得展示可执行的开始闯关操作；失败文档继续展示重试操作。

#### Scenario: 已就绪文档显示开始闯关按钮
- **WHEN** 登录用户打开知识库页面且某文档状态为 `ready`
- **THEN** 系统 MUST 在该文档卡片中显示使用现有主题色规范的“开始闯关”按钮，并保留文档名、分片数量和删除操作

#### Scenario: 文档尚未就绪时禁止开始闯关
- **WHEN** 文档状态为 `processing` 或 `failed`
- **THEN** 系统 MUST 隐藏或禁用“开始闯关”，并显示处理中状态或失败原因，用户只能等待处理完成或重试

#### Scenario: 游客访问知识库页面
- **WHEN** 未登录用户访问知识库页面
- **THEN** 系统 MUST 保持登录提示，不得允许游客发起文档专属题目生成

### Requirement: 开始闯关必须创建单文档出题会话

系统 MUST 在用户点击某个已就绪文档的“开始闯关”后，进入现有题目生成中页面，并携带该文档 ID、文档名称和默认出题设置。生成成功后 MUST 使用现有答题页面、答题记录和报告页面。

#### Scenario: 从文档卡片进入生成中页面
- **WHEN** 用户点击文档 `document_id` 对应的“开始闯关”按钮
- **THEN** 系统 MUST 保存本轮文档 ID和文档名称，跳转到生成中页面，并展示当前文档名称作为练习主题

#### Scenario: 单文档题目生成成功
- **WHEN** 后端基于该文档返回合法的 6 道题目
- **THEN** 系统 MUST 创建正常练习会话并进入答题页面，后续答题、断点保存和报告生成行为与普通练习一致

### Requirement: 后端必须校验文档归属和可用状态

系统 MUST 要求文档专属出题请求携带 `document_id` 和专属出题标记，并校验文档属于当前登录用户且状态为 `ready`。校验失败时 MUST 不执行检索和模型出题。

#### Scenario: 请求使用其他用户的文档
- **WHEN** 当前用户提交不属于自己的 `document_id`
- **THEN** 系统 MUST 返回资源不存在或无权访问错误，且不得泄露文档名称、内容或分片信息

#### Scenario: 请求使用未就绪文档
- **WHEN** 当前用户提交状态为 `processing` 或 `failed` 的文档
- **THEN** 系统 MUST 返回可识别的文档不可用错误，并要求用户等待处理或重试

### Requirement: 专属出题必须严格限制为当前文档的 Chroma 证据

系统 MUST 优先检索当前 `document_id` 的 Chroma 分片，并将命中的分片标记为个人知识库证据后传给题目生成器。该模式 MUST 禁止 Tavily Search、Tavily Extract、其他用户文档和当前用户其他文档作为本轮题目依据；当当前文档证据不足时，系统 MUST 使用基础模型生成，不得因证据不足直接失败。

#### Scenario: 当前文档有足够相关内容
- **WHEN** 当前文档存在与练习主题相关且足以支撑 6 道题的分片
- **THEN** 系统 MUST 仅使用这些分片生成题目，并在 `evidence_meta` 中记录文档专属路由、文档 ID、`used_personal_kb=true`、`used_web=false`、`used_base_model=false`

#### Scenario: 当前文档内容不足时使用基础模型降级
- **WHEN** 当前文档没有足够相关分片支撑题目
- **THEN** 系统 MUST 使用不带外部检索内容的基础模型生成 6 道题，不得为了凑题调用联网搜索或其他知识库内容，并在 `evidence_meta` 中记录 `used_base_model=true`、`used_personal_kb=false`、`used_web=false` 及 `fallback_reason=document_content_insufficient`

#### Scenario: 单文档检索结果隔离
- **WHEN** 用户知识库中同时存在多个已就绪文档
- **THEN** 系统 MUST 确保本轮证据中所有分片的 `document_id` 都等于请求中的文档 ID

### Requirement: 专属出题失败不得破坏现有练习流程

系统 MUST 保持普通主题生成请求的向后兼容；专属出题只有在基础模型本身生成或 schema 校验失败时才返回现有生成失败页面可识别的错误信息，且不得写入半成品题目或破坏已有答题记录。

#### Scenario: 专属生成失败后重试
- **WHEN** 文档专属生成因基础模型校验失败或服务异常失败
- **THEN** 系统 MUST 停留在生成失败页面，允许用户重试或返回答题首页，并保持现有会话数据完整

#### Scenario: 普通主题生成兼容
- **WHEN** 普通答题首页提交不带 `document_id` 的请求
- **THEN** 系统 MUST 继续按现有主题、个人知识库和 Agentic RAG 路由生成题目，行为不受本功能影响
