## Purpose

为技术面试题的文字解析提供按需生成、可持久访问且不阻塞答题的视觉辅助，帮助用户理解流程、关系和抽象概念，同时保证图片异常不会破坏核心答题体验。

## ADDED Requirements

### Requirement: AI SHALL decide whether an explanation needs an image

题目生成结果 MUST 在文字解析之外包含可选的可视化决策。适合精确表达技术流程、关系或状态的内容可以请求配图；不适合视觉表达的内容 MUST 返回未启用状态。决策必须包含简短的替代文本，图片提示词不得要求生成未经题目证据支持的事实。

#### Scenario: Explanation is suitable for visualization

- **WHEN** the generated explanation describes a multi-step algorithm, service interaction, data relationship, or state transition
- **THEN** the question includes an enabled visualization request with a supported type, image prompt, and alt text

#### Scenario: Explanation is not suitable for visualization

- **WHEN** the explanation is a definition, parameter list, simple comparison, or otherwise gains no meaningful clarity from an image
- **THEN** the question marks visualization as disabled and the frontend relies on the existing text explanation

### Requirement: Text question content SHALL be available before image completion

题目的题干、选项、答案和文字解析 MUST 在通过题目质量校验后立即写入生成任务。图片生成和上传 MUST NOT 阻塞首题返回、增量轮询、用户答题、评分或报告生成。

#### Scenario: Incremental question becomes available

- **WHEN** a generated question has valid text content and an enabled visualization is pending
- **THEN** the question is returned to the frontend with visualization status `pending`, and the user can start answering it

#### Scenario: One-shot question becomes available

- **WHEN** a complete quiz is generated with one or more pending visualizations
- **THEN** the quiz response remains usable for answering and does not wait for all images to finish

### Requirement: User SHALL control whether a quiz generates images

闯关设置 MUST 提供“生成图片”开关，并将选择透传到题目生成请求。开关关闭时系统 MUST 不调用百炼图片模型、不创建图片任务，题目流程保持纯文字；开关默认关闭以避免意外费用。

#### Scenario: User enables image generation

- **WHEN** the user turns on “生成图片” and starts a quiz
- **THEN** each eligible question may create an asynchronous image asset task subject to configured limits

#### Scenario: User leaves image generation disabled

- **WHEN** the user starts a quiz with the switch off
- **THEN** no image provider or COS upload is called and the quiz remains text-only

### Requirement: Image assets SHALL be generated and persisted asynchronously

对启用的图片请求，系统 MUST 调用配置的国产图片模型生成图片，并兼容临时 URL 或 base64 响应。系统 MUST 下载或解码图片、校验类型和大小、上传腾讯云 COS，并保存稳定的资源标识及对象路径；数据库 MUST 保存任务状态，不得保存图片二进制内容。

#### Scenario: Image generation and COS upload succeed

- **WHEN** the image provider returns a valid image and COS accepts the upload
- **THEN** the visualization status becomes `ready`, a stable asset identifier and COS object reference are persisted, and the frontend receives an accessible image URL

#### Scenario: Public COS access is used

- **WHEN** the configured bucket and public base URL allow public reads
- **THEN** the backend persists and returns a stable public image URL without exposing COS credentials

### Requirement: Visual asset processing SHALL be safe, bounded, and idempotent

系统 MUST 限制图片提示词、响应体、图片文件大小、生成超时、并发数和每轮图片数量；同一题目和相同提示词版本 MUST 不重复扣费。图片任务失败最多按配置有限重试，并记录可诊断的错误类型而不是把临时供应商链接持久化为最终资源。

#### Scenario: Provider or upload failure

- **WHEN** image generation, temporary URL download, decoding, validation, or COS upload fails after allowed retries
- **THEN** the asset status becomes `failed`, a bounded error message is logged, and the question remains answerable with text only

#### Scenario: Duplicate task delivery

- **WHEN** the same question and prompt hash are submitted again while an equivalent asset is pending or ready
- **THEN** the system reuses the existing asset task or result and does not issue a second image generation request

#### Scenario: Malicious or oversized response

- **WHEN** the provider response has an unsupported type, exceeds the configured size, or contains unusable data
- **THEN** the system rejects the asset, records `failed`, and does not expose or persist the invalid content

### Requirement: Frontend SHALL render visual state without changing the core flow

答题提交后的解析区域 MUST 在 `ready` 时展示图片和替代文本，在 `pending` 时展示轻量状态提示，在 `failed` 或图片加载失败时隐藏图片并保留完整文字解析。图片展示 MUST 使用适合微信小程序的远程图片组件和等比适配，不得要求前端运行 Mermaid 或访问云存储密钥。

#### Scenario: Ready image is displayed

- **WHEN** the answer feedback contains a ready visual asset with a valid image URL
- **THEN** the frontend displays the text explanation and the image with its alt text without overlapping the answer controls

#### Scenario: Image is still processing

- **WHEN** the user opens feedback before the background asset task completes
- **THEN** the frontend shows the text explanation and a non-blocking “配图生成中” state

#### Scenario: Image loading fails

- **WHEN** the remote image cannot be loaded by the mini-program
- **THEN** the frontend removes or replaces the image area and keeps the text explanation and next-question action usable

### Requirement: Existing quiz data SHALL remain backward compatible

历史题目、任务快照和报告中缺少可视化字段时 MUST 按未启用处理。新增图片资源状态不得改变现有题目去重、答题进度保存、评分、报告生成、底部导航和用户系统行为。

#### Scenario: Existing question is opened

- **WHEN** a stored question has no visualization field
- **THEN** the frontend renders the existing text-only explanation without a migration error

#### Scenario: Asset processing service is unavailable

- **WHEN** the image model or COS configuration is missing or disabled
- **THEN** text question generation continues normally and visualizations are marked unavailable without failing the quiz

### Requirement: History detail SHALL show persisted explanation images

历史记录详情 MUST 在题目包含 ready 图片 URL 时展示题目文字解析和配图；没有图片、图片仍 pending 或图片失败时 MUST 继续展示文字解析，不得影响历史记录加载。

#### Scenario: User reviews a historical quiz with images

- **WHEN** the user opens a completed quiz whose question has a ready public image URL
- **THEN** the history detail view displays that image alongside the corresponding explanation

#### Scenario: Historical quiz has no usable image

- **WHEN** a historical question lacks a visualization field or its image failed
- **THEN** the history detail view remains text-only and loads without an error
