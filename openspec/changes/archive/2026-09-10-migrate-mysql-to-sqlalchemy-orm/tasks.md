## 1. 基础设施与依赖

- [x] 1.1 增加 SQLAlchemy 2.x Async、Alembic 依赖并锁定兼容版本，验证后端依赖安装和 `python -m compileall app` 通过
- [x] 1.2 创建 AsyncEngine、`async_sessionmaker` 和 FastAPI Session 依赖，配置 `mysql+aiomysql`、连接池健康检查和关闭流程，验证数据库健康接口及连接释放测试通过
- [x] 1.3 建立 SQLAlchemy Declarative Base 与统一数据库模型导入入口，验证所有现有表模型可加载且 metadata 无重复表定义

## 2. Schema 基线与迁移

- [x] 2.1 按真实 MySQL schema 映射 users、quiz_sessions、answer_records、reports、quiz_progress，验证字段、索引、外键和字符集 diff 无意外变化
- [x] 2.2 映射 quiz_generation_tasks、guest_generation_usage、knowledge_documents、quiz_visual_assets，验证 JSON、ENUM、时间字段和唯一约束与现库一致
- [x] 2.3 配置异步 Alembic env.py、初始基线迁移和升级/降级脚本，使用临时测试库验证 `alembic upgrade head`、`alembic downgrade` 和重复执行幂等
- [x] 2.4 增加部署文档和命令，明确先执行迁移后启动应用，并验证应用启动不依赖生产环境自动建表

## 3. Repository 渐进迁移

- [x] 3.1 保持现有 repository 函数签名，新增 Session 适配层并迁移 user_repository，验证微信登录、头像/昵称更新和历史列表接口结果与迁移前一致
- [x] 3.2 迁移 progress_repository 和报告保存事务，保留版本校验、XP 幂等和回滚语义，验证并发保存与重复提交测试通过
- [x] 3.3 迁移 generation_repository，保留任务抢占、逐题追加、进度保存、失败重试和过期恢复语义，验证增量出题集成测试通过
- [x] 3.4 迁移 knowledge_repository 和 visual_asset_repository，保留文档状态流转、删除、图片资源状态及 JSON 更新语义，验证知识库和 COS 相关测试通过
- [x] 3.5 在全部 repository 迁移完成前保留旧 aiomysql 实现作为可回退适配器，验证核心答题 API 可在新旧实现之间切换

## 4. 安全、性能与兼容性

- [x] 4.1 审查所有 ORM/Core 查询的参数绑定和动态字段白名单，增加 SQL 注入回归测试并验证用户输入不会进入 SQL 结构
- [x] 4.2 为 `FOR UPDATE`、乐观锁、事务回滚、JSON UTF-8 和时间序列化增加数据库集成测试，验证与现有 API schema 完全兼容
- [x] 4.3 对用户、答题、报告、增量任务和知识库关键查询建立迁移前后基准，验证连接池无泄漏且 P95 查询耗时无明显回归
- [x] 4.4 运行后端全量 pytest，验证核心生成、答题、报告、敏感词过滤和知识库流程全部通过

## 5. 切换与前端回归

- [x] 5.1 在测试环境执行 Alembic 基线和升级，切换所有生产 repository 到 SQLAlchemy 实现，验证 FastAPI 启动日志不再执行应用内建表/改表
- [x] 5.2 执行前端 typecheck 和微信小程序构建，验证 ORM 改造未改变接口响应和前端类型
- [x] 5.3 在微信开发者工具手动验证登录、主题生成、答题进度保存、报告查看、知识库上传和历史回看，确认核心流程与改造前一致
- [ ] 5.4 观察一个完整灰度周期的数据库错误率、连接池等待、事务回滚和接口延迟，确认无异常后删除旧 aiomysql repository 代码
