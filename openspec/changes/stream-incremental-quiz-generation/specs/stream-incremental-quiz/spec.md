## Purpose

让用户在第一道面试题生成后立即开始答题，同时让后端在用户答题期间持续生成并提供后续题目，缩短首屏等待并保持题目顺序、答题进度和失败恢复的一致性。

## ADDED Requirements

### Requirement: Generation task creation SHALL be asynchronous

用户点击生成后，服务 SHALL 先创建并持久化任务，立即返回任务 ID 和可表示运行中的状态；联网检索、主题判断和模型出题 SHALL 在后台执行，不得阻塞创建请求直到整套题生成完成。

#### Scenario: Task is created immediately
- **WHEN** 用户提交有效的主题、岗位和难度
- **THEN** 服务 SHALL 在短时间内返回任务 ID 与 `queued` 或 `generating` 状态，客户端无需等待搜索或模型生成结果

#### Scenario: Background task starts after creation
- **WHEN** 创建接口已经返回任务 ID
- **THEN** 后端 SHALL 在后台执行资料准备和逐题生成，并通过任务快照更新运行状态

### Requirement: Generation SHALL expose questions incrementally

生成任务 SHALL 按题目顺序逐题生成；每道题完成必要校验并持久化后，任务快照 SHALL 立即包含该题和最新的 `generated_count`，不得等待整套题全部生成后才返回题目。

#### Scenario: First question becomes available early
- **WHEN** 生成任务已完成主题判断和资料准备，并成功生成第 1 道题
- **THEN** 任务快照 SHALL 返回 `generated_count=1` 和第 1 道题，即使第 2 至第 6 道题尚未生成

#### Scenario: Later questions are produced in order
- **WHEN** 后台继续生成后续题目
- **THEN** 每次任务快照中的题目列表 SHALL 保持生成顺序，新增题目 SHALL 追加在已有题目之后

### Requirement: The client SHALL start answering after the first question

客户端 SHALL 在首次获取到至少一道有效题目后进入答题页面，不得等待 `generated_count` 达到总题数；后续题目未就绪时 SHALL 保留已生成题目和用户答题记录。

#### Scenario: User answers while generation continues
- **WHEN** 用户已进入答题页且下一道题尚未生成
- **THEN** 页面 SHALL 显示可恢复的等待状态，并继续获取任务进度；不得显示空白页、清空题组或将任务误判为最终失败

#### Scenario: A new question arrives during answering
- **WHEN** 后端生成了下一道题
- **THEN** 客户端 SHALL 将新题合并到当前题组，用户完成当前题后可以继续作答

### Requirement: Question generation SHALL remain independently recoverable

单道题生成失败、模型返回非法结构或重复内容时，系统 SHALL 只重试当前题，不得删除已经持久化的题目和答题记录；重试耗尽后 SHALL 使用当前主题的有效降级题或将任务标记为可重试失败。

#### Scenario: Invalid response is retried
- **WHEN** 模型返回格式错误、字段缺失或与已生成题目重复的内容
- **THEN** 系统 SHALL 记录失败原因并重新请求当前题，且 `generated_count` 不得提前增加

#### Scenario: Partial task fails
- **WHEN** 当前题多次生成失败但之前已经生成了至少一道题
- **THEN** 任务快照 SHALL 保留已有题目和答题记录，并提供可重试状态；客户端 SHALL 允许继续生成，不得丢失已有内容

### Requirement: Polling snapshots SHALL be consistent

客户端 SHALL 以约 6 秒的间隔获取任务快照，网络异常或后端响应慢时 SHALL 退避至约 8 秒；客户端 SHALL 处理请求乱序和重复请求，较旧版本的快照不得覆盖较新题目、当前题号或答题记录。任务达到终态后 SHALL 停止轮询。

#### Scenario: Older response arrives late
- **WHEN** 一个较旧的快照在较新快照之后返回
- **THEN** 客户端 SHALL 忽略会导致题目数量、任务版本或当前进度回退的字段

#### Scenario: Generation completes
- **WHEN** 六道题均已生成并完成正式题组落库
- **THEN** 任务 SHALL 返回 `completed` 和完整题组，客户端 SHALL 停止增量轮询并继续正常答题或进入报告流程

#### Scenario: Task is still running
- **WHEN** 后端尚未生成新题目
- **THEN** 客户端 SHALL 按约 6 秒间隔继续查询；发生网络错误或后端响应超时后 SHALL 使用约 8 秒间隔重试

### Requirement: Answer progress SHALL survive incremental generation

用户在增量生成期间提交的答案、当前题号和退出行为 SHALL 被保存；生成任务进度保存发生版本冲突时，客户端 SHALL 获取最新快照、合并本地答案并重试一次。

#### Scenario: User leaves during generation
- **WHEN** 用户在后续题目生成完成前离开答题页
- **THEN** 系统 SHALL 保存已答题记录和当前题号，用户下次进入未完成练习时 SHALL 能继续答题

#### Scenario: Progress version conflict
- **WHEN** 进度保存请求携带的版本已过期
- **THEN** 服务 SHALL 返回冲突，客户端 SHALL 刷新最新版本并重试，不能静默丢弃用户答案
