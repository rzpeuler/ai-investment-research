---
name: abnormal-move-analysis
description: A股异动分析（Phase 3）。识别用户查询个股/行业/概念异动原因，构造标准 CLI 参数调用 research run abnormal-move，返回报告路径、归因状态、数据降级与模型路由。禁止自行搜索新闻生成原因或改写 UNEXPLAINED_MOVE。
version: 1.0.0
platforms: [windows]
---

# abnormal-move-analysis（异动分析）

## 触发条件

用户查询以下内容时使用本 Skill：

- 个股：`600519.SH`、`贵州茅台` 今日/某日为什么大涨/大跌/放量
- 行业：`白酒板块`、`光伏行业` 今日异动原因
- 概念：`AI 概念`、`低空经济` 今日异动原因

## 职责边界（任务书 18 节）

本 Skill **只负责**：

1. 识别用户是在查询个股、行业还是概念；
2. 解析或确认日期、深度（fast/standard/deep）和实时选项；
3. 构造标准 CLI 参数；
4. 调用 `research run abnormal-move`；
5. 向用户返回：报告路径、归因状态（attribution_status）、数据降级（missing_data/fallback_status）、模型路由（llm_called）。

本 Skill **禁止**：

- 自己搜索新闻后直接生成异动原因；
- 在 Prompt 中复制评分规则或阈值；
- 绕过标准流水线（不得只凭行情自己下结论）；
- 把 CLI 的 `UNEXPLAINED_MOVE` 结果改写成猜测性原因；
- 输出目标价、评级、仓位或交易建议。

## 工作流

### 1. 识别对象类型

| 用户表述 | 参数 |
|---|---|
| 6 位数字 + .SH/.SZ（600519.SH） | `--entity 600519.SH` |
| 公司名（贵州茅台） | 先映射到代码（如 600519.SH）再 `--entity`；无法确定时要求用户提供代码 |
| 行业（白酒/光伏） | `--industry industry:白酒` |
| 概念（AI/低空经济） | `--concept concept:AI概念` |

### 2. 构造 CLI 命令

```powershell
cd C:\Users\Administrator\Desktop\投研工作台\ai-investment-research
.\.venv\Scripts\research.exe run abnormal-move --entity 600519.SH
.\.venv\Scripts\research.exe run abnormal-move --entity 600519.SH --date 2026-08-05
.\.venv\Scripts\research.exe run abnormal-move --industry "industry:白酒"
.\.venv\Scripts\research.exe run abnormal-move --concept "concept:AI概念" --depth deep
.\.venv\Scripts\research.exe run abnormal-move --entity 600519.SH --dry-run
```

可选参数：`--date YYYY-MM-DD`（默认最近完整收盘交易日）、`--depth fast|standard|deep`、
`--force`（重跑产生新版本，不覆盖旧报告）、`--peer 000858.SZ`（同行，可重复）、
`--name "贵州茅台"`（报告显示名）。

### 3. 解读 CLI 输出

| 输出/退出码 | 含义 | Skill 应做的 |
|---|---|---|
| `[OK] 归因状态=EXPLAINED`（0） | 有主原因 | 读报告摘要给用户 |
| `[OK] 归因状态=UNEXPLAINED_MOVE`（0） | 异动事实成立但无法归因（**合法结果**） | 如实告知，不猜测原因 |
| `[OK] 归因状态=INSUFFICIENT_EVIDENCE`（0） | 证据不足 | 说明缺什么证据 |
| `[DATA_INSUFFICIENT]`（3） | 无日线数据 | 提示先 `research market-data import-daily` |
| `[FAILED] ...Validator...`（4） | 报告未通过校验 | 报告错误，不修改结果 |
| 参数错误（2）/内部错误（5） | — | 如实报告，不伪造 |

### 4. 数据准备（首次使用）

若目标股票无日线数据（提示 DATA_INSUFFICIENT），先人工导入：

```powershell
.\.venv\Scripts\research.exe market-data import-daily --file path\to\daily.csv --adjustment qfq --dry-run   # 先预览
.\.venv\Scripts\research.exe market-data import-daily --file path\to\daily.csv --adjustment qfq              # 正式导入
```

CSV 最低列：`symbol,trade_date,open,high,low,close,volume`。

## 输出约束

- 归因状态、置信度、数据降级、模型路由以报告 Front Matter 为准，不自行推断；
- 报告路径：`reports/abnormal_moves/YYYY/YYYY-MM/YYYY-MM-DD_<entity>_abnormal_move.md`；
- 运行产物：`reports/runs/<task_id>/`（15 件套 JSON + errors.log）；
- 不得输出任何交易建议。
