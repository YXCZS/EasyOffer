## 1. 文件识别与 PDF OCR

- [x] 1.1 增加扩展名、MIME、Magic Bytes 和专业库打开校验，处理冲突、伪造和损坏文件。
- [x] 1.2 实现 PDF 只读预检测：文字密度、空文字页比例、图片信号、乱码和加密状态。
- [x] 1.3 实现扫描 PDF 和混合 PDF 的逐页图像渲染，保存页码、图片序号和来源。
- [x] 1.4 将 MinerU OCR 从固定全局值改为按页面/文档形态动态启用，保留总开关作为回滚。
- [x] 1.5 保存文件类型、PDF 内容形态、OCR 判定、页码状态和 warning 元数据。
- [x] 1.6 增加普通 PDF、扫描 PDF、混合 PDF、加密 PDF、损坏 PDF 和 OCR 失败 pytest。

## 2. Word 和视觉理解

- [x] 2.1 保留 Word 段落、标题层级、列表、表格、页眉页脚和图片的独立来源。
- [x] 2.2 实现 Word 内嵌图片抽取，文字图片走 OCR，图表/流程图走 Qwen-VL。
- [x] 2.3 新增 Qwen-VL 文档视觉客户端，支持超时、重试、有界并发和 JSON schema 校验。
- [x] 2.4 实现 chart/flowchart/高价值技术图片筛选，跳过装饰图片并记录原因。
- [x] 2.5 实现复杂图片表格增强：OCR 文本 + bbox + 图片 + Qwen-VL JSON。
- [x] 2.6 校验表头、行列、合并单元格、关键数字和页码；失败时保留原始结果并标记 degraded。
- [x] 2.7 增加视觉成功、非法 JSON、超时、限流、重复图片和权限继承测试。

## 3. RAG 数据兼容

- [x] 3.1 扩展 ParsedBlock、ParentUnit、ChildChunk 和 Milvus 可选 metadata 字段。
- [x] 3.2 将表格/图表视觉摘要转换为 embedding_text，保留 evidence_text、media_path、bbox 和不确定性。
- [x] 3.3 验证 BM25、RRF、DashScope Rerank 对视觉描述文本的兼容性。
- [x] 3.4 验证 owner、document、corpus、version、license、published/inactive 过滤不会被视觉证据绕过。
- [x] 3.5 建立 OCR、复杂表格、Word 图片、ChartQA 和流程图关系 golden dataset。

## 4. 验证与发布

- [x] 4.1 运行后端全量 pytest，确认知识库、题目生成和报告流程无回归。
- [x] 4.2 运行前端 typecheck 和微信小程序构建，确认页面行为不变。
- [x] 4.3 记录 OCR 非空页比例、视觉 JSON 合法率、表格校验通过率、检索命中、耗时、Token 和费用。
- [x] 4.4 使用 feature flag 小流量启用视觉分析，准备关闭开关和兼容回滚步骤。
- [ ] 4.5 人工核对普通 PDF、扫描 PDF、混合 PDF、含图片 Word、文字截图、复杂表格、图表和流程图端到端结果。（待提供真实样本并在微信/后台环境完成目视核验）
