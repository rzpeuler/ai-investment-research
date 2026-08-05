---
name: morning-brief
description: 每日晨报（A股信息筛选系统）。触发词：晨报、早报、今日晨报、morning brief、morning digest。调用 ai-investment-research 项目 CLI 生成，展示降级状态，返回报告路径。
---

# Morning Brief（每日晨报）

## 职责边界

本 Skill **只负责**：

1. 识别晨报需求（"晨报/早报/morning brief"等触发词）；
2. 确认或默认报告日期（默认 Asia/Shanghai 今天）；
3. 调用项目 CLI `research run morning-brief`；
4. 返回报告路径与运行摘要；
5. 展示降级状态（四个监测方向覆盖）；
6. 失败时返回错误摘要。

**禁止**：

- 自行生成绕过项目流水线的晨报（不得直接让 LLM 总结采集结果）；
- 把完整评分规则和分类 Prompt 复制进本 Skill（详见工程指南 13/14 节与项目代码）；
- 输出目标价、买卖建议、仓位建议（项目报告校验器强制拦截）。

## 前置条件

项目绝对路径（必须配置，不允许相对路径）：

```text
C:\Users\Administrator\Desktop\投研工作台\ai-investment-research
```

CLI：`<项目根>\.venv\Scripts\research.exe`（Windows），或激活 venv 后 `research`。

## 调用流程

### 1. 确定报告日期

- 用户给出日期（YYYY-MM-DD）→ 原样使用；
- 用户未给出 → 使用 Asia/Shanghai 今天；
- 补跑：用户说"补昨天的晨报"→ 昨天日期（窗口仍为前一日 20:00 至当日 08:00，延迟标记由系统自动写入）。

### 2. 执行 CLI

```powershell
cd "<项目根>"
.\.venv\Scripts\research.exe run morning-brief --date 2026-08-06
```

可选参数：

- `--force`：同一窗口已存在通过校验的报告时强制重跑（产生新版本，不覆盖旧报告）；
- `--dry-run`：只输出计划（窗口/来源/模块/输出路径），不写任何产物；
- `--live`：发起真实网络采集（默认仅 manual_inbox，离线）；
- `--as-of`：覆盖数据截止时间。

### 3. 解析输出

- `[OK] 晨报 <日期> 生成: <路径>` → 报告路径为 `reports\morning\<年>\<年-月>\<日期>_morning.md`；
- `[IDEMPOTENT]` → 该窗口已有通过校验的晨报，未重复生成；
- `[FAILED]` → 返回错误摘要（含运行目录 `reports\runs\<task_id>\errors.log`）；
- `[INFO] 缺失/降级: ...` → 逐条转述给用户。

### 4. 展示降级状态

报告"六、四个监测方向覆盖"章节状态含义：

- `covered` 已覆盖；`partial` 部分覆盖；`manual_only` 仅人工导入；
- `not_covered` 未覆盖；`source_failure` 来源故障。

**禁止把"没有采集能力"转述成"该方向没有信息"。**

## 幂等与补跑

- 同一窗口（前一日 20:00 至当日 08:00）已有通过校验的晨报 → 默认不重复生成（`IDEMPOTENT`）；
- 补跑必须在 08:10 之后开机时进行，窗口不变，报告标记 `delayed: true`；
- `--force` 重跑产生新版本，不覆盖旧文件。

## 验证

- 报告生成后检查 Front Matter `validator_status`（项目内部校验）；
- 校验失败时返回 `validation.json` 中的错误列表。
