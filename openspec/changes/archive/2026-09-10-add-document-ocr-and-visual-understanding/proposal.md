## Why

EasyOffer 当前通过 MinerU 获取文档结构，但扫描型 PDF、Word 内嵌图片和复杂图片表格还没有完整的分层处理链路。需要明确区分文件格式、内容形态和节点类型：扫描 PDF 逐页转图后 OCR，复杂版面使用多模态模型，Word 保留原生结构并单独处理图片，图片按 OCR 或 VLM 分流。

## What Changes

- 增加扩展名、MIME、Magic Bytes 和专业库打开结果的文件真实类型校验。
- 文本型 PDF 使用结构化文档解析，保留文字、页码、标题、表格和坐标。
- 扫描型和混合型 PDF 必须先逐页渲染为图片，再执行 OCR；复杂版面可追加多模态理解。
- Word 保留段落、标题层级、列表、表格、页眉页脚和图片；内嵌图片单独进入 OCR 或 VLM 分支。
- 图片按内容分流：文字截图、票据、扫描件走 OCR；图表、流程图、产品照片走 VLM。
- 复杂图片表格组合 OCR 文本、版面坐标和 Qwen-VL 描述，并在写入知识库前校验。
- 将视觉摘要、元素和关系作为有来源的文本证据写入现有 Parent/Child 和 Milvus 文本检索链路。
- OCR 或视觉理解失败时保留可验证文本并记录 degraded 状态，不阻塞其他内容摄取。
- 增加 OCR、复杂表格、Word 图片、图表理解和端到端质量评测。
- 不改变现有答题、报告、底部导航、Milvus 检索和版本过滤行为。

## Capabilities

### New Capabilities

- `document-ocr`: 文件真实类型校验、PDF 内容形态识别、逐页图像化 OCR 和结果降级。
- `document-visual-understanding`: 复杂版面、图片表格、图表、流程图和 Word 图片的多模态理解。

### Modified Capabilities

- `knowledge-ingestion`: 摄取流程必须根据文件类型和内容形态选择解析分支，并保留完整来源。

## Impact

- 后端：`app/corpus`、`app/services/mineru_service.py`、知识库摄取流水线、Milvus 元数据和 pytest。
- 外部服务：MinerU OCR/结构解析和 DashScope Qwen-VL；复用现有超时、重试和密钥配置。
- 数据：新增文件类型、OCR 判定、视觉分析和 degraded 元数据；旧文本 Parent/Child 保持兼容。
- 运维：增加 OCR、视觉模型、并发、超时和 feature flag 配置；日志不得记录 API Key 或原始敏感文件内容。
