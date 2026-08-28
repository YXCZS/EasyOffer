## Purpose

定义 EasyOffer 单选、多选和判断题从题组生成、用户作答到进度恢复与报告回看的统一行为，确保每轮练习包含稳定的题型组合且所有答案均可判定。

## ADDED Requirements

### Requirement: Six-question quiz type composition
系统 SHALL 为每组 6 道题生成 4 道单选题、1 道多选题和 1 道判断题，并 SHALL 在题组交付前校验实际题型数量。

#### Scenario: Complete generated quiz satisfies the type quota
- **WHEN** 一组 6 道题生成完成
- **THEN** 题组包含恰好 4 道 `single`、1 道 `multiple` 和 1 道 `judge`

#### Scenario: Incremental generation preserves the target type
- **WHEN** 后端逐题生成第 1 至第 6 题
- **THEN** 每次生成请求都包含该题的目标题型，最终题组满足固定题型组成

#### Scenario: Model returns the wrong question type
- **WHEN** 模型返回的题型与当前题号要求的目标题型不一致
- **THEN** 系统拒绝该题并按现有单题重试策略重新生成，不将错误题型写入任务快照

### Requirement: Multiple-choice answer interaction
系统 SHALL 允许用户在多选题中选择一个或多个选项，并 SHALL 使用无序答案集合的完全相等关系判定结果。

#### Scenario: Select multiple options
- **WHEN** 用户在未提交的多选题中依次点击多个未选选项
- **THEN** 所有被点击选项保持选中状态

#### Scenario: Deselect a selected option
- **WHEN** 用户再次点击多选题中的已选选项
- **THEN** 该选项取消选中，其他已选选项保持不变

#### Scenario: Submit a correct multiple-choice answer
- **WHEN** 用户提交的选项集合与标准答案集合完全一致，且仅顺序不同
- **THEN** 系统判定回答正确

#### Scenario: Submit an incomplete or excessive multiple-choice answer
- **WHEN** 用户漏选任一正确选项或额外选择任一错误选项
- **THEN** 系统判定回答错误并展示标准答案和解析

#### Scenario: Submit without an option
- **WHEN** 用户尚未选择任何多选项
- **THEN** 提交操作不可用

### Requirement: True-false question contract
判断题 SHALL 只提供“正确”和“错误”两个互斥选项，且标准答案 SHALL 恰好包含一个选项。

#### Scenario: Render a true-false question
- **WHEN** 当前题目类型为 `judge`
- **THEN** 答题页展示“正确”和“错误”两个选项，并显示“判断题”题型标签

#### Scenario: Change a true-false selection
- **WHEN** 用户在判断题中先选择一个选项后再选择另一个选项
- **THEN** 后选择的选项替换先前选择，页面最多保持一个选中项

#### Scenario: Invalid generated true-false options
- **WHEN** 模型返回的判断题不是两个语义明确的“正确/错误”选项，或返回多个标准答案
- **THEN** 系统拒绝该题并重新生成，不向用户交付不可判定题目

### Requirement: Question-type guidance
答题页 SHALL 显示当前题型；多选题 SHALL 显示明确的“可多选”提示，单选题与判断题 SHALL 保持互斥选择行为。

#### Scenario: User opens a multiple-choice question
- **WHEN** 当前题目类型为 `multiple`
- **THEN** 页面显示“多选题”和“可多选”提示

#### Scenario: User opens a single-choice question
- **WHEN** 当前题目类型为 `single`
- **THEN** 页面显示“单选题”，点击新选项时替换旧选项

### Requirement: Progress and report compatibility
系统 SHALL 使用现有答案数组格式保存三种题型，并 SHALL 在断点恢复、历史详情和报告逐题明细中还原用户答案与标准答案。

#### Scenario: Resume an unanswered multiple-choice question
- **WHEN** 用户选择多个选项后提交、保存进度并重新进入练习
- **THEN** 页面恢复该题全部已提交选项及判题结果，且不能再次修改答案

#### Scenario: Review a true-false answer in the report
- **WHEN** 用户完成包含判断题的练习并打开报告或历史详情
- **THEN** 逐题明细显示题干、用户判断、正确判断、结果和解析

#### Scenario: Read an existing single-choice practice
- **WHEN** 用户恢复本变更发布前保存的单选题练习
- **THEN** 系统按原有格式正常读取和展示，不要求数据迁移

