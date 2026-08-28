## Purpose

让未登录用户也能体验 EasyOffer 的核心“输入主题并开始答题”流程，同时严格隔离个人数据、控制匿名访问成本，并保证外部服务异常时仍能完成基础题目生成。

## ADDED Requirements

### Requirement: Guests can generate ordinary quizzes

系统 SHALL 允许未登录用户使用普通文本主题创建异步题目生成任务，并返回可查询的任务标识和初始排队状态。游客 SHALL 能够完成当前会话中的答题和报告流程。

#### Scenario: Guest creates a normal topic

- **WHEN** 未登录用户提交 2 至 2000 字符的普通技术主题且未指定个人文档
- **THEN** 系统 SHALL 创建异步任务并返回 `queued` 或 `generating` 状态，不得要求登录后才能生成题目

#### Scenario: Guest receives the first question

- **WHEN** 匿名任务生成第一道有效题目
- **THEN** 系统 SHALL 返回该题并允许游客进入答题页，剩余题目可以继续后台生成

### Requirement: Guest data access SHALL remain isolated

游客 SHALL 不得读取、创建、修改或删除个人知识库、历史练习、用户画像和其他用户数据。匿名任务的查询和进度更新 SHALL 绑定匿名会话凭证，不得仅凭可猜测的任务 ID 访问。

#### Scenario: Guest requests a personal document

- **WHEN** 未登录用户提交 `document_id` 或知识库专属答题请求
- **THEN** 系统 SHALL 拒绝请求并返回明确的登录提示，不得调用 Chroma 或公共联网工具

#### Scenario: Guest tries to access another task

- **WHEN** 游客使用不属于当前匿名会话的任务标识查询或更新进度
- **THEN** 系统 SHALL 返回未授权或不存在响应，不得泄露题目、答案或用户信息

### Requirement: Guest usage SHALL be budgeted

系统 SHALL 对游客的生成频率、并发任务数、联网搜索次数和每日用量执行服务端限制，并在超限时返回可识别的限流状态。限制不得影响已创建任务的答题和报告完成。

#### Scenario: Guest exceeds the anonymous budget

- **WHEN** 游客超过单会话、单 IP 或每日生成额度
- **THEN** 系统 SHALL 拒绝新的生成任务并返回重试时间或登录后继续的提示

### Requirement: Guest research failure SHALL degrade to the base model

联网搜索、证据过滤或 Agent 路由失败时，系统 SHALL 允许游客使用基础模型继续生成，不得返回空白题目页面或把未过滤网页内容注入题目 Prompt。

#### Scenario: Guest Tavily is unavailable

- **WHEN** 游客任务的联网工具超时、限流、无结果或未配置
- **THEN** 系统 SHALL 记录降级原因并使用基础模型生成题目，任务仍可进入答题流程
