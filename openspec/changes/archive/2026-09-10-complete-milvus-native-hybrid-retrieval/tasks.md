## 1. Milvus 检索适配器

- [x] 1.1 在 native hybrid 检索入口增加 ranker 构造适配器，优先使用当前 `langchain-milvus` 推荐的 RERANK Function API，并兼容已安装 `pymilvus` 的 `RRFRanker`；用单元测试断言实际传入 Milvus 的 strategy 为 `rrf` 且 k 等于 `MILVUS_RRF_K`
- [x] 1.2 为 dense 和 BM25 计算并校验实际预召回深度，将 `MILVUS_DENSE_RECALL_K`、`MILVUS_SPARSE_RECALL_K` 和最终 k 传入 hybrid 请求；用 mock `hybrid_search` 测试确认不再使用默认 `fetch_k=4`
- [x] 1.3 保持 hybrid 融合后再执行 DashScope rerank，验证候选截断发生在 rerank 之后；补充 rerank 可用、超时和失败降级测试
- [x] 1.4 为 native 模式增加检索模式、集合名、fetch_k、RRF k、候选数量和耗时日志；测试日志不包含 API Key、Token 和完整文档原文
- [x] 1.5 对 Milvus 异常保留原始失败类型和安全摘要，避免统一吞掉错误；用失败 mock 测试确认 API 仍返回兼容错误结构且日志可定位

## 2. 配置与集合运维

- [x] 2.1 将 `.env` 解析为相对于 backend 应用根目录的稳定路径，并保留进程环境变量覆盖；分别从仓库根目录和 backend 目录运行配置检查，确认 Embedding、DashScope、Milvus URI 均一致
- [x] 2.2 为 `MILVUS_RRF_K`、dense/sparse recall、fetch 上限增加正数和范围校验；用配置单元测试覆盖空值、负数、非数字和超上限场景
- [x] 2.3 完善 `milvus_admin` 的 schema/索引/Function/向量维度检查和幂等初始化；在真实 Standalone 上重复执行初始化，确认不改动现有行数
- [x] 2.4 增加健康检查输出集合存在、加载状态、schema 版本和服务版本的非敏感摘要；验证 HTTP 健康接口与命令行健康检查结果一致

## 3. 公共与私有数据隔离

- [x] 3.1 为公共检索补充 published、corpus_version、role_tags 的组合过滤测试，验证 inactive/withdrawn 版本不会进入默认线上结果
- [x] 3.2 为私有写入、检索、更新和删除补充 owner_id 隔离测试，验证跨用户 document_id 和 chunk_id 均被拒绝且数据不变
- [x] 3.3 编写真实 Standalone 私有知识库 smoke test：创建随机临时文档、写入 embedding、执行 native hybrid 检索、验证命中和跨 owner 不可见、更新替换、删除清理；测试结束后比较集合行数并确保恢复

## 4. 应用层 BM25 下线

- [x] 4.1 扫描在线服务、脚本和测试对 `rank-bm25`、`_bm25_search`、`_rrf_merge` 的引用，明确仅保留迁移兼容所需的引用；用静态检查结果记录引用清单
- [x] 4.2 在 native 模式增加防回归测试，确认不会调用 Milvus 全量 query 构建应用层 BM25，也不会对 native 结果做二次 RRF
- [x] 4.3 在 Standalone smoke test 和 benchmark 门禁通过后删除在线 adapter 的 `rank-bm25` 依赖、缓存和旧分支，并运行完整 pytest 确认无残留引用
- [x] 4.4 更新 `.env.example`、运行手册和检索文档，明确 Lite 只作为迁移备份，生产仅连接 Standalone native hybrid；用文档链接和配置扫描检查完成

## 5. 检索质量与性能评测

- [x] 5.1 固化一份包含中文技术词、英文标识符、长问题和无关问题的 golden query 数据集，并为每条样本标注期望文档/chunk；验证数据格式可被 benchmark 脚本读取
- [x] 5.2 执行 dense-only、native dense+BM25+RRF、native hybrid+DashScope 三组对比，输出 Recall@k、Hit@k、MRR、nDCG、答案相关性和来源可追溯性
- [x] 5.3 记录每组 p50/p95 延迟、Embedding 次数、Milvus 候选数、RRF 候选数和 rerank 耗时；将代码 revision、集合名、RRF k、recall 深度写入报告
- [x] 5.4 设置质量和 p95 延迟门禁，构造一个故意退化的配置验证 benchmark 会失败，而不是只生成无门槛报告

## 6. 前端与系统回归

- [x] 6.1 保持现有 Taro API 返回结构不变，执行前端 typecheck 和微信小程序构建，确认“答题”和“我的”页面无编译回归
- [x] 6.2 在微信开发者工具中验证输入知识点生成题目、使用公共知识库检索、使用私有知识库检索和报告生成关键流程；确认 Milvus 异常时页面仍能展示可理解的失败提示
- [x] 6.3 启动完整后端服务并执行健康接口、登录态请求和一次真实题目生成 smoke test；记录请求耗时、检索模式和无敏感信息的日志摘要

## 7. 发布与回滚

- [x] 7.1 发布前保存 Standalone 集合行数、加载状态、schema 描述和当前 benchmark 基线；按最新决策确认旧 Lite 不再作为运行依赖且本机无残留 Lite 数据目录
- [x] 7.2 在测试环境完成新代码观察窗口，验证异常率、rerank 降级率、p95 延迟和集合行数无异常后再标记生产可用
- [x] 7.3 演练仅回退应用代码/feature flag 的恢复路径，确认不删除 native 集合；如需回退旧 dense-only 集合，先执行召回一致性检查并记录结果
