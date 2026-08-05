# 当前项目状态（CURRENT STATE）

> 生成日期：2026-08-05 · 由 Phase 2 收尾审计后更新

## 当前 HEAD

```
9f59fbe fix: golden rejection samples to 8, honest model_route, rename deterministic clustering
```

提交链（Phase 2）：

```
9f59fbe fix: golden rejection samples to 8, honest model_route, rename deterministic clustering
781e3df fix: validate morning-brief as-of param at cli boundary
10dda6b docs: update README with phase 1.1 and phase 2 status
3fd9606 test: add morning brief golden and failure coverage
331fabe feat: add hermes morning brief skill and cron docs
6ed78df feat: implement morning brief orchestration
c24e83c feat: implement deduplication, classification and scoring
f84b9ef feat: add morning brief pipeline contracts
67dd572 fix: separate realtime snapshots from daily ohlcv
```

## Phase 0—2 状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0（骨架与契约） | **PASS** | 目录结构、19 Schema 中的 9 个、Pydantic 模型、SQLite+迁移、抽象接口、Orchestrator、CLI、运行目录、Front Matter 校验、测试 |
| Phase 0.1（控制面加固） | **PASS** | 契约说明文档、CLI UUID 边界、失败状态持久化（task.json/DB/validation.json 同步 failed）、结构化 JSONL 错误日志（敏感字段过滤） |
| Phase 1（来源探测与数据底座） | **PASS** | 来源注册表、探测框架、5 个适配器（cninfo/nbs/sina_quote/cls/manual_inbox）、主备路由、健康检查、19 Schema 中的 13 个 |
| Phase 1.1（行情契约修正） | **PASS** | 实时快照与历史日线严格分离 |
| Phase 2（信息筛选系统与每日晨报） | **PASS** | 晨报流水线、四方向覆盖、19 Schema、CLI morning-brief、验证器升级、Skill、Cron 文档、黄金测试集 |

**Phase 3（异动分析）尚未开始**（见 NEXT_PHASE.md）。

## 测试数量

```
343 passed in ~5.2s（0 failed, 0 skipped）   全部离线
```

命令：`python -m pytest -ra --tb=short`（在项目根，venv 内）

## 已有 Schema、迁移版本和 CLI

### Schema（19 个，`schemas/`）

Phase 0（9）：task / entity / raw_item / event / opinion / claim / evidence / module_result / graph_change
Phase 1（4）：source / source_probe / data_route / manual_inbox
Phase 1.1（2）：market_realtime_snapshot / market_daily_ohlcv
Phase 2（4）：candidate_item / event_cluster / information_score / morning_brief_run

校验：`research validate`（全部 19 个通过）；所有对象须通过 Schema（additionalProperties:false），模型 extra="forbid"。

### SQLite 迁移

`PRAGMA user_version` = **3**

- 001_initial.sql：Phase 0 核心 10 表（tasks/entities/raw_items/events/opinions/claims/evidence/module_results/graph_changes 等）
- 002_sources.sql：来源层（source_probes/source_health/data_routes/manual_inbox）
- 003_market.sql：行情契约分离（market_realtime_snapshots / market_daily_ohlcv，日线唯一键 symbol+trade_date）

### CLI（`research`）

| 命令 | 说明 |
|---|---|
| `run [--task-id/--scenario/--entity/--depth/--as-of/--force]` | 空任务：生成 Task/Plan/Run 目录；幂等 |
| `run morning-brief [--date/--as-of/--depth/--force/--dry-run/--live]` | 晨报流水线（默认离线 manual_inbox） |
| `validate` | 校验全部 Schema |
| `probe-sources [--all/--source/--group/--output/--no-write]` | 来源探测（真实 HTTP，curl 引擎） |
| `health [--source]` | 来源健康检查 |
| `inbox add/list/status` | 人工 Inbox（add 支持 --published-at） |

## 已验证来源

| source_id | 类型 | 探测结果 | 适配器 |
|---|---|---|---|
| cninfo 巨潮 | 法定披露 | HTTP 200 JSON API（字段实测） | ✅ 正式适配器（S 级） |
| sse / szse / csrc | 披露/监管 | HTTP 200（部分静态确认） | 无（watchlist/candidate） |
| nbs 统计局 | 政府统计 | HTTP 200 列表页可提取 | ✅ 元数据适配器（S 级） |
| cls 财联社 | 快讯 | HTTP 200 title/content 确认 | ✅ B 级元数据适配器 |
| sina_quote 新浪 | 行情 | HTTP 200（需 Referer） | ✅ 实时快照适配器 |
| manual_inbox | 人工 | — | ✅ 人工服务 |

ima / 雪球等：client_only / watchlist，仅登记不采集。

## 已实现的晨报流水线

```
来源采集（默认 manual_inbox；--live 附加 cninfo/cls）
→ RawItem 标准化 → 时间窗口过滤（前日20:00-当日08:00 Asia/Shanghai）
→ 精确去重（URL规范化+内容指纹+DuplicateGroup 归并）
→ 事件相似聚类（确定性第一版：实体+日期预分桶+标题相似度）
→ 内容分类（四类主分类树）
→ 硬性否决（广告/情绪/标题党/匿名/窗口外等）
→ 信息价值评分（8 维权重合计100/强制纳入/惩罚）
→ 事件簇合并 → Claim 生成（FACT/OPINION/INFERENCE/UNKNOWN/CONFLICT）
→ 晨报选择（75+重大必读/65+正文/55+附录）→ Markdown 渲染 → 报告校验
```

输出：`reports/morning/YYYY/YYYY-MM/YYYY-MM-DD_morning.md` + `reports/runs/<task_id>/`（13 件套产物）。
幂等：同窗口已存在通过校验的报告 → `IDEMPOTENT`；`--force` 产生新版本不覆盖旧报告。

## 实际未接入 LLM

- 模型路由：`model_route: {mode: deterministic_fallback, llm_called: false, intended_default_model: deepseek-v4-flash, limitation: semantic_llm_modules_not_connected}`（报告 Front Matter 如实记录）
- 新颖性/影响路径/预期差评分为**确定性规则近似**；事件聚类为**确定性第一版**（预分桶+相似度），不宣称语义聚类
- V4 Pro 升级条件（高等级冲突/影响链>3跳/Flash 连续校验失败等）已定义，待 LLM 客户端接入后生效

## 当前无历史日线自动源

- `market_daily_ohlcv`：primary=[] secondary=[] fallback=[manual_import]，failure_policy=insufficient_data
- sina_quote 仅用于 `market_realtime_snapshot`（快照不得映射为 close/trade_date）
- 日线只能人工导入（manual_import）

## 当前工作区状态

```
git status: clean
分支: master
安装: 普通 pip 安装（非 editable，Windows 中文路径 + GBK locale 约束）
Python: venv 3.11.15（uv 托管）；系统 3.12.10
包名: research-os 0.1.0
```

## 运行方式

```powershell
cd C:\Users\Administrator\Desktop\投研工作台\ai-investment-research
.\.venv\Scripts\research.exe run morning-brief            # 今天晨报（离线）
.\.venv\Scripts\research.exe run morning-brief --date YYYY-MM-DD --dry-run
.\.venv\Scripts\python.exe -m pytest -ra --tb=short       # 全部测试
```
