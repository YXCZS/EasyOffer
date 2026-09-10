# EasyOffer RAG 全流程与当前实现说明

## 0. 文档目的与边界

这份文档汇总本轮关于 EasyOffer RAG 的全部关键问题，并严格以当前仓库源码、配置、测试和运行态检查为准。

文中使用三种表述：

- **当前实现**：源码已经具备，且可以通过测试或运行态检查验证。
- **当前配置**：代码支持，但是否启用取决于 `.env` 或运行环境。
- **未实现/后续方向**：讨论过、文档提过或行业常见，但当前代码没有接入。

EasyOffer 的目标不是做通用知识问答，而是为程序员技术面试刷题提供可信的题目生成和评估依据。因此 RAG 的核心目标是：

1. 把文档中的技术知识加工成可检索、可追溯的证据；
2. 先尽可能召回相关内容，再提高排序准确率；
3. 知识库没有可靠证据时，不强行让本地内容回答；
4. 对新知识或用户给出的网页，使用 Tavily 获取较新的外部证据；
5. 把证据、来源和结构上下文交给 DeepSeek 生成面试题。

---

## 1. RAG 在本项目中的完整链路

### 1.1 离线知识库构建

```text
文件/网页
  -> MinerU 解析
  -> MinerU 结构块统一化
  -> 文本清洗与异常标记
  -> 标题层级和章节路径识别
  -> Parent 构建
  -> Child 切分
  -> 精确去重和近重复去重
  -> Embedding
  -> 写入 Milvus
  -> 审核、评测、发布
```

### 1.2 在线题目生成

```text
用户输入主题、岗位、难度
  -> Agentic RAG 策略路由
  -> Milvus 本地知识检索 / Tavily Search / Tavily Extract
  -> 宽召回
  -> BM25 + Dense 的 RRF 融合
  -> DashScope 或 Cohere 二阶段精排
  -> Child 命中后恢复 Parent
  -> 证据和来源注入 DeepSeek Prompt
  -> 生成面试题
```

普通已登录用户的技术主题不会直接无条件走基础模型，而是优先尝试获取证据；本地证据不足时允许转 Tavily。游客路径按策略限制为基础模型，以控制成本和权限范围。

---

## 2. 为什么要把 MinerU 节点转换成统一结构

### 2.1 MinerU 解决什么问题

普通 PDF 文本提取往往只能得到一长段字符串，标题、表格、代码、公式、图片说明和页码关系会丢失。MinerU 可以识别复杂版面，并输出结构化 JSON、Markdown 以及图片等资源。

当前代码优先读取 `paper_content_list_v2.json`，兼容旧版 `paper_content_list.json`。解析结果会保留：

- 节点类型：`heading`、`paragraph`、`list`、`code`、`table`、`formula`、`image`、`chart`、`reference`；
- 页码和起止页；
- 标题层级；
- `section_path` 章节路径；
- 节点路径；
- bbox 坐标；
- 图片或媒体路径；
- MinerU 原始元数据；
- 结构置信度。

### 2.2 `MinerUStructuredBlock` 的动因

不同版本 MinerU 的 JSON 字段可能变化，且本地 PDF/DOCX fallback 的输出格式不同。系统把它们统一转换为 `MinerUStructuredBlock`，是为了给后续清洗、Parent 构建、切分和入库提供稳定的数据契约。

这不是行业强制标准名称，而是项目内部的适配层模型。它的价值是：

1. 上游解析器可以替换，后续流水线不用跟着改；
2. 特殊结构不会在读取 Markdown 时退化成普通文本；
3. 页码、坐标、章节和来源可以一路传递到检索结果；
4. 测试可以对统一结构做确定性断言。

### 2.3 图片目前的实际处理

MinerU 下载的图片资源会保存到 artifact 目录，结构块保留图片路径、说明和可提取文本。启用 `DOCUMENT_VISUAL_ENABLED` 后，系统会筛选高价值技术图片，并使用 DashScope Qwen-VL 对图片、图表、流程图和复杂表格进行结构化视觉理解；输出的描述、关系和表格信息会转换为 `embedding_text`，继续进入现有 BM25、Dense、RRF 和 Rerank 文本检索链路。

当前实现不是对图片像素直接生成多模态向量：Milvus 中保存的仍是视觉模型输出文本的 Embedding。图片原生视觉 Embedding 和图文联合向量检索仍属于未实现能力。

### 2.4 安全处理

MinerU 返回 ZIP 时，系统会检查压缩包内路径，拒绝绝对路径和包含 `..` 的路径，避免 Zip Slip；原始 ZIP、结构化 JSON 和图片资源会持久化，便于审计和问题复现。

### 2.5 解析失败时的 fallback

配置 `MINERU_API_TOKEN` 后，PDF、DOCX、PPT、PPTX、XLS、XLSX、HTML 和图片会优先调用 MinerU。MinerU 不可用时：

- PDF 使用 `pypdf` 本地提取；
- DOCX 使用 `docx2txt` 本地提取；
- 其他 MinerU 专属格式没有本地等价 fallback，会返回解析失败。

fallback 会记录 warning，不会伪装成 MinerU 成功。

---

## 3. 数据清洗：做了什么，为什么做

清洗的原则是“去除格式噪声，不改写技术语义”。当前 `clean_text` 做以下处理：

1. 统一 `CRLF`/`CR` 为 `LF`；
2. 删除控制字符；
3. 合并连续空格和 Tab；
4. 清除行首行尾多余空白；
5. 将过多空行压缩为最多一个空段；
6. 检测常见乱码标记，如 `锟斤拷`、`ï¿½`、`Ã`、`Â`，只记录 warning，不擅自猜测原文；
7. 对 PDF 页面边缘行做重复统计。

### 3.1 重复页眉页脚去除

当 PDF 至少有 3 页时，系统统计每页第一行和最后一行。如果某行在至少 60% 页面重复，且长度少于 120 字符，就作为可能的页眉/页脚移除，并记录 `repeated_headers_or_footers_removed`。

MinerU 的 `header`、`footer`、`page_header`、`page_footer`、`page_number`、`page_footnote` 节点也会被过滤。原始解析产物仍然保留，便于追溯。

### 3.2 清洗没有做什么

当前没有使用大模型改写全文，没有做自动同义词改写，也没有把乱码强行恢复成猜测文本。原因是清洗阶段应尽量确定性，避免把原始技术事实改坏。

---

## 4. 结构感知：标题、章节和 Parent

### 4.1 `section_path`

标题不会单独作为普通知识块参与检索，而是维护层级上下文。例如：

```text
# RAG
## 向量检索
### Milvus
```

正文会继承：

```text
section_path = ["RAG", "向量检索", "Milvus"]
```

Embedding 文本还会携带技术名、标题、章节路径和结构类型，例如：

```text
技术：RAG
标题：Milvus
章节：RAG > 向量检索 > Milvus
Structure type: paragraph
正文：...
```

这样做是为了避免正文脱离章节语义。标题作为上下文是项目设计选择，不是某个官方强制标准。

### 4.2 Parent 是什么

Parent 是适合生成答案或题目的较完整知识单元。每个 Parent 记录：

- `parent_id`；
- `parent_type`；
- 标题和章节路径；
- 正文；
- 页码；
- bbox；
- MinerU 节点路径；
- 结构元数据；
- 内容哈希；
- 结构置信度。

标题本身通常不独立生成 Parent，避免检索到只有标题没有解释的空证据。

### 4.3 特殊结构 Parent

表格、代码、公式、图片、图表、列表和引用不会全部退化成普通段落，而是保留对应的 `parent_type`。这样后续可以采用不同切分规则，也能在生成题目时告诉模型证据属于什么结构。

### 4.4 问答识别和跨页合并

普通文本会依据问题编号、`Q` 格式、面试问法词、问号以及“答案/解析”等标记，识别为 `qa`、`question`、`section` 或 `paragraph`。对于跨页的问答内容，系统会尝试把下一页的答案延续合并到前一个问题 Parent。

### 4.5 DeepSeek 边界分类器

代码中存在 `DeepSeekBoundaryClassifier`，它的职责是返回边界偏移并校验覆盖范围。但 `boundary_classifier_enabled` 默认是 `False`，正常知识库构建流程不会调用它。因此当前切分不是大模型语义切分。

---

## 5. 切分策略：Recursive、结构感知和重叠

### 5.1 `RecursiveCharacterTextSplitter` 是什么

`RecursiveCharacterTextSplitter` 是 LangChain 提供的递归字符切分器。它会按一组分隔符从粗到细尝试切分：先尝试段落，再尝试换行、标点、空格，最后才退化到字符级，以尽量保留自然边界。

它属于“规则驱动切分”，不是语义模型切分。虽然分隔符优先级体现了一点文本结构，但它不会计算向量相似度，也不会理解两个句子是否发生了语义跳变。

### 5.2 当前普通文本参数

当前默认配置：

- Child 大小：850 字符左右；
- Child overlap：100 字符；
- 保留 `start_index`；
- 分隔符优先级：空段、换行、中文句号/感叹号/问号、分号、逗号、空格、空字符串。

配置文件中的通用知识库参数为 `knowledge_chunk_size=900`、`knowledge_chunk_overlap=120`；公共语料流水线的 `CorpusConfig` 默认值为 850/100。实际运行时以调用该流水线的配置对象为准，不能把两个配置误认为同一个固定值。

### 5.3 特殊结构切分

| Parent 类型 | 当前处理方式 |
| --- | --- |
| `formula`、`image`、`chart` | 保持单个 Child |
| `table` | 按表格行分组，尽量保留表头和 `<table>` 包裹 |
| `code`、`list`、`reference` | 按行切分，并使用 overlap |
| 普通段落、章节 | `RecursiveCharacterTextSplitter` |

### 5.4 是否有 overlap

有。相邻 Child 会保留一部分重叠内容，避免一个概念刚好被切在两个块的边界上，导致单个块缺少前文定义或后文结论。

### 5.5 是否“小块检索，大块生成”

有。Milvus 中检索的是 Child 的 `embedding_text`；命中后通过 `parent_id` 查询同一 Parent 的全部 Child，并拼接恢复较完整的 Parent 文本，再交给 Agent/DeepSeek。这样检索粒度较细，生成上下文较完整。

### 5.6 当前切割思路属于哪一类

准确分类如下：

```text
结构感知（MinerU 节点、标题、表格、代码等）
    + 规则驱动（RecursiveCharacterTextSplitter、按行、按表格行）
    + 检索增强（Child 召回，Parent 恢复）
```

当前不是：

- 默认语义驱动切分；
- 智能体动态决定每个文档如何切分。

---

## 6. 去重策略：精确重复和近重复

### 6.1 保留谁

去重前按 `authority_priority`、文档顺序、Child 顺序和 chunk id 排序，优先保留权威级别更高、顺序更稳定的内容。

### 6.2 SHA-256 精确去重

普通文本会转小写并去除非中文、英文和数字字符，再计算 SHA-256。相同规范化内容产生相同哈希，后出现的块被记录为 `exact` duplicate。

代码、公式和表格只规范化空白，不删除标点，避免把 `a+b` 和 `ab` 错误合并。

### 6.3 SimHash 近重复去重

普通文本还会：

1. 生成连续 5 字符窗口；
2. 使用 64 位 BLAKE2b 指纹；
3. 按高位建立桶；
4. 在同桶内计算汉明距离；
5. 默认距离小于等于 3 时判定为 `near` duplicate。

代码、公式和表格跳过近重复判断，因为少量字符变化可能就是语义或语法变化。

### 6.4 去重的边界

当前去重是内容级确定性去重，不是语义等价判断。它不会判断两段不同表述是否“意思相同”，也不会用 LLM 做合并。

---

## 7. Embedding 和 Milvus 存储

### 7.1 Embedding

当前配置使用 DashScope 兼容 API 的 `text-embedding-v4`，Embedding 文本不是只有正文，还会加入技术、标题、章节和结构类型，以增强上下文检索。

### 7.2 Milvus

Milvus 是项目唯一的向量数据库；项目已移除 Chroma 路径。当前本机运行态是 Milvus Standalone `2.5.16`。

公共知识库和用户私有知识库使用不同 collection/作用域。公共检索会按发布状态、语料版本和岗位标签过滤；私有检索会强制 owner/document scope，避免用户读到别人的文档。

### 7.3 Milvus Standalone 原生混合检索

生产集合使用 Milvus 原生 BM25 Function：`text` 字段经 analyzer 生成 `sparse` 字段，并与 dense `vector` 在服务端执行 hybrid search 和显式 RRF。旧 Lite 数据（如存在）只作为迁移备份，不参与线上检索。

---

## 8. 检索策略：先召回，再精排

你提出的“先召回，追求广度；再 rerank，追求精准”是当前主流 RAG 检索结构，本项目已经按这个思想实现。

### 8.1 Dense 召回

用户 Query 经过 Embedding 后，在 Milvus 中做向量相似度召回。公共检索会 over-fetch，默认 `milvus_dense_recall_k=50`，而不是一开始只取最终的 5 条，避免目标证据被相邻主题占满。

### 8.2 原生 BM25 关键词召回

BM25 是基于词频、逆文档频率和文档长度的关键词检索算法，适合版本号、类名、配置项、缩写和精确技术名。

当前实现使用 Milvus Standalone 的 BM25 analyzer：

- 英文和技术标识符尽量保持完整，如 `HashMap`、`Spring Boot`、配置名；
- 中文使用单字和二元组，降低中文没有空格分词造成的漏召回；
- 修复 MinerU 常见断词，如 `HashM ap`、`M ilvus`；
- 稀疏倒排索引由 Milvus 管理，检索时不把全量语料拉回应用进程。

### 8.3 RRF 融合

Dense 分数和 BM25 分数不在同一量纲，不能直接相加。当前使用标准 Reciprocal Rank Fusion：

```text
RRF score = Σ 1 / (k + rank)
```

默认 `k=60`。RRF 只使用各路结果的排名，因此不需要对两种分数做危险的人工归一化。结果元数据会保留 `dense_rank`、`bm25_rank` 和 `rrf_score`。

### 8.4 二阶段 Rerank

融合后的宽候选集再进入二阶段精排。当前支持：

- DashScope `TextReRank`，默认模型 `gte-rerank-v2`；
- Cohere Rerank，作为可选 provider。

精排只处理有限候选，不让 Cross-Encoder 或远程 API 扫描整个知识库。当前默认精排结果上限为 8，并有 `milvus_rerank_min_score` 最低分门槛。

如果没有对应 API Key、调用失败、超时或返回为空，系统降级保留 RRF 顺序；如果全部结果低于最低分，则返回空证据，避免把相邻主题冒充答案。

### 8.5 Parent 恢复

检索结果首先是 Child。系统使用 `parent_id`、document/version/corpus version 查询父级 Child 集合，按 Child 顺序拼接成 Parent 文本，同时保留来源、页码、章节和 URL 元数据。

### 8.6 目前还没有做的精排策略

当前没有接入本地 BGE Cross-Encoder、Jina Reranker，也没有使用 LLM 对候选逐条重写排序。这些属于可选后续优化，不是当前默认链路。

---

## 9. Agentic RAG：AI 如何决定走 Milvus 还是 Tavily

### 9.1 为什么不能只靠固定词表

技术概念会持续更新，固定词表无法覆盖新框架、新工具和新术语。比如 `Harness Engineering` 不在本地知识库时，单靠旧模型或词表容易误判成其他领域概念。

### 9.2 当前路由结构

项目使用 LangGraph StateGraph 和 DeepSeek 路由控制器。Agent 不直接拥有无限制执行权，而是：

1. 根据登录状态、用户 id、文档 id、是否 URL、岗位和难度构造 `PolicyEnvelope`；
2. 只把策略允许的工具暴露给路由模型；
3. 模型每次只选择一个下一步工具；
4. 图节点统一执行工具、记录超时和调用次数；
5. 对模型输出做 Pydantic 校验，禁止越权工具；
6. 模型不可用时使用确定性 fallback 路由。

### 9.3 当前工具

- `public_milvus_search`：检索已发布的公共面试知识；
- `personal_milvus_search`：只检索当前用户私有知识库；
- `tavily_search`：根据关键词获取当前网络结果；
- `tavily_extract`：对用户输入的 `http(s)` URL 提取完整页面内容。

### 9.4 实际路由规则

| 场景 | 当前允许路径 |
| --- | --- |
| 游客 | 基础模型 |
| 用户指定私有文档或知识库闯关 | 私有 Milvus + 基础模型兜底 |
| 输入是 URL | Tavily Extract + 基础模型兜底 |
| 普通已登录技术主题 | 查询扩展、公共 Milvus、Tavily Search；复杂主题可用 Tavily Extract |

普通已登录主题的确定性 fallback 会优先公共知识库，再 Tavily Search；如果已有网页证据，再尝试 Tavily Extract。模型可以在策略允许范围内调整顺序，但不能把普通已登录主题静默改成纯基础模型。

### 9.5 证据不足时怎么办

本地 Milvus 低分或没有证据时，精排门槛会拒绝不相关结果，Agent 再尝试 Tavily。Tavily 失败时捕获异常、记录日志，并允许系统使用没有网络证据的原有 Prompt 继续生成，保证降级可用。

---

## 10. 证据如何进入题目生成

题目生成不是把 Milvus 原始对象直接塞给模型，而是整理为带来源信息的证据 payload。每条证据至少包含：

- 文本；
- source type；
- source id/name/url；
- parent id；
- 文档版本和语料版本；
- 技术名、岗位标签、章节路径；
- 检索分数或版本适配信息。

DeepSeek Prompt 会要求围绕用户岗位、难度和主题出程序员面试题，并优先使用证据中的事实。这样可以减少模型脱离资料自由发挥；但当前没有独立的 LLM-as-a-Judge 在每次生成后自动判定事实忠实度。

### 10.1 质量是否会因为逐题生成下降

当前项目的增量出题和一次性出题是不同的调用流程。逐题生成可以缩短首题等待，但每道题都要独立调用模型和检索。为尽量保持原质量，系统沿用相同的主题、岗位、难度和证据约束，并对生成任务做状态记录和失败降级。

不过，“逐题生成与一次性生成质量完全相同”目前没有经过完整统计评测，不能写成已证明结论。

---

## 11. 为什么会出现相邻主题误召回

RAG 常见错误主要发生在两个节点：检索失败和生成失败。

在检索侧，可能出现：

1. Dense 向量理解了技术大类，但没有识别用户的细分意图；
2. Top-K 太小，相邻主题占满候选；
3. 中文或 OCR 断词导致 BM25 没有命中；
4. Parent 恢复扩大上下文，但不会自动修正最初的主题偏差；
5. 单个高分邻题让整体 confidence 被高估。

当前已采取的措施是：公共 over-fetch、中文 BM25、断词归一化、RRF、二阶段 rerank、最低分门槛、Parent 恢复和 Golden Set 回归评测。

仍然存在的限制是：当前没有把技术名和细分知识点做独立的强过滤字段，也没有完整的意图级 LLM 评审。因此 benchmark 之外的所有主题不能承诺绝对准确。

---

## 12. 当前评测体系：已经有什么

### 12.1 Golden Set 离线检索回归

当前已经实现的是“基于 Golden Set 的离线检索回归评测”，不是行业正式术语“确定性评测”。每条样本包含：

- 用户问题；
- 岗位；
- 难度；
- 期望技术；
- 期望知识点；
- 相关 Parent/document/source identity 及相关性等级。

Benchmark 通过 YAML 版本化，使用 Pydantic 校验。

### 12.2 当前指标

- `Hit@5`：前 5 条是否至少命中一个相关结果；
- `MRR@5`：第一个相关结果出现得有多靠前；
- `nDCG@5`：综合相关性等级和排序质量；
- 知识点覆盖率；
- 重复结果率；
- 岗位污染率；
- 来源可追溯率；
- Parent 恢复率；
- `answer_integrity_rate`；
- P50/P95 延迟。

其中 `answer_integrity` 是规则检查：文本长度、Parent 是否恢复、是否存在来源，以及问答块是否有答案段。它不能等同于 Faithfulness。

### 12.3 发布门禁

当前默认门禁包括：

- Hit@5 >= 0.85；
- MRR@5 >= 0.70；
- nDCG@5 >= 0.75；
- 岗位污染率 <= 0.05；
- 重复率 <= 0.10；
- Parent 恢复率、来源可追溯率、答案完整性均 >= 1.0。

评测结果会写入运行目录，并可通过 CLI 的 `evaluate` 和 `compare` 比较候选版本与当前版本。

### 12.4 当前真实 smoke benchmark

当前公共集合约 1,284 个已发布 chunk，本地 Milvus Lite 抽查结果如下：

| Pipeline | Hit@1 | Hit@3 | Hit@5 | Content coverage | 未知主题拒绝 | P50 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense only | 0.67 | 0.67 | 0.67 | 0.75 | 0% | 1.31s | 1.32s |
| Dense + BM25 + RRF | 0.83 | 0.83 | 0.83 | 0.83 | 0% | 1.43s | 1.48s |
| Dense + BM25 + RRF + DashScope | 0.50 | 0.67 | 0.83 | 0.83 | 100% | 1.70s | 1.78s |

该数据是小规模 smoke test，不是统计显著的生成质量结论。它说明混合召回扩大覆盖，精排门槛可以拒绝未被本地知识支持的主题，但不能证明所有问题都准确。

---

## 13. 你提到的 RAGAS 三层评测，当前处于什么状态

行业常见的完整评测可以分为：

### 13.1 检索评测

- Context Precision：召回上下文中有多少是真正相关的；
- Context Recall：标准答案所需信息有多少被召回。

### 13.2 生成评测

- Faithfulness：答案是否被上下文支持，有没有编造；
- Answer Relevancy：答案是否真正回答了问题。

### 13.3 端到端业务评测

例如题目是否覆盖面试知识点、答案分析是否有帮助、用户流程是否成功、耗时和成本是否可接受。

### 13.4 项目当前事实

当前没有接入 RAGAS、DeepEval、TruLens，也没有 Context Precision、Context Recall、Faithfulness、Answer Relevancy 的真实运行结果；没有端到端业务回放评测。当前仅有 Golden Set 检索回归、规则化 answer integrity 和人工 smoke 抽查。

因此面试时应准确表述为：

> 项目已经建立了版本化 Golden Set 的离线检索评测和发布门禁；生成质量的 RAGAS/LLM-as-a-Judge 评测还没有接入，answer_integrity 只是规则校验，不能冒充 Faithfulness。

---

## 14. 评测是否可复现，以及限制

可复现部分：

- YAML benchmark 有版本号；
- 指标计算公式固定；
- InMemory fixture 有单元测试；
- Milvus 检索链路有真实抽查和回归测试；
- 后端完整测试当前通过。

当前限制：

1. benchmark 声明的 embedding model 没有强制校验运行时实际模型；
2. 真实延迟是单次 wall-clock，没有 warm-up、多次重复和置信区间；
3. 评测 artifact 没有完整保存代码 revision、reranker 配置和 Milvus 快照；
4. 标注依赖人工 relevance，尚未自动检查每个标签是否对应真实文档；
5. smoke benchmark 样本量小，不能外推到全部技术主题；
6. 门禁支持 override reason，使用时必须保留审计记录。

---

## 15. 面试中应该如何概括这套方案

可以用下面这段准确描述：

> EasyOffer 采用结构感知的 RAG 流程。离线侧使用 MinerU 解析 PDF、DOCX 等文件，保留标题、表格、代码、公式、页码和坐标等结构信息，统一转换成内部结构块；经过确定性文本清洗后构建 Parent，再按不同结构用 RecursiveCharacterTextSplitter、按行或按表格行生成 Child。普通文本使用 SHA-256 精确去重和 SimHash 近重复去重。在线侧以 Milvus Standalone 做 Dense + 原生 BM25 宽召回，用显式 RRF 融合，随后通过 DashScope TextReRank 二阶段精排，命中 Child 后恢复 Parent。Agentic RAG 根据用户身份、是否 URL、是否私有知识库和当前证据情况，在公共/私有 Milvus、Tavily Search、Tavily Extract 之间做受策略约束的单步路由。当前已经有 Golden Set 离线检索评测和发布门禁，但尚未接入 RAGAS 或 LLM-as-a-Judge，所以不能宣称已经得到 Faithfulness 等生成质量指标。

---

## 16. 成本、性能和复杂度取舍

当前没有把所有流行技术无条件叠加，而是根据 EasyOffer 的中文面试场景和 Milvus Standalone 环境做了取舍：

| 方案 | 优点 | 当前状态 |
| --- | --- | --- |
| 仅 Dense | 延迟和实现成本最低 | 作为对照 benchmark |
| Dense + Milvus 原生 BM25 | 技术名、版本号和中文关键词更容易命中，检索不扫描应用全量语料 | 当前默认 |
| RRF | 不需要把 Dense/BM25 分数硬归一化，融合开销小 | 当前默认 |
| Cross-Encoder/API Rerank | 提高候选排序精度 | DashScope 默认 |
| LLM 逐条重排 | 质量上限高但慢且贵 | 未实现 |

正常在线流程不应该让大模型对整个知识库逐条判断。当前只对几十条宽召回候选做二阶段精排，再把少量证据交给 DeepSeek。这样增加了一次精排调用，但避免了错误 Top1 直接进入生成。

当前 smoke benchmark 中，Dense-only P50 约 1.31 秒，Dense+BM25+RRF 约 1.43 秒，加入 DashScope 精排约 1.70 秒。这个增量是当前样本和环境下的测量，不代表所有网络条件下的固定延迟。

## 17. 这些方法是不是我临时编的，是否有标准

需要区分“行业通用方法”和“项目内部适配”：

- Dense retrieval、BM25、RRF、Cross-Encoder rerank、Parent/Child、overlap 是业界 RAG 常用组件；
- `RecursiveCharacterTextSplitter` 是 LangChain 的通用规则切分器；
- MinerU 结构块到 `MinerUStructuredBlock` 是项目自己的稳定适配模型，不是行业标准名；
- `authority_priority`、SimHash 阈值 3、页眉页脚 60% 阈值、Parent 字段组合是本项目的工程规则；
- Golden Set、Hit/MRR/nDCG、Context Precision/Recall、Faithfulness、Answer Relevancy 是常见评测思想，但当前项目只实现其中的离线检索指标和规则完整性检查。

因此面试时不能说“MinerUStructuredBlock 是标准”，应该说“我们为 MinerU 输出定义了内部统一数据契约”。同理，不能把项目阈值说成行业统一标准，应该说明它们是可配置的初始工程参数，需要通过 benchmark 调优。

## 18. Agent 评测四层与当前覆盖

你提出的 Agent 评测四层可以这样对应项目：

1. **结果层**：当前有检索命中、知识覆盖、Parent 恢复、来源追溯和答案完整性；没有自动判断生成答案是否事实正确。
2. **过程层**：Agentic graph 会记录 route、tool_calls、round、fallback_reason、coverage、confidence 和冲突信息，可检查是否越过策略或过早 finish。
3. **效率层**：当前记录检索 P50/P95，以及 Tavily、精排和 Agent 工具超时；没有完整的 Token 成本统计和跨多次运行的成本报表。
4. **风险层**：PolicyEnvelope 限制游客、私有文档、URL 和公共检索的工具权限；工具调用有预算、超时和 Pydantic 决策校验；Web 内容被视为不可信数据。当前没有独立的红队安全评测套件。

## 19. Tavily 的动态参数与降级

Tavily 不是所有输入都用同一套参数。当前 `tavily_agent.py` 会根据查询长度、难度和 URL 场景选择搜索深度、结果数量、原始内容/提取深度，并对查询做 1 至 3 个有界扩展；结果经过去重和相关性过滤。

- 关键词输入：调用 `tavily_search`，适合发现新术语和当前网页；
- URL 输入：调用 `tavily_extract`，获取页面正文，而不是把 URL 当普通关键词；
- 复杂或困难主题：允许更深搜索或进一步抽取；
- Tavily 失败：捕获异常、记录 `fallback_reason`，不阻塞基础模型生成；
- 用户指定个人知识库：策略禁止公共 Web，避免知识库闯关被外部内容污染。

当前没有“按城市选择搜索范围”功能，也没有把城市参数加入路由。

## 20. 当前实现的最终边界

当前项目可以真实描述为：

```text
MinerU 结构解析
  + 确定性清洗
  + 结构感知 Parent/Child
  + 规则切分与 overlap
  + SHA-256/SimHash 去重
  + Milvus Dense
  + 应用 BM25
  + RRF 融合
  + DashScope/Cohere 二阶段精排
  + Agentic RAG 工具路由
  + Tavily Search/Extract 降级
  + Golden Set 检索回归
```

当前不能描述为：

- 已经接入 RAGAS 全套评测；
- 已经有 Faithfulness、Answer Relevancy 的真实分数；
- 已经使用视觉模型生成图片向量；
- 已经启用语义模型切分或智能体动态切分；
- 仍在使用 Milvus Lite 或应用层 BM25；
- 已经证明逐题生成质量与一次性生成完全相同。

---

## 21. 审核记录

审核日期：2026-09-10。

核对范围：`backend/app/corpus/`、`backend/app/services/`、`backend/app/research/`、`backend/app/core/config.py`、`backend/tests/` 以及 Milvus Standalone 运行态。

验证结果：

```text
python -m pytest -q
全部通过
```

专项测试覆盖 MinerU 结构化解析、切分、去重、Milvus 检索、Agentic RAG 路由和评测模块，也已完成公共知识库主题抽查。

审核结论：当前项目已接入可选文档视觉理解链路和 RAGAS 离线评估，并保留确定性检索评测、题目/报告业务评测与 Agent 四层评测。尚未接入的是图片原生视觉 Embedding、图文联合向量检索和默认语义切分；这些能力不得描述为当前已实现。
