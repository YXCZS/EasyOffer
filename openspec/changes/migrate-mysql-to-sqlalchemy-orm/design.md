## Context

当前后端使用 `aiomysql.create_pool`，通过 repository 直接执行参数化 SQL。业务表和初始化 DDL 分散在多个文件；部分操作需要 JSON 序列化、MySQL Upsert、`FOR UPDATE`、乐观锁和显式回滚。现有接口和核心答题流程必须保持不变。动机和范围见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 建立统一的 SQLAlchemy 2.x Async Engine、`async_sessionmaker` 和 FastAPI Session 依赖。
- 保持 `mysql+aiomysql` 连接方式、现有表名/字段/索引和接口数据格式兼容。
- 用 SQLAlchemy ORM 表达常规实体读写，用 SQLAlchemy Core 表达复杂聚合、JSON、批量更新和 MySQL 特有 Upsert。
- 用 Alembic 管理结构迁移；应用启动不再执行生产级 `CREATE TABLE`/`ALTER TABLE`。
- 保留行锁、乐观锁、事务边界和任务幂等语义，并用测试证明行为一致。
- 支持分阶段迁移和单阶段回滚，不要求一次性替换全部 repository。

**Non-Goals:**

- 不更换 MySQL，不迁移到 PostgreSQL，不改变云数据库部署方式。
- 不把 Milvus、Chroma 或 COS 纳入 SQLAlchemy 管理。
- 不改变任何前端页面、API 路径、请求响应模型、题目生成和报告业务规则。
- 不把所有 SQL 强行改写成 ORM；必要的数据库特性可以保留为受控 Core 表达式。

## Decisions

### 1. 采用 SQLAlchemy 2.x Async + aiomysql

使用 `create_async_engine("mysql+aiomysql://...")` 和 `async_sessionmaker`。SQLAlchemy 官方提供 MySQL aiomysql 方言，能够继续复用现有驱动和连接配置，减少基础设施变更。`expire_on_commit=False` 避免提交后访问实体属性触发异步隐式 IO；连接池启用 `pool_pre_ping` 和合理的 recycle/timeout。

备选方案：Tortoise ORM 上手更简单，但当前项目已有复杂锁、JSON、Upsert 和统计查询；这些场景在 Tortoise 中需要更多特殊 API，且迁移通常依赖 Aerich。综合兼容性和长期生态，暂不采用。

### 2. ORM 与 Core 混合，而非纯 ORM

用户、答题会话、进度、报告、知识库文档和图片资源使用声明式 Model；统计列表、JSON 原子更新、`ON DUPLICATE KEY UPDATE` 和需要精确控制锁的查询使用 `select/update/insert` Core 表达式。所有值仍通过绑定参数传递，禁止把用户输入拼进 SQL；动态列名只允许来自固定白名单。

### 3. Session 生命周期由 FastAPI 依赖管理

每个请求获取一个 `AsyncSession`，请求结束后关闭；跨多个写操作的业务事务使用 `async with session.begin()`，异常自动回滚。后台增量任务不复用请求 Session，而是在任务步骤内独立获取 Session，避免请求结束后使用失效连接。

### 4. Alembic 作为唯一结构迁移入口

创建与异步 Engine 兼容的 Alembic `env.py`，目标元数据指向所有 SQLAlchemy Model。现有数据库先进行 schema 基线核对，再通过 `alembic stamp` 标记初始版本；后续字段、索引和表变更使用人工审核过的迁移脚本。迁移脚本禁止直接删除或重命名生产数据，破坏性变更必须拆成兼容的多步迁移。

### 5. Repository 接口先保持不变

Service 层继续调用现有 repository 函数，先替换 repository 内部的连接/查询实现。这样可以把 ORM 改造与 API/前端变更隔离；每迁移一个 repository，运行其数据库集成测试，再进入下一个模块。旧的 aiomysql 实现保留到全部模块通过验收后再删除。

### 6. 数据一致性与并发语义不变

任务抢占和报告 XP 更新继续使用事务；需要锁的读取使用 `with_for_update()`；增量任务和答题进度继续使用版本字段进行乐观锁校验。JSON 字段保持 UTF-8 内容和现有数组/对象结构，时间字段继续按现有 API 格式序列化。

## Risks / Trade-offs

- [迁移期间两套数据访问实现并存] -> 通过 repository 接口隔离、逐模块切换和全量回归测试控制；禁止同一写路径同时双写。
- [Alembic 自动生成误判字段重命名或索引变化] -> 所有自动生成脚本必须人工审查，并在测试数据库执行升级/降级验证。
- [异步 ORM 隐式懒加载导致运行时错误] -> 默认不依赖懒加载，使用显式查询或 `selectinload`；Session 提交后不访问过期实体。
- [MySQL Upsert/JSON 行为与旧 SQL 不一致] -> 对用户登录、报告保存、进度保存和生成任务追加题目增加旧新实现结果对比测试。
- [连接池配置不当导致连接耗尽] -> 先沿用当前小连接池容量，增加 pool timeout、健康检查和指标，再根据压测调整。
- [初始迁移与实际云数据库 schema 不一致] -> 上线前导出真实 schema、执行只读 diff；不通过基线校验不得运行迁移。
- [ORM 抽象增加少量 CPU 开销] -> 保留 Core/批量操作，性能基线以数据库查询耗时和端到端生成耗时为准；AI/Tavily 仍是主要延迟来源。

## Migration Plan

1. 备份 MySQL，记录当前表、索引、约束、字符集和时区配置，建立迁移前基线。
2. 增加 SQLAlchemy/Alembic 依赖和数据库基础设施，但暂不改变业务 repository。
3. 建立 Model 和 Alembic 初始基线，使用测试库验证升级、回滚和 schema diff。
4. 按“用户 -> 答题/报告 -> 进度 -> 增量任务 -> 知识库 -> 图片资源”顺序迁移，每阶段运行针对性集成测试和全量 pytest。
5. 灰度环境先执行 `alembic upgrade head`，观察连接池、错误率、事务回滚和接口延迟。
6. 全部 repository 迁移并稳定后，删除启动时 `ensure_*` 建表/改表逻辑；部署流程固定先迁移、后启动应用。

回滚策略：如果某一阶段出现问题，停止后续迁移并将 repository 实现切回旧适配器；已执行的结构迁移只允许执行经过验证的 downgrade，数据迁移需提供反向脚本和备份恢复方案。因为不改变业务表数据格式，正常情况下无需回滚数据。

## Open Questions

无。驱动、ORM、迁移工具和渐进式边界已确定；具体字段类型映射在实现阶段依据真实 MySQL schema 逐表确认。
