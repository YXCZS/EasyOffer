## Context

当前 `parse_source_async` 优先调用 MinerU，`is_ocr` 由全局配置控制且默认关闭；本地 PDF 降级使用 pypdf，无法处理图片型扫描件。MinerU 已能返回标题、段落、表格、图片、图表、页码、bbox 和媒体路径，但现有系统没有逐页扫描 PDF OCR 和文档视觉理解链路。

## Goals / Non-Goals

**Goals:**

- 先完成真实文件类型校验，再判断 PDF 是文本型、扫描型还是混合型。
- 扫描 PDF 强制执行“逐页转图片 → OCR”；复杂版面再调用 Qwen-VL。
- Word 保留原生结构，内嵌图片独立进入 OCR 或 VLM 分支。
- 复杂图片表格组合 OCR 文本、bbox 和 VLM 结构化结果。
- 复用现有 Parent/Child、文本 Embedding、Milvus 权限和版本过滤。

**Non-Goals:**

- 不引入第二套向量数据库或图像向量 Collection。
- 本次不替换 MinerU 为 PaddleOCR；PaddleOCR 只作为未来本地 OCR 备选。
- 不对普通装饰图片批量调用视觉模型。
- 不改动答题、报告、底部导航和现有检索 API。

## Decisions

1. **文件判断分三层**：扩展名/MIME/Magic Bytes 判断真实格式；PDF 预检测判断内容形态；MinerU 节点类型决定 OCR、表格增强或 VLM。Qwen-VL 不负责文件格式识别。
2. **扫描 PDF 逐页图像化**：pypdf 只用于预检测，不能作为扫描件 OCR。扫描页先渲染图片，再送 MinerU OCR；页码、图片序号和来源必须贯穿后续结构。
3. **MinerU 主解析，Qwen-VL 增强**：文本型 PDF、Word 正文和基础表格优先由 MinerU 解析；复杂版面、图片表格、图表、流程图和 Word 图片按策略调用 Qwen-VL。
4. **复杂表格多源校验**：将 OCR 文本、bbox、原图和章节上下文一起提供给 VLM；表头、行列、合并关系和关键数字校验失败时不覆盖原始结果。
5. **视觉结果文本化**：视觉摘要、元素和关系转为带章节和来源前缀的 `embedding_text`，原图路径、页码、bbox、模型和不确定性写入 metadata，继续使用现有文本 Embedding 与 Milvus。
6. **增强失败隔离**：OCR/VLM 设置超时、有限重试、有界并发和预算；失败只标记对应页面或节点为 degraded，不阻塞可用正文入库。

## Risks / Trade-offs

- [文件伪造或容器损坏] → 使用 Magic Bytes 和专业库双重校验，冲突时拒绝下游调用。
- [扫描检测误判] → 记录文字密度和空页比例；不确定时开启 OCR，并用样本校准阈值。
- [逐页 OCR 增加成本和延迟] → 仅对扫描/混合页面启用，设置页数、超时和并发上限。
- [Qwen-VL 幻觉或表格错位] → 强制 JSON、保留 uncertainties、执行 OCR/bbox 交叉校验，失败不覆盖原文。
- [媒体文件过大或敏感] → 限制格式和大小，日志只记录文档/节点 ID，不记录原始图片内容和密钥。
- [旧数据兼容] → 新字段全部可选，旧 Parent/Child 继续按原文本链路检索，Milvus 采用兼容字段迁移。

## Migration Plan

1. 增加文件类型、OCR 判定和视觉状态的可选字段，默认视觉分析关闭。
2. 部署 Magic Bytes 校验和 PDF 预检测，先验证普通、扫描、混合 PDF。
3. 开启逐页图像化 OCR，回归页码、标题、段落和表格来源。
4. 小流量启用 Qwen-VL，验证 Word 图片、复杂表格、图表和流程图。
5. 全量启用后保留 feature flag；出现问题时可关闭 VLM 或恢复固定 OCR，不删除已有文本数据。

## Open Questions

- Qwen-VL 的具体模型、区域 endpoint 和单页成本需在接入测试账号后通过实测确定。
- OCR 和视觉节点筛选阈值需使用项目样本校准，不在设计阶段固定最终数值。
