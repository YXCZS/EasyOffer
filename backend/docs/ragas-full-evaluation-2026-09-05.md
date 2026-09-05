# RAGAS 100 条全量评估工作汇总

日期：2026-09-05  
评估对象：EasyOffer 公共知识库 RAG 主链路  
语料版本：`full-authorized-v1`  
Golden Dataset：`golden-v3`，共 100 条样本

## 1. 本次目标

本次工作是在切换 DashScope 评估模型后，重新执行真实的 100 条 RAG 评估，验证以下内容：

1. 100 条 Golden Dataset 是否全部完成检索和生产生成。
2. RAGAS 四项指标是否能够对 100 条样本完整计算。
3. 评估过程中出现网络超时或单批失败时，是否能够恢复而不丢失已经完成的数据。
4. 评估结果是否绑定到已发布的公共语料版本，而不是未发布或旧版本语料。

## 2. 使用的模型与数据

### 2.1 评估模型

- RAGAS LLM：`qwen3.7-flash`
- Embedding：`text-embedding-v4`
- RAGAS 接口：DashScope OpenAI-compatible API
- 生产出题模型：DeepSeek，未在本次评估中替换

评估模型通过 `RAGAS_LLM_MODEL` 配置，默认值位于：

`backend/app/core/config.py`

示例配置位于：

`backend/.env.example`

### 2.2 评估数据

- 数据集文件：`backend/corpus/benchmarks/golden-v3.yaml`
- 样本数量：100
- 每条样本包含用户问题、岗位方向、难度、参考答案、期望知识点和相关性标注。
- 检索固定使用 `corpus_version=full-authorized-v1`、`status=published`。

## 3. 执行流程

```text
加载 golden-v3
    ↓
按 corpus_version=full-authorized-v1 检索已发布公共语料
    ↓
逐条调用生产出题链路
    ↓
每条样本写入 observations.json / generations.json
    ↓
按 10 条拆分 RAGAS 批次
    ↓
每批计算四项 RAGAS 指标并原子写入 batch-xxx.json
    ↓
汇总 10 个成功批次
    ↓
生成 ragas-summary.json
```

生产检索使用真实 Milvus 公共知识库，生成阶段使用真实 DeepSeek 出题链路，RAGAS 阶段使用 DashScope 的 `qwen3.7-flash` 和 `text-embedding-v4`。

## 4. 防止结果丢失的实现

运行脚本：

`backend/scripts/run_resumable_ragas.py`

### 4.1 逐条 checkpoint

- 每完成一条检索就写入 `observations.json`。
- 每完成一条生成就写入 `generations.json`。
- 写文件时先写入临时文件，再替换正式文件，避免进程中断留下半截 JSON。
- 重新运行时已经成功的样本不会重复调用 DeepSeek。

### 4.2 RAGAS 分批 checkpoint

- 100 条样本拆成 10 个批次，每批 10 条。
- 每个批次单独保存到 `ragas_batches/batch-xxx.json`。
- 批次失败会保留失败记录，便于审计失败原因。
- 只有 `status=success` 且样本数完整的批次才会被跳过。
- 失败批次会在下一次运行时自动删除错误记录并重试。
- 汇总只统计成功完成的批次，不会把失败批次伪装成成功。

这次实际发生过部分批次超时。脚本识别出失败批次后，仅重试失败批次，没有重新生成 100 条题目，也没有重复计算已经成功的 RAGAS 批次。

## 5. 实际执行结果

### 5.1 生成阶段

- 检索样本：`100/100`
- 生成样本：`100/100`
- 生成失败：`0`

结果文件：

`backend/data/public-corpus/evaluations/golden-v3-resumable/generations.json`

### 5.2 RAGAS 阶段

- 批次数量：`10/10`
- 成功批次：`10`
- 评估样本：`100/100`
- 失败样本：`0`
- 最终状态：`success`

### 5.3 指标结果

| 指标 | 得分 |
|---|---:|
| Context Precision | 0.9435555555 |
| Context Recall | 0.9716386946 |
| Faithfulness | 0.9498805596 |
| Answer Relevancy | 0.8145040917 |

结果文件：

`backend/data/public-corpus/evaluations/golden-v3-resumable/ragas-summary.json`

分批结果目录：

`backend/data/public-corpus/evaluations/golden-v3-resumable/ragas_batches/`

## 6. 本次代码改动

### 配置与模型

- 增加独立的 `ragas_llm_model` 配置，避免评估模型和生产 DeepSeek 模型耦合。
- 将 RAGAS 默认模型切换为 `qwen3.7-flash`。
- `build_dashscope_components()` 从配置读取评估模型和 Embedding 模型。
- 增加模型配置和 RAGAS 组件构建测试。

### 可靠性与可恢复性

- 增加 `golden-v3` 数据集重建脚本。
- 增加可恢复的全量评估脚本。
- 修复失败批次被错误跳过的问题。
- 只有完整成功批次才会参与最终汇总。

### 文档

- 更新 RAG 评估开发流程文档中的评估模型说明。
- 新增本文档，记录本次真实执行过程、故障处理和最终结果。

## 7. 验证情况

本次完成以下验证：

- 后端完整测试：全部通过。
- RAGAS 专项测试：全部通过。
- Python 编译检查：通过。
- 100 条生成结果完整性检查：通过。
- 10 个 RAGAS 批次状态检查：全部为 `success`。
- 100 条样本四项指标完整性检查：通过。
- 未读取、提交或输出 `.env` 中的真实密钥。

## 8. 当前结论

本次 100 条真实 RAGAS 全量评估已经完整完成，最终不是部分结果，也没有使用伪造分数。评估结果绑定到已发布的 `full-authorized-v1` 公共语料，评估模型为免费额度的 `qwen3.7-flash`，结果和中间 checkpoint 均已保存在本地评估目录中。
