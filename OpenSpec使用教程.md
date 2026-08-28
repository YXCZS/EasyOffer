# EasyOffer 使用 OpenSpec 扩展功能教程

这份教程只讲一件事：以后给 EasyOffer 增加功能时，如何用 OpenSpec 让 AI 先写清楚方案，再动代码。

你不需要先把整个项目重新写一遍，也不需要先给所有旧代码补文档。OpenSpec 会围绕你这次要做的功能，逐步留下需求、设计和任务记录。

## 一、先记住一个区别

OpenSpec 有两类命令，输入位置不一样：

| 命令 | 输入位置 | 示例 |
| --- | --- | --- |
| `openspec ...` | PowerShell 或终端 | `openspec init` |
| `$openspec-...` | AI 助手的聊天框 | `$openspec-propose add-wrong-answer-review` |

最容易犯的错误是：把 `$openspec-propose` 输入到 PowerShell。它应该输入在 Codex 的聊天框里。

如果初始化后，OpenSpec 给你的命令形式是 `/opsx:propose`，就以它打印出来的形式为准。不同 AI 工具的写法可能不同，但意思一样。

## 二、准备环境

OpenSpec 官方要求 Node.js `20.19.0` 或更高版本。

在 PowerShell 检查：

```powershell
node -v
npm -v
```

如果 Node.js 版本低于 `20.19.0`，先升级 Node.js，再继续。

## 三、只安装一次 OpenSpec

在 PowerShell 执行：

```powershell
npm install -g @fission-ai/openspec@latest
```

检查是否安装成功：

```powershell
openspec --version
```

## 四、在 EasyOffer 中初始化

进入项目根目录：

```powershell
cd D:\code\develop\project_prepare\easyoffer
openspec init --tools codex
```

初始化时如果询问要为哪些 AI 工具安装指令，选择你正在使用的 Codex。

初始化完成后，项目中会出现类似目录：

```text
.agents/
└── skills/         # Codex 使用的 OpenSpec 技能

openspec/
├── specs/       # 已经确认的系统行为
├── changes/     # 尚未完成的功能变更
└── config.yaml  # 项目约定，可选
```

当前 OpenSpec 版本会在 `.agents/skills/` 下生成 `openspec-propose`、
`openspec-apply-change` 等技能。Codex 重新加载项目后即可识别它们。

不要重复执行 `openspec init`。以后升级 OpenSpec 或刷新 AI 指令时使用：

```powershell
openspec update
```

## 五、第一次扩展功能：照这个例子做

下面以“增加错题复习入口”为例。你也可以替换成自己的真实需求。

### 第 1 步：可选，先让 AI 看代码

在 Codex 聊天框输入：

```text
$openspec-explore
```

然后告诉 AI：

```text
我想给 EasyOffer 增加错题复习入口。
请先阅读现有的 Taro 前端、FastAPI 后端、用户历史记录和报告相关代码，
告诉我应该改哪些模块、有哪些风险，不要修改代码。
```

这一步只是调查，不会创建功能，也不会修改代码。需求还不清楚时使用它。

### 第 2 步：让 OpenSpec 写方案

在同一个聊天框输入：

```text
$openspec-propose add-wrong-answer-review
```

随后补充完整需求：

```text
为 EasyOffer 增加错题复习入口。

目标：用户可以在“我的”中进入错题复习，查看自己答错过的题目，并重新练习。

要求：
1. 保持现有“答题”和“我的”底部导航不变。
2. 登录用户可以保存错题，游客只保留当前设备数据。
3. 复习时仍然使用现有答题和报告流程。
4. 后端必须补充测试，不能破坏现有题目生成、答题和报告功能。
5. 先给出方案，确认后再写代码。
```

OpenSpec 通常会创建：

```text
openspec/changes/add-wrong-answer-review/
├── proposal.md  # 为什么做、做什么、不做什么
├── specs/       # 可验证的需求和场景
├── design.md    # 技术实现方案
└── tasks.md     # 可以逐项执行的任务清单
```

### 第 3 步：人工检查方案

打开这些文件，重点看 5 件事：

1. 有没有误改现有核心流程。
2. 有没有把游客和登录用户的行为写清楚。
3. 有没有写失败场景和边界情况。
4. 有没有后端测试和前端验证任务。
5. 有没有偷偷扩大范围，例如把“错题复习”变成整个学习系统重构。

如果不满意，直接在聊天框说：

```text
方案需要修改：错题复习先只支持登录用户，游客功能暂不增加；不要修改底部导航；请同步更新 proposal、specs、design 和 tasks。
```

也可以使用：

```text
$openspec-update-change add-wrong-answer-review
```

注意：更新方案不会自动修改业务代码。

### 第 4 步：让 AI 按任务实现

确认方案后，在聊天框输入：

```text
$openspec-apply-change
```

AI 会按照 `tasks.md` 逐项实现，并勾选已经完成的任务。

实现过程中，如果发现方案不对，先暂停并修改方案，不要让 AI 一边猜一边继续写大量代码。

## 六、实现完成后必须验证

先让 AI 执行项目测试：

```text
请先执行后端 pytest、前端 typecheck 和微信小程序构建。
如果有失败，修复后重新执行，不要直接标记完成。
```

你也可以在 PowerShell 手动执行：

```powershell
cd D:\code\develop\project_prepare\easyoffer\backend
pytest -q

cd ..\frontend
npm run typecheck
npm run build:weapp
```

然后在微信开发者工具中导入：

```text
D:\code\develop\project_prepare\easyoffer\frontend\dist
```

至少手动走一遍：

```text
登录 -> 进入功能 -> 完成操作 -> 查看结果 -> 返回答题 -> 再生成一轮题目
```

## 七、检查和归档

在 PowerShell 中查看当前变更：

```powershell
openspec list
openspec show add-wrong-answer-review
openspec validate add-wrong-answer-review
```

确认代码、测试和微信工具验证都通过后，先把已经确认的规格同步回主规格目录：

```text
$openspec-sync-specs
```

然后在 AI 聊天框输入归档命令：

```text
$openspec-archive-change
```

归档会做两件事：

1. 把本次变更的需求合并到 `openspec/specs/`。
2. 把已完成的变更移动到 `openspec/changes/archive/`。

最后提交 Git：

```powershell
git add openspec
git commit -m "docs: add OpenSpec change record for wrong-answer review"
```

## 八、以后每次加功能只需要记这 6 步

```text
1. PowerShell：进入项目目录
2. AI 聊天框：$openspec-explore              （不确定时使用）
3. AI 聊天框：$openspec-propose 功能名
4. 人工检查 proposal、specs、design、tasks
5. AI 聊天框：$openspec-apply-change
6. 测试通过后：$openspec-sync-specs
7. 最后归档：$openspec-archive-change
```

## 九、EasyOffer 的需求模板

以后你可以把下面这段复制给 AI，再替换内容：

```text
我想给 EasyOffer 增加：<功能名称>

用户目标：<用户最终想完成什么>
入口页面：<从哪个页面进入>
核心流程：<用户点击什么，系统发生什么>
登录要求：<游客能不能使用，登录用户有什么不同>
失败情况：<网络失败、空数据、权限失败如何处理>
保持不变：不能影响现有的 AI 生成题目、答题、报告和底部导航。
技术要求：前端使用 Taro，后端使用 FastAPI，后端必须补充 pytest 测试。

请先使用 OpenSpec 生成 proposal、specs、design 和 tasks，不要直接修改代码。
```

## 十、最常见的 4 个问题

### 1. 在 PowerShell 输入 `$openspec-propose` 没反应

这是正常的。它是 AI 聊天命令，不是终端命令。终端只执行 `openspec init`、`openspec list` 这类命令。

### 2. AI 聊天框没有 OpenSpec 命令

在项目根目录执行：

```powershell
openspec update
```

然后重启 AI 助手。如果仍然没有出现，使用初始化时打印的命令形式。

### 3. 需要先给整个项目写完 specs 吗？

不需要。EasyOffer 是已经存在的项目，每次只为当前要修改的功能写增量规格即可。

### 4. 什么时候不能直接 `$openspec-apply-change`？

以下情况先不要执行：

- 需求还没说清楚。
- 方案没有人工检查。
- 任务范围明显扩大。
- 没有明确测试方式。
- 当前工作区有未确认的用户改动。

## 一句话记忆

```text
先让 OpenSpec 把“做什么、为什么做、怎么做、怎么验”写清楚，再让 AI 写代码。
```

官方仓库：<https://github.com/Fission-AI/OpenSpec/>
