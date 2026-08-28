## Why

EasyOffer 当前通过 aiomysql 在多个 repository 中手写 SQL，并在应用启动时分散执行建表和 `ALTER TABLE`。随着用户、答题进度、增量生成任务、知识库和图片资源表持续增加，重复的连接/事务/结果转换代码会提高维护和回归风险，也缺少可审计的数据库结构迁移版本。现在进行渐进式 ORM 化，可以在继续使用现有 MySQL 数据和业务接口的前提下，建立统一的数据访问和迁移基础。

## What Changes

- 引入 SQLAlchemy 2.x Async，继续使用 MySQL 和 `aiomysql` 驱动。
- 引入 Alembic，使用版本化迁移管理表结构，不再依赖生产环境启动时自动修改表结构。
- 建立与现有表兼容的 SQLAlchemy 数据库模型和异步 Session 依赖。
- 按业务域逐步迁移 repositories；复杂统计、JSON、锁和 MySQL Upsert 可使用 SQLAlchemy Core 保留明确语义。
- 保持现有 API 路径、请求响应结构、题目生成、答题、报告、知识库、Milvus/Chroma 和 COS 行为不变。
- 为每个迁移阶段补充数据库集成测试、事务回滚、并发版本校验和迁移验证。
- **不做**一次性重写全部数据访问代码，不更换 MySQL，不把向量数据库或 COS 纳入 ORM 管理。

## Capabilities

### New Capabilities

- 无。本变更是数据库访问层和迁移工具的内部重构，不新增用户可见的业务能力。

### Modified Capabilities

- 无。现有业务需求和 API 契约不变。

## Impact

- 后端依赖增加 SQLAlchemy 2.x Async 和 Alembic。
- 影响 `backend/app/core/db.py`、`backend/app/repositories/`、数据库模型目录、应用生命周期和部署脚本。
- 需要以现有 MySQL schema 为基线创建初始 Alembic 版本，并在迁移稳定后移除启动时的 `ensure_*` 建表/改表逻辑。
- 需要保留现有 aiomysql 测试兼容层，逐个 repository 迁移并运行全量 pytest，避免影响核心答题流程。
