# EasyOffer 面试答题小程序

面向程序员的碎片化技术面试学习工具。用户在通勤、休息等没有电脑的场景下，输入一个技术主题即可生成 6 道面试题，通过逐题作答、即时解析和复盘报告完成一次短时学习。

## 功能模块

### 智能题目生成

- 支持输入 2～2000 字技术主题，并按岗位方向和难度生成 6 道技术面试题。岗位范围覆盖通用基础、后端、前端、AI/大模型、数据/算法、测试/运维、移动端和安全工程。
- 每轮题组固定包含 4 道单选题、1 道多选题和 1 道判断题。题目数据包含标准答案、逐选项解释、知识点、常见误区、难度和版本前提，并在交付前完成结构与答案有效性校验。
- 采用异步任务与逐题生成机制。后端完成第一题后立即释放给前端，剩余题目在用户答题期间继续生成，避免小程序长连接超时并缩短首题等待时间。
- 生成前先进行内容安全检查、主题规范化和技术面试范围判断；非技术主题直接终止，不进入后续检索与出题流程。

### Agentic RAG 检索

- 使用 LangGraph 编排受约束的检索流程，根据主题、岗位、查询扩展结果和用户权限，在公共 Milvus 知识库、Tavily Search、Tavily Extract 与基础模型之间选择合适的数据来源。
- 查询扩展保留用户输入中的核心技术词，并生成多个互补查询以扩大召回范围；URL 输入通过 Tavily Extract 直接提取正文，避免将链接误作普通关键词搜索。
- 对多来源证据执行合并、去重、相关性评分和覆盖度评估，只将高相关内容写入出题上下文。证据不足时可在预算范围内改写查询并继续检索。
- 路由过程受工具白名单、调用次数、检索轮数、超时时间和上下文长度约束。外部检索失败时记录降级原因，并回退到基础模型，不中断题目生成主流程。

### 个人知识库

- 支持上传 PDF、DOCX 和 Markdown 文档，完成文件校验、内容解析、文本清洗、分块、Embedding 和向量入库，将用户资料转换为可检索的学习语料。
- 用户可以查看文档处理状态与上传进度，并执行重试、重命名和删除操作；向量数据按 `user_id` 和 `document_id` 隔离，防止跨用户或跨文档检索。
- 支持从指定文档直接发起练习，也支持在答题首页启用个人知识库模式。该模式只检索用户个人资料，并由基础模型结合检索证据生成题目，不调用公共知识库或联网搜索。

### 答题与学习进度

- 答题页统一支持单选、多选和判断三种题型。多选题采用答案集合完全匹配规则，判断题固定使用“正确/错误”两个互斥选项，提交后即时展示判题结果与答案解析。
- 支持上一题回看、下一题作答和已提交答案只读恢复；在后台继续生成题目时，新增题目不会打断用户当前的答题或历史回看位置。
- 答题进度同时保存题目位置、选择结果和答题记录。用户中途返回后可从首页继续未完成练习，也可以删除不再继续的练习。
- 生成任务与答题进度分别使用版本号进行乐观并发控制。发生 409 冲突时，客户端获取最新快照、合并本地答案并重新保存，避免覆盖已生成题目或丢失多选答案。

### 学习报告与可视化

- 完成练习后生成结构化复盘报告，展示得分、正确率、逐题作答结果、用户答案、标准答案、知识点解析、已掌握内容、待复习内容、总结和后续建议。
- 客观得分与逐题状态由后端确定性计算，大模型只负责知识总结和复习建议，避免模型输出影响评分结果。
- 对适合视觉表达的知识点生成题解配图，覆盖流程图、时序图、ER 图、状态图、思维导图和概念图等场景；图片上传至腾讯云 COS 后持久化展示。
- 生图与题目生成相互解耦。DashScope 或 COS 异常只会将对应图片标记为失败，不阻塞答题、报告生成和历史记录回看。

### 用户体系与内容安全

- 通过 `wx.login` 和微信 `jscode2session` 完成用户身份识别，后端按 `openid` 创建或读取用户并签发 JWT，支持昵称、头像选择、拖动缩放裁剪和资料更新。
- 记录 XP、完成题组数、答对题数、平均正确率和练习历史，用户可以在“我的”页面管理个人资料、知识库和历史学习记录。
- 游客使用 Guest Token 标识设备并限制生成额度，只允许使用基础模型出题；登录用户可以使用公共知识库、联网检索、个人知识库和跨会话进度恢复。
- 对开放式学习主题接入微信 `msgSecCheck`，在进入模型和检索链路前拦截违规文本，降低不当内容进入生成系统的风险。

## 系统架构

```text
┌──────────────────────────────────────────────────────┐
│         微信小程序（Taro 4 + React 18）               │
│  答题首页 / 生成进度 / 答题 / 报告 / 我的 / 知识库    │
└────────────────────────┬─────────────────────────────┘
                         │ HTTP + JSON
                         │ Bearer JWT / X-Guest-Token
                         ▼
┌──────────────────────────────────────────────────────┐
│                    FastAPI                           │
│  Router → Service → Repository / LLM / Research     │
└──────────────┬─────────────────┬─────────────────────┘
               │                 │
               ▼                 ▼
┌────────────────────────┐  ┌──────────────────────────┐
│ MySQL                   │  │ LangChain + LangGraph    │
│ 用户、题组、任务、进度、 │  │ DeepSeek / Tavily /      │
│ 报告、文档和图片元数据   │  │ Milvus                   │
└────────────────────────┘  └─────────────┬────────────┘
                                         │
                     ┌───────────────────┼───────────────────┐
                     ▼                   ▼                   ▼
              ┌────────────┐      ┌────────────┐      ┌────────────┐
              │ Milvus     │      │ DashScope  │      │ 腾讯云 COS │
              │ 向量数据    │      │ Embedding  │      │ 题解图片    │
              │            │      │ / 生图      │      │            │
              └────────────┘      └────────────┘      └────────────┘
```

后端采用模块化单体结构。路由层负责请求校验和鉴权，Service 层编排业务流程，Repository 层访问 MySQL，`llm`、`research`、`media` 分别封装模型、检索和图片服务。

## 核心流程

### 普通主题出题

```text
用户输入主题
  → 确定性规范化
  → 微信内容安全检查
  → DeepSeek 判断是否属于程序员技术面试
  → 查询扩展
  → LangGraph 选择公共 Milvus / Tavily Search / Tavily Extract
  → 检索结果去重、评分、过滤
  → 生成第一题并写入任务快照
  → 前端进入答题页
  → 后台逐题生成剩余题目
  → 答题完成后生成报告
```

主题范围判断位于检索之前。非技术主题直接返回业务错误，不创建生成任务，也不调用 Milvus 或 Tavily。

### 数据源路由

路由前先根据身份和请求模式生成权限策略，Agent 只能调用策略允许的工具。

| 场景 | 可用数据源 | 说明 |
| --- | --- | --- |
| 游客 | 基础模型 | 不调用公共知识库、个人知识库和 Tavily |
| 登录用户输入关键词 | 公共 Milvus、Tavily Search、Tavily Extract、基础模型 | 查询扩展后检索；证据不足时继续有限轮次 |
| 登录用户输入 URL | Tavily Extract、基础模型 | 直接抽取网页，不把 URL 当成搜索关键词 |
| 勾选个人知识库 | 个人向量库、基础模型 | 不调用公共 Milvus 和 Tavily |
| 从指定文档开始答题 | 指定个人文档、基础模型 | 使用 `document_id` 限定检索范围 |

`PolicyEnvelope` 保存允许的工具、最大调用次数、用户 ID、文档 ID 和知识库专属标记。LangGraph 状态保存当前查询、扩展查询、检索轮次、候选证据、覆盖度、冲突、工具调用和降级原因。

### Agentic RAG 检索

```text
构建权限策略
  → 生成/校验路由决策
  → 选择检索查询
  → 调用允许的检索工具
  → 合并并去重候选证据
  → 恢复公共语料父块
  → 计算相关性与覆盖度
  → 证据不足时改写查询并进入下一轮
  → 达到阈值或预算上限后结束
```

实现约束：

- 工具只能从策略白名单中选择，用户输入不能扩大权限。
- 普通知识检索同时保留用户原始技术词，查询扩展不能丢失明确主题。
- Tavily 返回内容按不可信外部数据处理，不能覆盖系统 Prompt。
- 检索有总轮数、工具调用数、单次超时和上下文长度限制。
- 检索失败或证据不足时记录 `fallback_reason`，再回退到基础模型。
- 题组通过 `evidence_meta` 保存路由、来源类型、工具调用、覆盖度和耗时。

### 增量题目生成

同步生成 6 道题会让小程序请求持续占用连接。项目使用 MySQL 任务表保存生成状态，接口创建任务后立即返回。

```text
POST /quiz/generation-tasks
  → 写入 queued 任务
  → asyncio 后台任务 claim
  → prepare_incremental：范围判断与证据准备
  → generate_incremental_question：逐题调用模型
  → 每题成功后追加 questions_json，递增 version
  → 前端轮询任务快照
  → 第一题可用后 redirectTo 答题页
  → 生成完成后保存正式 Quiz 和初始进度
```

任务状态包括 `queued`、`generating`、`completed`、`failed`、`expired`。前端使用 `setTimeout` 递延轮询：首题阶段约 2.5 秒一次，进入答题后约 6 秒一次，请求异常时按 3/6/10 秒退避。

题目追加和答题进度分别使用 `version`、`progress_version` 乐观锁。客户端收到 409 后先获取最新快照，合并本地答案，再重试保存；较旧的轮询响应不能覆盖已经生成的题目。

### 答题与报告

每道题由 Pydantic 校验：

- 选项数量为 2～4 个；
- 答案必须存在于选项；
- 单选题和判断题只能有一个答案；
- 多选题至少有两个答案；
- 每个选项必须有对应解释；
- 同一题组不能出现重复 ID 或完全相同的题干。

前端本地完成即时判题，同时保存选择项和答题时长。报告中的得分、正确率和逐题状态由 Python 代码计算，DeepSeek 只生成知识总结和复习建议，不参与修改分数。

## 知识库

### 个人知识库

支持 PDF、DOCX 和 Markdown，单个文件默认上限 20 MB。

```text
文件校验
  → SHA-256 去重
  → 保存原文件
  → 文档解析与清洗
  → 按配置切分并保留重叠窗口
  → DashScope text-embedding-v4 向量化
  → 写入个人向量集合
  → 更新文档状态和 chunk_count
```

个人向量记录包含 `user_id` 和 `document_id`。检索时同时使用 Milvus 标量过滤和应用层二次校验，避免跨用户、跨文档返回内容。文档删除时同时删除向量记录和本地文件。

项目统一使用 Milvus 作为个人与公共知识库的向量存储。公共知识库和个人知识库使用独立集合并通过元数据过滤隔离。

### 公共面试知识库

公共知识库使用独立语料流水线，不把正文存入 MySQL 或 COS。

```text
YAML 来源清单
  → 解析 PDF/Markdown
  → 清洗页眉、页脚和异常字符
  → 父子分块
  → 精确去重与近似去重
  → Embedding
  → 以 unpublished 状态写入 Milvus
  → 检索基准评估
  → 人工审核
  → 发布 corpus_version
```

项目清单包含 20 份已授权技术面试 PDF，共 904 页。处理后发布 1,283 个知识块，覆盖 Java、JVM、并发、集合、Spring、Spring Boot、Spring Cloud、MySQL、Redis、RabbitMQ、Elasticsearch、Nginx、ZooKeeper、MyBatis、操作系统、计算机网络、设计模式和 AI 大模型等主题。

公共知识块保存：

- `document_id`、`document_version`、`corpus_version`；
- 技术分类和岗位标签；
- 子块文本、`parent_id` 和父块正文；
- 来源 URL、许可状态、审核状态和发布时间；
- 稳定 chunk ID，支持重复运行和版本回滚。

检索命中子块后通过 `parent_id` 恢复完整父块，使用小块提高召回精度，使用父块提供足够的出题上下文。

公共语料命令：

```powershell
cd backend

# 只解析、切分和检查，不写 Milvus
python -m app.corpus.cli --config corpus/config.yaml --store memory preview corpus/manifests/full-authorized-v1.yaml

# 写入候选版本
python -m app.corpus.cli --config corpus/config.yaml ingest corpus/manifests/full-authorized-v1.yaml

# 检索评估与状态检查
python -m app.corpus.cli --config corpus/config.yaml evaluate corpus/benchmarks/pilot-v1.yaml full-authorized-v1
python -m app.corpus.cli --config corpus/config.yaml inspect full-authorized-v1
```

## 题目配图

配图与题目生成分开执行。模型先判断题解是否适合用流程图、时序图、ER 图、状态图、思维导图或概念图表达，再生成中文图片 Prompt。

```text
创建 quiz_visual_assets 记录
  → DashScope 生成图片
  → Pillow 校验格式、尺寸和文件大小
  → 上传腾讯云 COS
  → 保存 cos_key、image_url、宽高和 MIME 类型
  → 更新题目的 visualization 状态
```

图片任务限制并发数、每套题最大图片数、Prompt 长度、文件大小和重试次数。DashScope 或 COS 失败时只把该资源标记为 `failed`，不回滚题目，也不阻塞答题和报告。

## 用户与进度

### 登录

```text
wx.login 获取 code
  → POST /user/login
  → 后端调用微信 jscode2session
  → 按 openid 创建或读取用户
  → 签发 JWT
  → 前端保存 token 和用户资料
```

后续请求使用 `Authorization: Bearer <token>`。JWT 失效时清除本地用户状态和登录用户练习缓存。

### 游客

游客请求携带 `X-Guest-Token`。后端只保存 Token 哈希，并按日期统计总任务数和活动任务数；游客不能访问个人知识库、历史记录和用户资料。

### 断点续答

登录用户进度保存在 MySQL；游客进度保存在 Taro Storage。保存内容包括当前题号、答题记录、状态和版本号。首页只展示 `in_progress`、`ready_for_report` 状态的练习，支持继续或幂等删除。

生成报告时，答案、报告和 XP 在同一事务中写入。已存在报告时不重复增加 XP。

## 技术栈

| 层 | 技术 | 项目中的职责 |
| --- | --- | --- |
| 小程序 | Taro 4.2.1、React 18.3、TypeScript 5.6、Sass | 页面、表单、答题交互和微信小程序构建 |
| 状态管理 | Zustand 5、Taro Storage | 当前题组、生成任务、答题进度和登录状态 |
| API | FastAPI、Uvicorn、Pydantic v2 | 异步接口、依赖注入、Schema 校验和 OpenAPI |
| 数据访问 | SQLAlchemy 2 Async、aiomysql、Alembic | 异步连接池、参数化 SQL 兼容层和结构迁移 |
| 模型调用 | LangChain、langchain-openai、DeepSeek | Prompt 组合、JSON 输出、主题判断、出题和报告 |
| Agent | LangGraph | 保存检索状态、执行工具、控制循环和结束条件 |
| 搜索 | langchain-tavily | 关键词搜索和指定 URL 全文抽取 |
| 向量检索 | Milvus、langchain-milvus、PyMilvus | 公共/个人知识片段的向量检索和标量过滤 |
| 向量数据库 | Milvus | 个人与公共知识库检索 |
| Embedding | DashScope `text-embedding-v4` | 文档块和查询向量化 |
| 文档解析 | pypdf、docx2txt | PDF、DOCX 文本抽取 |
| 图片 | DashScope、Pillow、腾讯云 COS SDK | 生图、文件校验和对象存储 |
| 鉴权与安全 | 微信 `jscode2session`、PyJWT、`msgSecCheck` | 登录、接口鉴权和文本安全检测 |
| 测试 | pytest、Node Test Runner、TypeScript | 后端单元/接口测试、前端状态和导航测试 |

数据库层处于渐进式 ORM 迁移阶段：表结构已由 SQLAlchemy Model 和 Alembic 管理，现有 Repository 通过 SQLAlchemy `AsyncSession` 兼容适配器执行参数化 SQL；`DATABASE_BACKEND=aiomysql` 可切回旧连接池。

## 项目结构

```text
easyoffer/
├── backend/
│   ├── app/
│   │   ├── api/v1/routes/       # API 路由
│   │   ├── core/                # 配置、数据库、鉴权、游客、异常
│   │   ├── db/                  # SQLAlchemy Model、Session 和兼容层
│   │   ├── models/              # Pydantic 请求和响应模型
│   │   ├── repositories/        # MySQL 数据访问
│   │   ├── services/            # 出题、报告、进度、用户、知识库、图片
│   │   ├── llm/                 # DeepSeek 调用和 Prompt
│   │   ├── research/            # LangGraph、路由、Tavily 和证据处理
│   │   ├── corpus/              # 公共语料流水线
│   │   └── media/               # DashScope 生图和 COS
│   ├── alembic/                 # 数据库迁移
│   ├── corpus/                  # 语料清单、评估集和审核记录
│   ├── tests/                   # 后端测试
│   └── pyproject.toml
├── frontend/
│   ├── src/pages/               # 首页、生成、答题、报告、用户、历史、知识库
│   ├── src/components/          # 通用组件
│   ├── src/services/            # 请求封装和登录存储
│   ├── src/store/               # Zustand Store
│   ├── src/styles/              # 全局样式和动效变量
│   ├── tests/                   # 前端测试
│   └── package.json
├── docs/                        # 技术和运维文档
├── openspec/                    # 需求变更规格
└── README.md
```

## 数据库表

| 表 | 用途 |
| --- | --- |
| `users` | 微信 openid、昵称、头像、XP |
| `quiz_sessions` | 完整题组和用户原始主题 |
| `answer_records` | 已完成练习的答案、正确数和正确率 |
| `reports` | 复盘报告 JSON |
| `quiz_progress` | 普通练习的当前题号、答案、状态和版本 |
| `quiz_generation_tasks` | 增量生成请求、题目快照、任务状态和两个版本号 |
| `guest_generation_usage` | 游客每日额度和活动任务数 |
| `knowledge_documents` | 个人文档元数据、处理状态和片段数 |
| `quiz_visual_assets` | 生图任务、COS 地址、尺寸和错误信息 |

表结构由 `backend/app/db/models.py` 映射，由 Alembic 迁移维护。向量正文存放在 Milvus，图片文件存放在 COS，不写入 MySQL BLOB。

## API

接口前缀：`/api/v1`

| 方法 | 路径 | 认证 | 说明 |
| --- | --- | --- | --- |
| GET | `/health` | 否 | 健康检查 |
| POST | `/quiz/generate` | 可选 | 同步生成完整题组 |
| POST | `/quiz/generation-tasks` | 可选 | 创建增量生成任务 |
| GET | `/quiz/generation-tasks/{task_id}` | 可选 | 获取任务快照 |
| PUT | `/quiz/generation-tasks/{task_id}/progress` | 可选 | 保存增量任务进度 |
| POST | `/quiz/generation-tasks/{task_id}/retry` | 可选 | 重试失败任务 |
| POST | `/report/generate` | 可选 | 生成报告；登录用户会持久化 |
| POST | `/user/login` | 否 | 微信登录 |
| GET | `/user/profile` | 是 | 用户资料与统计 |
| PUT | `/user/profile` | 是 | 修改昵称 |
| POST | `/user/avatar` | 是 | 上传头像 |
| GET | `/user/quizzes` | 是 | 历史练习列表 |
| GET | `/user/quizzes/{quiz_id}` | 是 | 历史题组和报告 |
| GET | `/user/quizzes/incomplete` | 是 | 未完成练习 |
| GET | `/user/quizzes/{quiz_id}/progress` | 是 | 获取练习进度 |
| PUT | `/user/quizzes/{quiz_id}/progress` | 是 | 更新练习进度 |
| DELETE | `/user/quizzes/{quiz_id}/progress` | 是 | 放弃未完成练习 |
| GET | `/knowledge/documents` | 是 | 个人文档列表 |
| GET | `/knowledge/documents/{document_id}` | 是 | 文档详情和处理状态 |
| POST | `/knowledge/documents` | 是 | 上传文档 |
| PUT/PATCH | `/knowledge/documents/{document_id}` | 是 | 重命名文档 |
| POST | `/knowledge/documents/{document_id}/retry` | 是 | 重试失败文档 |
| DELETE | `/knowledge/documents/{document_id}` | 是 | 删除文档和向量 |

成功响应格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

完整请求和响应结构见 FastAPI Swagger：<http://127.0.0.1:8000/docs>。

## 环境要求

| 软件 | 版本 |
| --- | --- |
| Python | 3.11+ |
| Node.js | 18+ |
| MySQL | 8.0+ |
| 微信开发者工具 | 当前稳定版 |
| Milvus | 2.5+，启用知识库时需要 |

## 快速启动

### 1. 配置后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Linux/macOS 激活命令：

```bash
source .venv/bin/activate
```

最小配置：

```dotenv
DEEPSEEK_API_KEY=your-deepseek-key
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DATABASE=easyoffer
DATABASE_BACKEND=sqlalchemy
JWT_SECRET=replace-with-a-random-secret
```

初始化数据库：

```powershell
alembic upgrade head
```

启动后端：

```powershell
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. 配置可选服务

联网搜索：

```dotenv
TAVILY_ENABLED=true
TAVILY_API_KEY=your-tavily-key
```

Milvus 和 Embedding：

```dotenv
MILVUS_ENABLED=true
MILVUS_URI=http://127.0.0.1:19530
MILVUS_PUBLIC_COLLECTION=easyoffer_public_chunks
MILVUS_PRIVATE_COLLECTION=easyoffer_private_chunks
EMBEDDING_API_KEY=your-dashscope-key
EMBEDDING_MODEL=text-embedding-v4
```

微信登录和内容安全：

```dotenv
WECHAT_APP_ID=your-app-id
WECHAT_APP_SECRET=your-app-secret
WECHAT_CONTENT_SECURITY_ENABLED=true
```

图片生成和 COS：

```dotenv
DASHSCOPE_API_KEY=your-dashscope-key
IMAGE_GENERATION_ENABLED=true
IMAGE_GENERATION_MODEL=z-image-turbo
IMAGE_GENERATION_SIZE=512*512

COS_ENABLED=true
COS_SECRET_ID=your-secret-id
COS_SECRET_KEY=your-secret-key
COS_REGION=ap-guangzhou
COS_BUCKET=your-bucket
COS_PUBLIC_READ=true
```

完整配置及超时、重试、额度参数见 `backend/.env.example`。

`IMAGE_GENERATION_MODEL` 默认使用 `z-image-turbo`，也可切换为已在百炼授权的 `qwen-image-2.0`。

### 3. 启动前端

```powershell
cd ../frontend
npm install
Copy-Item project.config.example.json project.config.json
npm run dev:weapp
```

将 `project.config.json` 中的 `appid` 替换为自己的微信小程序 AppID。该文件和微信开发者工具生成的 `project.private.config.json` 仅供本机使用，已被 Git 忽略；仓库只保留脱敏模板。

微信开发者工具导入 `frontend`，其 `miniprogramRoot` 指向 `dist/`。本地调试 `127.0.0.1:8000` 时，需要在开发者工具中关闭合法域名校验。

生产构建：

```powershell
npm run build:weapp
```

H5 构建输出到独立的 `frontend/h5-dist`：

```powershell
npm run build:h5
```

## 测试

后端测试：

```powershell
cd backend
pytest -q
```

前端检查：

```powershell
cd frontend
npm run typecheck
npm run test:frontend
npm run test:quiz-navigation
npm run build:weapp
```

后端测试使用替身隔离 DeepSeek、Tavily、Milvus、DashScope、COS 和微信接口，不消耗线上额度。覆盖范围包括：

- 主题判断和内容安全；
- 查询扩展、证据过滤和 Agent 路由；
- Milvus 过滤、父块恢复和个人数据隔离；
- 增量生成任务、重复题检测和失败重试；
- 进度乐观锁、409 合并、报告与 XP 幂等；
- 文档解析、分块、去重、评估和发布；
- 图片校验、COS 上传和失败降级。

## 部署

后端适合部署到微信云托管或其他 Docker 容器平台。生产环境使用云 MySQL、Milvus Standalone/托管 Milvus 和腾讯云 COS，密钥通过平台环境变量注入。

部署顺序：

```text
创建 MySQL
  → 部署 Milvus 并创建公共/个人集合
  → 配置 DeepSeek、Tavily、DashScope、COS 和微信密钥
  → 运行 Alembic 迁移
  → 部署 FastAPI 容器
  → 配置 HTTPS 和小程序合法域名
  → 导入并发布公共语料版本
  → 构建并上传小程序
```

Milvus 不保存用户、答题记录和报告；COS 不保存知识库正文。MySQL、Milvus 和 COS 的职责保持分离。

## 截图

<!-- 截图完成后取消注释并替换文件路径。 -->

<!-- ![答题首页](docs/screenshots/home.png) -->
<!-- ![题目生成](docs/screenshots/generating.png) -->
<!-- ![答题与解析](docs/screenshots/quiz.png) -->
<!-- ![复盘报告](docs/screenshots/report.png) -->
<!-- ![个人知识库](docs/screenshots/knowledge.png) -->
