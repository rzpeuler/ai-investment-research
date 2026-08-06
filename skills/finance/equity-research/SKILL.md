---
name: equity-research
description: A 股个股深度研报（Phase 4）。用户要求对某只 A 股生成深度研究报告时使用。
  只识别证券代码、构造 CLI 参数、调用标准流水线、返回结果摘要；不自行搜索新闻写研报，
  不复制公式/权重/阈值，不修改 Validator 结果。
version: 1.0.0
---

# 个股深度研报（equity-research）

生成 A 股个股深度研究档案与 Markdown 报告。**研报只能由标准流水线生成**，
本 Skill 只负责构造 CLI 调用并汇报结果。

## 触发条件

- 用户要求"深度研究某只 A 股 / 个股研报 / 基本面研究 / 写一份 XX 的研报"；
- 用户明确提供 6 位证券代码（如 600519.SH / 000858.SZ / 688981.SH）。

不触发：仅询问行情/异动分析（用 abnormal-move）、晨报（用 morning-brief）。

## 执行步骤

1. **识别证券代码**：从用户输入提取 `\d{6}\.(SH|SZ|BJ)`。不允许公司名模糊猜代码；
   无法唯一识别时请用户提供代码。
2. **识别参数**：
   - 深度：fast / standard（默认）/ deep；
   - 截止时间 `--as-of`（用户指定才传）；
   - 是否估值（默认开）、是否情景预测（默认关，需用户明确要求）；
   - 财务文件 `--financial-file`（用户提供的 CSV/JSON/XLSX 路径，可重复）；
   - 文档 `--document`（PDF/HTML，可重复）；同行 `--peer`（可重复，只加入候选）。
3. **构造并调用 CLI**：

```powershell
cd C:\Users\Administrator\Desktop\投研工作台\ai-investment-research
.\\.venv\\Scripts\\research.exe run equity-research --entity 600519.SH `
  [--date YYYY-MM-DD] [--as-of ISO-8601] [--depth standard] [--periods 5] `
  [--financial-file path.csv] [--peer 000858.SZ] [--include-forecast]
```

4. **汇报结果**：报告路径、research_status、财务覆盖、同行状态、估值状态、
   模型路由（deterministic_fallback / llm_called=false）、Validator 状态、数据缺口。

## 禁止

- 自行搜索新闻或阅读 PDF 后直接写研报（必须走 CLI 流水线）；
- 在 Skill 中复制财务公式、同行权重、质量阈值、估值公式；
- 修改 Validator 结果或跳过校验；
- 把 `DATA_DEGRADED` / `UNKNOWN` 改写成基本面判断或"没有"；
- 输出目标价、买卖评级、仓位建议或任何交易建议。

## 退出码解读

| 退出码 | 含义 | 处理 |
|---|---|---|
| 0 | 成功/部分成功/合法降级/幂等跳过 | 正常汇报 |
| 2 | 参数或实体解析错误 | 修正参数重试 |
| 3 | 核心数据不足（缺财务数据） | 请用户提供 --financial-file |
| 4 | Validator 失败 | 报告禁止内容，人工复核 |
| 5 | 内部错误 | 收集 errors.log 上报 |

## 数据缺口说明（如实汇报）

- 无真实 LLM Provider：语义模块确定性回退，`llm_called=false`；
- 无自动财务源：需用户提供 CSV/JSON/XLSX；
- 历史日线仅人工导入；无自动行情来源。
