# Milvus 运维与回滚

EasyOffer 首期使用 Milvus Standalone。应用通过 `MILVUS_URI` 和可选的 `MILVUS_TOKEN` 连接，集合由 `python -m app.services.milvus_admin` 幂等初始化。新集合必须配置 `MILVUS_VECTOR_DIMENSION`，该值必须与 Embedding 模型维度一致。

备份时保存 Milvus 数据卷和配置文件；恢复时停止应用，恢复数据卷后启动 Milvus，再运行初始化命令并执行健康检查。升级前先复制数据卷并在测试环境验证集合加载和检索结果。

规模增长后可迁移到 Distributed 部署：先保持集合名称、字段和向量维度不变，使用检索对比工具确认召回一致率达到 0.9 后再切换 `MILVUS_URI`。升级失败时保留 MySQL 元数据和 COS 图片不受影响，并通过基础模型降级保证出题流程可用。
