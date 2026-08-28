# EasyOffer 公共面试语料运维手册

以下命令都在 `backend` 目录执行。首次操作先运行：

```powershell
python -m app.corpus.cli --help
python -m app.corpus.cli preview --help
python -m pytest -q tests/test_corpus_manifest.py tests/test_corpus_parsing_chunking.py tests/test_corpus_pipeline.py tests/test_corpus_evaluation.py tests/test_corpus_cli.py
```

## 1. 登记资料

1. 把自有或已获授权的文件放入受控资料目录，不要放密钥。
2. 在 `corpus/manifests/` 新建或更新 YAML。
3. 每条来源填写 `document_id`、路径或 URL、来源名、技术、岗位、文档版本、语言、内容类型、许可状态和目标 `corpus_version`。
4. 官方网页参考还要记录 URL、抓取日期、内容版本和许可判断。
5. 无法确认正式再发布许可时必须使用 `license_status: local-evaluation-only`，不得改成 `approved` 以绕过发布门禁。

## 2. 预览

预览只解析、清洗、切分、去重和检查，不写 Milvus：

```powershell
python -m app.corpus.cli --config corpus/config.yaml --store memory preview corpus/manifests/pilot-v1.yaml
```

检查 JSON 输出中的失败文档、`quality_issues`、重复数、父单元数和分块数。扫描版、空白、加密或损坏 PDF 必须显示具体失败原因。运行产物默认在 `data/public-corpus/runs/`。

## 3. 摄取候选版本

确认 `.env` 中 Milvus 和 Embedding 配置完整，并已创建公共集合。不要在生产集合上用未授权资料执行此命令。

```powershell
python -m app.services.milvus_admin
python -m app.corpus.cli --config corpus/config.yaml ingest corpus/manifests/approved-v1.yaml
python -m app.corpus.cli --config corpus/config.yaml inspect approved-v1
```

摄取后的分块必须保持 `unpublished`。同一清单重跑会复用 `data/public-corpus/runs/ingest-*/documents/<document_id>/` 下的 `parsed.json`、`parents.json`、`chunks.jsonl` 和 `status.json`，仅从失败或缺失阶段继续。某个文档失败时，批次保留其他统计，但整个候选版本不能通过审批。

## 4. 检索评估和人工抽检

```powershell
python -m app.corpus.cli --config corpus/config.yaml evaluate corpus/benchmarks/pilot-v1.yaml approved-v1
```

检查 Hit@5、MRR@5、NDCG@5、知识覆盖、重复结果、岗位污染、来源追溯、父级恢复和 P50/P95。复制 `corpus/reviews/pilot-v1.template.yaml` 为 `corpus/reviews/<corpus_version>.yaml`，填写 `reviewer`、`reviewed_at`、`decision: approved`、`decision_reason`，并抽检高分、低分、边界和冲突样本；每条必须写 `query_id`、`chunk_id` 和 `parent_id`。审核文件在仓库中版本控制，不能写密钥或完整第三方正文。

## 5. 审批与发布

只有自动门禁通过且人工抽检完成后才能审批：

```powershell
python -m app.corpus.cli --config corpus/config.yaml approve approved-v1 --reviewer owner --review-file corpus/reviews/approved-v1.yaml
python -m app.corpus.cli --config corpus/config.yaml publish approved-v1
python -m app.corpus.cli --config corpus/config.yaml stats
```

如确需人工豁免，`--override-reason` 必须记录具体、可审计的原因，不能写“临时通过”。审批会核对审核文件的版本、审核人、结论、理由和抽样记录。发布先激活候选、停用旧版，再做冒烟检索；任何异常都会尝试恢复旧版并生成 rollback 报告。

## 6. 替换、撤回和重试

替换资料时使用新的 `document_version` 和 `corpus_version`，重复第 2～5 步。不要覆盖旧版本清单或基准。

```powershell
python -m app.corpus.cli --config corpus/config.yaml withdraw approved-v1 --reason "来源授权已撤回"
python -m app.corpus.cli --config corpus/config.yaml retry approved-v2
python -m app.corpus.cli --config corpus/config.yaml inspect approved-v1
```

撤回版本会立即从默认公共检索中消失，但其元数据和原因仍可审计。`retry` 重新执行最近候选清单，稳定 ID 保证已成功内容幂等覆盖。

## 7. 回滚与故障排查

- 发布冒烟失败：查看 `data/public-corpus/reports/publish-*-rollback.json`，确认旧 `active_version` 已恢复。
- `license_not_approved`：先确认授权；不能用豁免绕过许可问题。
- `scanned_or_empty_pdf`：当前版本不支持 OCR，换用可复制文本的资料。
- `possible_mojibake`：修正文件编码或解析器，重新预览。
- `metadata_incomplete`：补清单字段，不要在存储适配层伪造来源。
- Milvus 连接失败：检查 `MILVUS_URI`、Token、集合和向量维度；参考 `docs/milvus-operations.md`。
- Embedding 失败：检查 Embedding API Key、模型、Base URL 和维度是否与集合一致。

## 8. 发布前最终验证

```powershell
python -m pytest -q
python -m compileall -q app
Set-Location ..\frontend
npm run typecheck
npm run build:weapp
```

目标 Milvus Standalone 上还必须单独记录过滤、父级扩展和 P50/P95 延迟。微信开发者工具中验证登录、游客限制、普通主题、公共语料主题、个人文档专属出题、增量答题、未完成练习、报告和“我的”。未实际执行的环境验证不得标记为通过。
