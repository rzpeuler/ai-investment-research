# Hermes Cron：每日晨报（A股）

本文档说明如何用 Hermes Cron 调度每日晨报生成（建议 08:10 Asia/Shanghai）。
不依赖常开 Gateway：本机计划任务负责生成，输出落在项目目录。

## 0. 前置

- 项目路径：`C:\Users\Administrator\Desktop\投研工作台\ai-investment-research`
- CLI：`<项目根>\.venv\Scripts\research.exe run morning-brief`
- 报告输出：`<项目根>\reports\morning\YYYY\YYYY-MM\YYYY-MM-DD_morning.md`

## 1. 创建任务

```text
hermes cron create --name morning-brief-daily \
  --schedule "10 8 * * *" \
  --command "cd C:\Users\Administrator\Desktop\投研工作台\ai-investment-research && .\.venv\Scripts\research.exe run morning-brief" \
  --workdir "C:\Users\Administrator\Desktop\投研工作台\ai-investment-research" \
  --provider deepseek \
  --model deepseek-v4-flash \
  --deliver telegram
```

必须配置：

- `workdir`：项目根（绝对路径）；
- `provider` / `model`：固定为 deepseek / deepseek-v4-flash，**Cron Agent 运行时不得自行更改模型**；
- 输出位置：项目 `reports/morning/`；
- 任务名称：`morning-brief-daily`。

## 2. 查看任务

```text
hermes cron list
hermes cron show morning-brief-daily
```

## 3. 手动触发

```text
hermes cron run morning-brief-daily
```

等价于手动执行：

```powershell
cd "C:\Users\Administrator\Desktop\投研工作台\ai-investment-research"
.\.venv\Scripts\research.exe run morning-brief
```

## 4. 暂停与恢复

```text
hermes cron pause morning-brief-daily
hermes cron resume morning-brief-daily
```

## 5. 删除

```text
hermes cron delete morning-brief-daily
```

## 6. 补跑（电脑关机错过 08:10）

晨报流水线支持延迟补跑：**窗口固定为前一日 20:00 至当日 08:00**，
运行时间晚于 08:10 时报告自动标记 `delayed: true` 与 `delay_seconds`。

手动补跑命令（当天任意时间）：

```powershell
.\.venv\Scripts\research.exe run morning-brief --date <YYYY-MM-DD>
```

同一窗口已存在通过校验的报告时返回 `IDEMPOTENT`；确需重跑加 `--force`（产生新版本，不覆盖旧报告）。

开机后若 cron 错过，可由 Hermes 会话执行上述命令（Skill：`morning-brief`）。

## 7. 电脑关机后的行为

- 关机期间 cron 不执行（本地计划任务）；
- 开机后**不会自动补跑**（依赖用户或 Hermes 手动触发）；
- 补跑命令见第 6 节；窗口与延迟标记由系统保证正确。

## 8. 未来迁移服务器方式

1. 在服务器安装 Python 3.11+、uv，克隆项目并 `uv sync`；
2. 配置 `.env`（密钥与路径）；
3. 使用 `cron`（Linux）或 Windows 计划任务注册：
   ```bash
   10 8 * * * cd /opt/ai-investment-research && .venv/bin/research run morning-brief
   ```
4. 将 Hermes Cron 改为服务器端调度（`deliver` 指向消息平台），报告路径改为服务器共享目录；
5. 数据库与 `reports/` 迁移（SQLite 文件整体复制即可）。

## 9. 日志与排障

- 运行目录：`reports/runs/<task_id>/`（task.json、candidate_items.json、
  event_clusters.json、scores.json、claims.json、validation.json、errors.log）；
- 校验失败：检查 `validation.json` 的 errors；
- 全部来源无数据：报告仍生成，覆盖章节标注 `manual_only/not_covered`，
  不得写成"该方向没有信息"。
