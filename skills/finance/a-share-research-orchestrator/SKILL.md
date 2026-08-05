---
name: a-share-research-orchestrator
description: A股投研总控场景。所有研究场景（晨报/异动/个股研报等）的统一入口，负责意图理解、参数标准化、计划生成、模块调度、报告合成与质量校验。
version: 0.1.0
platforms: [windows]
metadata:
  hermes:
    tags: [finance, a-share, research]
    requires_tools: [terminal]
    config:
      - key: research.project_path
        description: 项目绝对路径（含 schemas/ 与 src/）
        default: ""
---

# A股投研总控

## 触发条件

用户提出研究需求且未明确指定具体场景 Skill 时，通过本总控进入：
- 个股研报 / 晨报 / 异动分析 / 首次覆盖 / 复盘 / 行业研究 / 主题挖掘 / 财报预期

## 输入参数

| 参数 | 说明 | 默认 |
|---|---|---|
| scenario | 场景标识（morning_brief / abnormal_move_analysis / stock_research_report 等） | 由意图识别 |
| entities | 实体 ID（如 600519.SH） | 空 |
| depth | fast / standard / deep | standard |

## 执行方式

```powershell
# Phase 0：空任务（生成 Task、Plan、Run 目录）
research run --scenario <scenario> --entity <code> --depth <depth>

# Phase 1+：真实采集与分析由 Orchestrator 按计划调用模块
```

## 结果文件

- 运行记录：`reports/runs/{task_id}/`（task.json / plan.json / retrieval_log.jsonl / module_results/ / evidence_index.json / validation.json / final.md / errors.log）
- 报告：`reports/{morning|evening|stocks|...}/...`

## 失败处理

- 任务失败显式记录于 errors.log 并返回非零退出码。
- 数据不足允许输出 `INSUFFICIENT_EVIDENCE` / `UNEXPLAINED_MOVE` 等状态，禁止编造。

## 验证命令

```powershell
python -m pytest
research validate
```
