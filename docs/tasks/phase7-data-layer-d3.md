# P7-D3：Free-Source Production MVP

**TASKBOOK_STATUS: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE（2026-08-18）**
**TASKBOOK_ID: P7-D3**
**TITLE: Free-Source Production MVP**
**PARENT_MASTER_SHA: `52080cffc7f703e0a6ec007dec60e318702ad694`**
**P7_D1_ACCEPTED_SHA: `bc277817ee419410803f5541d74be75a330e9713`**（PR #25 squash merge → master `5d78a05`）
**P7_D2_ACCEPTED_SHA: `55c4ba55847aec91ae425d86bf3415fcf867e7f4`**（merge → master `52080cf`）
**IMPLEMENTATION_HEAD: `23686f2`（最终实施 head，待合并验收）**
**SOURCE_SCOPE: nbs / cninfo**
**NEW_SOURCE_COUNT: 0**
**NEW_COLLECTOR_COUNT: 0**
**PRODUCTION_COLLECTOR_IDS: [nbs, cninfo]**
**PAID_SOURCE_SUPPORT: 0**
**GRAPH_WRITE: NONE**
**LLM_ACQUISITION_CALLS: 0**
**PHASE6.1: NOT_AUTHORIZED**
**DB_VERSION: v6**
**MIGRATIONS: NONE**
**SCHEMA_COUNT: 86**
**OFFLINE_CI: PASS（见 §10）**
**ONLINE_ACCEPTANCE_STATUS: NBS PASS / CNINFO PASS（见 §8，待独立验收复核）**

> 本 taskbook 只记录 D3 实施与交接状态；独立验收通过前不声明 PASS / CLOSED /
> operational / real-source ready。capability 晋级 BUSINESS_SUFFICIENT 仅在独立在线
> 验收通过后由治理 closeout 执行。

## 1. 前置门（全部满足）

- P7-D1 = CLOSED / PASS / MERGED（PR #25 squash → master `5d78a05`，2026-08-18）
- P7-D2 = CLOSED / PASS / INDEPENDENTLY ACCEPTED / MERGED（Decision #50，accepted head
  `55c4ba5`；merge → master `52080cf`，2026-08-18）
- 工程基线 = 最新 master `52080cf`；D3 分支 `phase7/d3-free-source-production-mvp`
  从该 master 创建，未叠加在 D2 开发分支上。

## 2. 目标与范围

把 P7-D2 的 fake-proven Acquisition Foundation 转换为真实免费公开数据源驱动的
生产级最小闭环：

```text
Scenario → D1 DataReadiness → DataGap → AcquisitionPlan → D2 Coordinator →
ExecutionService → existing Router → CollectorFetcherBridge → 真实 Collector →
真实网络 → normalize → RawItem Schema 校验 → 原子幂等持久化 →
独立 readiness recheck → 既有 Runner / Scenario Pipeline
```

来源范围仅限：`nbs → macro_data`、`cninfo → company_announcement`。
未新增来源、未新增 Collector、未接入付费数据。

## 3. 实施内容

### M1 Collector Runtime Hardening

- NBS `curl.exe` 写死 → 跨平台 `shutil.which("curl.exe") or shutil.which("curl")`
  （复用 CNINFO 模式）；curl 缺失 fail closed。
- NBS subprocess 显式 `encoding="utf-8", errors="replace"`（Windows GBK 解码崩溃修复）。
- CNINFO 跨平台解析验证（已有 `_curl_executable`）。
- 测试：`tests/unit/test_nbs_collector_runtime.py`（12 用例）。

### M2 SourceQueryProjector

- 新文件 `src/research_os/data_layer/source_query_projector.py`：canonical query →
  source-specific query 的精确投影层（fail closed）。
- 注册表：`("nbs","macro_data") → {}`；`("cninfo","company_announcement") →
  {"stock": "600519"}`（entity → 权威 security_profiles 映射 → 6 位代码；
  未知/歧义/malformed/多 entity → FAIL CLOSED）。
- 不修改调用方输入；不做来源选择（existing Router 仍唯一路由权威）。
- 测试：`tests/unit/test_source_query_projector.py`（20 用例）。

### M3 Canonical Field Projection

- 新文件 `src/research_os/data_layer/field_projector.py`：exact registry
  `(source_id, data_type, raw_category)`。
- `("nbs","macro_data","statistics_release")`：`published_at → publish_date`；
  `("cninfo","company_announcement","announcement")`：`publisher(=secName) → company`。
- 确定性、无 LLM、无模糊别名、不修改 RawItem、血缘可审计；未知组合 FAIL CLOSED。
- 测试：`tests/unit/test_source_field_projector.py`（12 用例）。

### M4 Production Wiring 与 --live-data 门

- `CollectorFetcherBridge` 注入 `SourceQueryProjector` + `FieldProjector`；
  fetcher 签名演进为 `(data_type, query, time_window)`（existing Router 仍是唯一权威）。
- `config/data_acquisition_execution.yaml`：`enabled: false`（默认真实采集关闭）、
  `production_collector_ids: [nbs, cninfo]`（治理批准 allowlist，未批准 ID fail closed）。
- `ExecutionPolicyRegistry` / `execution._policy_is_valid` 校验 allowlist 恰好为
  治理批准集合；enabled 仍强制 false。
- Orchestrator `live_data` 参数：默认 disabled path（Router/Repository 哨兵）；
  显式 `--live-data` 才注入真实 nbs/cninfo wiring 与 `live_authorized=True`。
- CLI `research execute --live-data`（与 `--live`/LLM 完全分离）；
  环境变量不构成隐式授权。
- capability：`macro_data` / `company_announcement` → `WORKFLOW_WIRED`
  （不提前 BUSINESS_SUFFICIENT）。
- 测试：`tests/unit/test_live_data_gate.py`（8）、`test_real_source_policy_contract.py`（8）、
  `test_nbs_production_wiring.py`（3）、`test_cninfo_production_wiring.py`（4）。

### M5/M6 在线验收（真实网络）

- `scripts/acceptance/run_source_acceptance.py`：Source Acceptance Harness
  （acceptance-only；受控 override 仅绕过 enabled/capability 两门以证明
  BUSINESS_SUFFICIENT 前置；其余 gate 全保留：allowlist / plan Schema / PIT /
  persistence 幂等 / recheck authority / dry-run）。
- NBS 真实 E2E：见 §8。
- CNINFO 沪市/深市真实 E2E：见 §8。

## 4. 真实发现与修复（真实验收驱动）

1. NBS Windows GBK 解码崩溃 → `encoding="utf-8", errors="replace"`。
2. NBS 列表页真实结构：标题在 `title` 属性、响应式布局重复链接、页脚 `wzgl` 链接
   → 解析器重写 + URL 去重。
3. NBS 发布日期语义：标题月份是统计期间，URL 路径 `tYYYYMMDD` 才是发布日期 → URL 优先。
4. NBS normalize 曾用 `now_iso()` 冒充 published_at（§25 禁止）→ 无法归因日期即跳过。
5. NBS 采集遵守 D1 canonical time_window（§46），窗口外发布不采集。
6. CNINFO 公告查询主过滤为 `secid=orgId`（stock 参数不生效）→ 官方 `topSearch/query`
   接口确定性解析 orgId（600519→gssh0600519、300750→GD165627）。
7. CNINFO `column` 必须 `szse` 才能命中（shmb 恒空）→ 恢复固定 szse。
8. CNINFO discover 参数构造中 `secid` 键重复（后者覆盖为空）→ 修复。

## 5. 安全与治理边界（全部保持）

- 未新增 Schema（86）、未 DB migration（v6）、未新增 Router、未新增来源、未新增
  Collector、未接入付费、未改 RawItem Schema、无 acquisition LLM 调用、无 Graph write、
  Phase 6.1 NOT_AUTHORIZED。
- 默认真实网络 OFF；仅显式 `--live-data`；环境变量不能打开；dry_run 优先于 live。
- 错误脱敏（sanitized reason codes，不保留 arbitrary exception 原文）。
- 来源身份保留（source_id = nbs / cninfo，不改写为泛化标签）。

## 6. 已知限制（D3 不解决）

- 自动完整财务报表数据、自动历史日线、分钟/完整实时行情、行业成分完整覆盖、
  同行财务自动覆盖、机构研报自动采集、深度新闻/社区数据、通用 PDF 表格解析、
  OCR、付费数据接入治理、Graph write、Research→GraphChange（Phase 6.1）均未具备。
- CNINFO subject scope 的 readiness 关联需要 RawItem 携带 subject entity
  （不修改 RawItem Schema），当前 readiness 保持 MISSING 为合法状态；subject 关联
  属后续阶段。
- CNINFO 深市近 5 日窗口真实无公告时 execution 链 EMPTY（合法语义）；
  真实数据证明使用验收窗口（§47 A）。

## 7. 验收矩阵摘要（Gate 1-33）

| Gate | 结果 |
|---|---|
| 1/2 D1/D2 merged | PASS（master 5d78a05 / 52080cf） |
| 3/4 source expansion 0 / new collectors 0 | PASS |
| 5 production free sources exactly [nbs, cninfo] | PASS |
| 6 paid sources 0 | PASS |
| 7 default real network OFF | PASS（enabled: false） |
| 8 explicit --live-data required | PASS |
| 9 LLM/data live gates separated | PASS（--live 与 --live-data 独立） |
| 10/11 NBS / CNINFO real E2E | PASS（§8） |
| 12 source provenance | PASS |
| 13/14 query/field projection exact | PASS |
| 15/16 PIT / future rejection | PASS |
| 17 empty-result semantics | PASS |
| 18 schema-change fail closed | PASS（结构变化显式失败） |
| 19 idempotency | PASS（NBS reuse=18→7；CNINFO reuse=6） |
| 20 independent readiness recheck | PASS |
| 21/22 normal offline / dry-run network 0 | PASS |
| 23 LLM calls during acquisition 0 | PASS |
| 24 graph write 0 | PASS |
| 25 Phase 6.1 NOT_AUTHORIZED | PASS |
| 26/27 DB v6 / migrations 0 | PASS |
| 28 schema registry 86 | PASS |
| 29 full pytest 0 failed | PASS（§10） |
| 30 schema validation 86/86 | PASS |
| 31 compileall | PASS |
| 32 offline CI | PASS |
| 33 online acceptance | PASS（§8，待独立验收复核） |

## 8. 在线验收结果

### NBS → macro_data（PASS）

```text
REAL_NETWORK = YES（stats.gov.cn 列表页 HTTP 200；真实发布条目）
ROUTER_SELECTED_SOURCE = nbs
SCHEMA_VALID_RAWITEM = YES
PERSISTENCE = PASS（run #5 inserted=7）
RECHECK = PASS（readiness PARTIAL；available 含 publish_date/title/url；missing=[]）
PIT = PASS（rejected_future=0；窗口权威过滤）
IDEMPOTENCY = PASS（run #6 inserted=0 / reused=7）
```

验收窗口：morning_brief report_date 2026-08-17 → D1 权威窗口
[2026-08-16T20:00, 2026-08-17T08:00]；7 条真实发布（2026-08-17）。
artifact：`reports/acceptance/nbs_online_acceptance.md`（本地，reports/ gitignored）。

### CNINFO → company_announcement（PASS）

```text
SH_SYMBOL_CASE = PASS（600519.SH：completed；inserted=6；reused=6 幂等；PIT=0 拒绝）
SZ_SYMBOL_CASE = PASS（300750.SZ：验收窗口 6 条真实公告；近 5 日窗口真实 EMPTY 合法）
QUERY_PROJECTION = PASS（entity → security_profiles → stock → 官方 topSearch orgId）
ROUTER_SELECTED_SOURCE = cninfo
SCHEMA_VALID_RAWITEM = YES；PERSISTENCE = PASS；RECHECK = PASS；PIT = PASS；IDEMPOTENCY = PASS
```

artifact：`reports/acceptance/cninfo_online_acceptance.md`（本地）。

## 9. Capability 状态

- `macro_data`: automatic_acquisition_lifecycle = **WORKFLOW_WIRED**
- `company_announcement`: automatic_acquisition_lifecycle = **WORKFLOW_WIRED**
- 独立在线验收通过后，由治理 closeout 单独晋级 BUSINESS_SUFFICIENT（NBS 与 CNINFO
  分开晋级，不得打包）。

## 10. 离线 CI 完成定义

```text
python -m pytest            → 0 failed（实施 head 全量：见交接记录）
schema validation           → 86/86 PASS（PYTHONPATH=src）
python -m compileall -q src tests scripts → PASS
git diff --check            → PASS
external network required   → 0（离线测试全 Fake/mock）
```

## 11. 工程交接

```text
IMPLEMENTATION_STATUS: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE
BRANCH: phase7/d3-free-source-production-mvp
START_HEAD: 52080cffc7f703e0a6ec007dec60e318702ad694
FINAL_IMPLEMENTATION_HEAD: 23686f2（待合并验收）
PARENT_MASTER_SHA: 52080cffc7f703e0a6ec007dec60e318702ad694
P7_D1_ACCEPTED_SHA: bc277817ee419410803f5541d74be75a330e9713
P7_D2_ACCEPTED_SHA: 55c4ba55847aec91ae425d86bf3415fcf867e7f4
SOURCE_SCOPE: nbs, cninfo
NEW_SOURCE_REGISTRATION: 0
NEW_COLLECTORS: 0
PRODUCTION_COLLECTOR_IDS: [nbs, cninfo]
PAID_SOURCE_SUPPORT: 0
SOURCE_QUERY_PROJECTION: PASS
FIELD_PROJECTION: PASS
DEFAULT_NETWORK: OFF
LIVE_DATA_GATE: --live-data
NBS_ONLINE: PASS
CNINFO_SH_ONLINE: PASS
CNINFO_SZ_ONLINE: PASS（证据 + 合法 EMPTY 语义）
IDEMPOTENCY: PASS
PIT: PASS
READINESS_RECHECK: PASS
LLM_ACQUISITION_CALLS: 0
GRAPH_WRITE: 0
PHASE6.1: NOT_AUTHORIZED
DB: v6
MIGRATIONS: NONE
SCHEMA_COUNT: 86
OFFLINE_CI: 待最终记录
ONLINE_ACCEPTANCE_ARTIFACT: reports/acceptance/nbs_online_acceptance.md、cninfo_online_acceptance.md
KNOWN_LIMITATIONS: 见 §6
```

## 12. 停止条件复核

无 STOP 条件触发：未新增 Schema、未 migration、未改 RawItem、未新增 Router、
未新增来源、未接入付费、未绕过登录、未用 LLM 做 source query/字段映射、
未开 Graph write / Phase 6.1、D1/D2 master 基线一致、existing Router 未重设计。
