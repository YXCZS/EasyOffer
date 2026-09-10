# incremental-quiz-generation Specification

## Purpose
让用户在题目生成过程中尽快拿到第一道可答题目，并在答题期间安全地接收后续题目，同时保证完整题组、答题进度和报告流程仍然可靠。

## Requirements

### Requirement: Create an incremental generation task

系统 SHALL 提供一个异步题目生成任务入口，接受现有题目生成所需的主题、岗位方向、难度、题目数量以及可选知识库文档上下文，并返回不可预测的任务 ID、总题数和初始状态。任务入口 MUST 复用现有的程序员面试主题校验、知识库文档归属/就绪状态校验和错误语义。

#### Scenario: Create task successfully

- **WHEN** 用户提交合法的程序员面试主题，且知识库文档参数（如果提供）属于当前用户并处于 ready 状态
- **THEN** 系统创建一个状态为 queued 或 generating 的任务，返回任务 ID、总题数、已生成题数 0 和可供轮询的状态信息

#### Scenario: Reject invalid task input

- **WHEN** 用户提交不属于程序员面试范围的主题、无权访问的文档或未就绪文档
- **THEN** 系统返回现有可识别的业务错误，不启动大模型生成，不创建可继续答题的半成品任务

### Requirement: Generate and publish questions incrementally

系统 SHALL 按题目顺序逐题生成并校验题目；每道题通过现有题目结构、选项、答案、解释和唯一性校验后，必须以原子方式写入任务状态并递增已生成题数。任务 MUST 在生成第一道题后立即暴露该题，而不等待其余题目完成；全部题目生成并校验通过后，任务状态才可变为 completed。

#### Scenario: First question becomes available

- **WHEN** 后台任务成功生成并校验第一道题
- **THEN** 状态查询返回 generated_count=1 和包含第一道题的有序题目列表，客户端可以进入答题页

#### Scenario: Later questions arrive while answering

- **WHEN** 用户已经开始回答第一道题，后台继续成功生成后续题目
- **THEN** 后续状态查询返回递增的 generated_count 和不重复的有序题目列表，客户端将新题追加到当前答题会话

#### Scenario: Question generation fails after partial progress

- **WHEN** 某一道题经过限定次数重试仍生成失败，且之前已经有题目生成成功
- **THEN** 任务状态变为 failed，保留已生成题目、generated_count 和可重试错误信息，不删除已生成内容，也不允许客户端将不完整题组当作完整题组生成报告

### Requirement: Query an atomic task snapshot

系统 SHALL 提供任务状态查询接口，返回任务状态、generated_count、total_count、当前任务版本、已生成题目、完整题组元数据和错误信息。每次响应 MUST 是同一版本的原子快照；题目列表不得包含未通过校验或重复题目。

#### Scenario: Poll before a new question is ready

- **WHEN** 客户端在两次生成之间轮询任务
- **THEN** 系统返回稳定的任务版本和当前题目列表，不重复追加题目，不改变任务状态

#### Scenario: Poll after task completion

- **WHEN** 六道题全部生成并校验成功
- **THEN** 系统返回 completed、generated_count=total_count 和完整题组；完整题组可以进入现有答题进度及报告流程

#### Scenario: Poll an expired or unknown task

- **WHEN** 客户端查询不存在、无权访问或超过保留期限的任务
- **THEN** 系统返回现有资源不存在/无权访问语义，不泄露其他用户的主题、题目或答案内容

### Requirement: Continue answering while generation is in progress

客户端 SHALL 在收到第一道题后进入答题页面；当用户答完当前题但下一题尚未生成时，页面 MUST 展示等待状态并继续轮询，不能跳转到不存在的题目或错误地结束本轮练习。答题记录 MUST 在任务未完成时仍可保存，并在任务完成后与完整题组关联。

#### Scenario: Next question is temporarily unavailable

- **WHEN** 用户提交当前题答案，且下一道题尚未生成
- **THEN** 页面显示“正在准备下一题”状态，保留用户答案并在新题可用后允许继续答题

#### Scenario: User leaves and resumes an in-progress task

- **WHEN** 用户离开答题页后重新进入应用，且任务仍未完成或已有部分答题记录
- **THEN** 客户端可以使用保存的任务 ID 恢复任务快照、已生成题目、当前索引和答案，不重新创建重复题组

### Requirement: Preserve compatibility with the existing generation flow

系统 MUST 保留现有一次性题目生成接口的请求和响应兼容性；未使用增量任务入口的客户端仍然获得完整题组后再进入答题页。增量任务完成后生成的完整 Quiz MUST 继续兼容现有 quiz_sessions、答题进度、报告、历史记录和 XP 结算流程。

#### Scenario: Legacy client generates a quiz

- **WHEN** 客户端调用现有 `/quiz/generate` 接口
- **THEN** 系统继续同步返回完整六道题，行为不因增量任务功能而改变

#### Scenario: Incremental task is finalized

- **WHEN** 增量任务完成且完整题组通过最终校验
- **THEN** 系统只创建一次完整题目会话和答题进度记录，后续报告和历史查询使用现有接口即可工作
