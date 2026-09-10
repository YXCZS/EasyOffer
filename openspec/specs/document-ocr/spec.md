# document-ocr Specification

## Purpose
让知识库能够按照文件真实格式和 PDF 内容形态选择可靠的解析链路，覆盖普通 PDF、扫描 PDF、混合 PDF 和文字图片，并在 OCR 失败时提供可诊断的降级结果。

## Requirements

### Requirement: 文件真实类型必须经过多信号校验

系统 SHALL 在解析前结合扩展名、MIME、Magic Bytes 和专业库打开结果判断真实文件类型。任一关键特征冲突或文件损坏时，系统 MUST 拒绝调用下游解析模型并返回明确错误。

#### Scenario: 类型一致
- **WHEN** 扩展名、MIME、文件头和专业库结果一致
- **THEN** 系统生成规范化文件类型并进入对应解析分支

#### Scenario: 客户端 MIME 不可用
- **WHEN** MIME 为 `application/octet-stream` 但文件头和专业库结果有效
- **THEN** 系统允许解析并以内容校验结果作为真实类型依据

#### Scenario: 类型冲突
- **WHEN** 文件名为 PDF 但 Magic Bytes 表明其为 PNG，或容器内部结构不匹配
- **THEN** 系统拒绝文件并返回类型冲突错误，不调用 MinerU、OCR 或 VLM

### Requirement: PDF 内容形态必须单独判定

系统 SHALL 对 PDF 进行只读预检测，统计页面文字密度、空文字页比例、图片信号、乱码和加密状态，并将结果分类为 text_pdf、scanned_pdf 或 mixed_pdf。

#### Scenario: 文本型 PDF
- **WHEN** 大多数页面存在可靠文字层且文字密度达到配置阈值
- **THEN** 系统标记为 text_pdf，并使用结构化文档解析，默认不启用 OCR

#### Scenario: 扫描型 PDF
- **WHEN** 大多数页面没有可靠文字层但存在页面图像
- **THEN** 系统标记为 scanned_pdf，并进入逐页图像化 OCR 流程

#### Scenario: 混合型 PDF
- **WHEN** PDF 同时包含文字页和无文字扫描页
- **THEN** 系统标记为 mixed_pdf，保留文字页直接解析，并对扫描页逐页图像化后 OCR

#### Scenario: 加密或损坏 PDF
- **WHEN** PDF 无法读取、被加密或页面结构损坏
- **THEN** 系统返回 encrypted_pdf 或 corrupted_pdf，不把空文本当作成功解析结果

### Requirement: 扫描 PDF 必须先逐页转图片再 OCR

被判定为 scanned_pdf 或 mixed_pdf 的 PDF SHALL 逐页渲染为图片，再对页面图片执行 OCR，并保留页码、图片序号和来源关联。pypdf 空文本结果不得作为扫描 PDF 的最终内容。

#### Scenario: 扫描 PDF 逐页 OCR
- **WHEN** PDF 页面没有可靠文字层
- **THEN** 系统生成对应页面图片并执行 OCR，将识别文本关联到原始页码

#### Scenario: OCR 部分失败
- **WHEN** 多页 PDF 只有部分页面 OCR 失败
- **THEN** 系统索引成功页面，失败页面保留页码、错误状态和 warning，任务标记为 degraded

### Requirement: OCR 结果必须可追溯

系统 SHALL 保存 OCR 是否启用、判定依据、处理状态、页码范围、图片来源和解析 warning，并禁止写入无法追溯来源的 OCR 文本。

#### Scenario: OCR 成功
- **WHEN** OCR 返回有效文本
- **THEN** 系统继续生成标题、段落、表格等结构块，并保留页码和来源信息

#### Scenario: OCR 无有效文本
- **WHEN** OCR 成功响应但所有页面仍为空或不可读
- **THEN** 系统记录 scanned_content_unavailable，并按质量策略隔离该内容
