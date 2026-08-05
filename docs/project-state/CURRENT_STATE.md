# 当前项目状态（CURRENT STATE）

> 生成日期：2026-08-05 · 由 Phase 3 收尾后更新

## 当前 HEAD

```
c398e58 fix: validator rule 12 allows downgrade path without candidates
```

> HEAD 字段 = Phase 3 代码基线（末个代码/测试提交）。其后仅状态文档维护
> 提交（03c43d4、8cd5267 等 docs: 同步/收尾），不改变代码基线，故不更新本字段。

提交链（Phase 3，13 个 Commit）：

```
c398e58 fix: validator rule 12 allows downgrade path without candidates
03c43d4 docs: close phase 3 and update project state
1c680ee test: add abnormal move golden and failure coverage
efbae2b feat: expose abnormal move cli and hermes skill
5f0d097 feat: add attribution synthesis report and validation
916241e feat: connect structured llm client and model routing
594bcff feat: implement cause candidate generation and scoring
213f823 feat: add layered event retrieval and causal timing checks
c39fcc1 feat: implement benchmark selection and peer linkage
3180765 feat: implement deterministic abnormal move detection
1823798 feat: add market data import manifest and phase 3 migration
2126b2c feat: add abnormal move contracts and models
aabdfe5 docs/registry: clarify realtime vs daily market data contracts
298e4c6 docs: add project state documents（Phase 2 收尾）
```

## Phase 0—3 状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0（骨架与契约） | **PASS** | 目录结构、Schema、Pydantic 模型、SQLite+迁移、抽象接口、Orchestrator、CLI、运行目录、Front Matter 校验、测试 |
| Phase 0.1（控制面加固） | **PASS** | 契约说明文档、CLI UUID 边界、失败状态持久化、结构化 JSONL 错误日志 |
| Phase 1（来源探测与数据底座） | **PASS** | 来源注册表、探测框架、5 适配器、主备路由、健康检查 |
| Phase 1.1（行情契约修正） | **PASS** | 实时快照与历史日线严格分离 |
| Phase 2（信息筛选系统与每日晨报） | **PASS** | 晨报流水线、四方向覆盖、19 Schema、CLI morning-brief、Skill、Cron 文档、黄金测试集 |
| **Phase 3（异动分析）** | **PASS** | 见下方 Phase 3 交付清单 |

**Phase 4（个股研报）尚未开始**（见 NEXT_PHASE.md）。

## Phase 3 交付清单（2026-08-05 验收）

- 11 个新 Schema（30 个总数）：market_daily_series_manifest / market_minute_bar /
  abnormal_move_request / anomaly_metric / abnormal_move_observation /
  benchmark_candidate / benchmark_selection / cause_candidate /
  cause_evidence_link / attribution_result / abnormal_move_run
- 迁移 004（user_version=4）：12 张新表（含 llm_call_records），
  abnormal_move_runs(idempotency_key+run_version) 唯一约束
- 人工日线导入：`research market-data import-daily`（CSV/Parquet、质量检查：
  日期/重复键/OHLC/负值/停牌缺口/交易日；dry-run 零副作用；rejected 行不写正式表；
  复权口径单一；Manifest checksum+data_version 进幂等键）
- 确定性异动检测：收益率/robust Z（MAD=0 回退平均秩分位）/severity 0-5 表/
  量额振幅波动/连续涨跌/Beta 调整残差（Winsorize）/特殊状态（停复牌/新股/ST/
  涨跌停/除权/未收盘 provisional）/综合成立规则 A/B/C
- 基准选择：市场基准注册表（按板块）+ 七维评分 + 防事后选择
  （pre_window>=45、概念 valid_from<=窗口开始）+ 降级链
- 板块联动：广度/中位/横截面分位/特异性（7.10），样本门槛 行业10/概念8
- 分层事件检索（四层）+ 时间因果（BEFORE/DURING/AFTER/UNKNOWN_ORDER，
  事后报道不得 direct、旧闻无新增不得重标、同日无分钟 medium 上限）
- 原因候选七维评分（权重固定）+ 惩罚表 + 直接证据门槛 + 主次/多原因划分
- 统一 LLM Client：LlmRequest/LlmResponse、五步校验链、Flash 两次修复后升级
  一次 Pro、provider 故障与业务升级分离、未配置诚实回退（llm_called=false）、
  llm_call_records 落库
- 归因合成状态机（EXPLAINED/MULTI_CAUSE/UNEXPLAINED_MOVE/INSUFFICIENT_EVIDENCE/
  SOURCE_CONFLICT/DATA_DEGRADED，UNEXPLAINED_MOVE 合法输出）
- 18 章节 Markdown 报告 + 33 条跨对象 Validator
- CLI：`research run abnormal-move`（--entity/--industry/--concept 三选一、
  退出码 0/2/3/4/5、幂等/force/dry-run、无 traceback）
- Hermes Skill：skills/finance/abnormal-move-analysis/SKILL.md
- 黄金测试集：14 案例（可归因/易错归因/无法归因/数据不足/边界五大类）

## 测试数量

```
551 passed in ~16s（0 failed, 0 skipped）   全部离线
```

命令：`python -m pytest -ra --tb=short`（在项目根，venv 内）

## Schema、迁移版本和 CLI

### Schema（30 个，`schemas/`）

Phase 0（9）+ Phase 1（4）+ Phase 1.1（2）+ Phase 2（4）+ Phase 3（11）。
校验：`research validate`（全部 30 个通过）；所有对象须通过 Schema（additionalProperties:false），模型 extra="forbid"。

### SQLite 迁移

`PRAGMA user_version` = **4**

- 001_initial.sql：Phase 0 核心 10 表
- 002_sources.sql：来源层（source_probes/source_health/data_routes/manual_inbox）
- 003_market.sql：行情契约分离（market_realtime_snapshots / market_daily_ohlcv）
- 004_abnormal_move.sql：Phase 3（manifests/import_rows/requests/observations/
  metrics/candidates/selections/causes/links/attributions/runs/llm_call_records）

### CLI（`research`）

| 命令 | 说明 |
|---|---|
| `run [--task-id/--scenario/--entity/--depth/--as-of/--force]` | 空任务：生成 Task/Plan/Run 目录；幂等 |
| `run morning-brief [--date/--as-of/--depth/--force/--dry-run/--live]` | 晨报流水线（默认离线 manual_inbox） |
| `run abnormal-move --entity 600519.SH [--date/--depth/--force/--dry-run/--peer/...]` | 异动分析流水线（个股/行业/概念） |
| `market-data import-daily --file ... [--adjustment/--calendar/--dry-run]` | 人工日线导入 |
| `validate` | 校验全部 Schema / 报告 |
| `probe-sources [--all/--source/--group/--output/--no-write]` | 来源探测（真实 HTTP，curl 引擎） |
| `health [--source]` | 来源健康检查 |
| `inbox add/list/status` | 人工 Inbox |

## 已验证来源

| source_id | 类型 | 探测结果 | 适配器 |
|---|---|---|---|
| cninfo 巨潮 | 法定披露 | HTTP 200 JSON API（字段实测） | ✅ 正式适配器（S 级） |
| sse / szse / csrc | 披露/监管 | HTTP 200（部分静态确认） | 无（watchlist/candidate） |
| nbs 统计局 | 政府统计 | HTTP 200 列表页可提取 | ✅ 元数据适配器（S 级） |
| cls 财联社 | 快讯 | HTTP 200 title/content 确认 | ✅ B 级元数据适配器 |
| sina_quote 新浪 | 行情 | HTTP 200（需 Referer） | ✅ 实时快照适配器（仅快照，非日线） |
| manual_inbox | 人工 | — | ✅ 人工服务 |

## 异动分析运行方式

```powershell
cd C:\Users\Administrator\Desktop\投研工作台\ai-investment-research
.\.venv\Scripts\research.exe market-data import-daily --file daily.csv --adjustment qfq --dry-run  # 先预览
.\.venv\Scripts\research.exe market-data import-daily --file daily.csv --adjustment qfq             # 正式导入
.\.venv\Scripts\research.exe run abnormal-move --entity 600519.SH --date YYYY-MM-DD --name 贵州茅台
.\.venv\Scripts\research.exe run abnormal-move --industry "industry:白酒" --peer 600519.SH --peer 000858.SZ
.\.venv\Scripts\research.exe run abnormal-move --entity 600519.SH --dry-run
```

输出：`reports/abnormal_moves/YYYY/YYYY-MM/YYYY-MM-DD_<entity>_abnormal_move.md`
+ `reports/runs/<task_id>/`（15 件套产物：request/observation/metrics/benchmark/
retrieved/causes/links/contradictions/attribution/model_route/validation/errors.log 等）。

## 实际未接入真实 LLM Provider

- 统一 LLM Client 已实现并通过 Fake Provider 全链路测试（校验/修复/升级/降级）
- 未配置真实 Provider 时报告 Front Matter 如实记录
  `model_route: {mode: deterministic_fallback, llm_called: false}`
- V4 Pro 升级条件已定义并实现，待真实 Provider 客户端接入后生效

## 当前工作区状态

```
git status: clean
分支: master
安装: 普通 pip 安装（非 editable，Windows 中文路径 + GBK locale 约束）
Python: venv 3.11.15（uv 托管）；系统 3.12.10
包名: research-os 0.1.0
```
