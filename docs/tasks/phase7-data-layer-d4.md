# P7-D4：CNINFO Official Filing → Core Financial Facts MVP

**TASKBOOK_STATUS: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE（2026-08-18）**
**TASKBOOK_ID: P7-D4**
**IMPLEMENTATION_GATE: P7-D3 = PASS / INDEPENDENTLY_ACCEPTED / MERGED（master 921fe95）**
**PARENT_MASTER_SHA: `921fe95`（含 P7-D3 验收合并）**
**P7_D3_ACCEPTED_SHA: `e8a4a9f`**
**SOURCE_SCOPE: cninfo only**
**DATA_TYPE_SCOPE: company_document / financial_statement_data**
**DOCUMENT_SCOPE: annual_report only**
**FINANCIAL_SCOPE: consolidated / audited / CORE_FINANCIAL_CODES（9 码）**
**NEW_SOURCE_REGISTRATION: 0**
**NEW_COLLECTORS: 0**
**PAID_SOURCE_SUPPORT: 0**
**OCR: NOT_AUTHORIZED**
**LLM_FINANCIAL_EXTRACTION: 0**
**GRAPH_WRITE: NONE**
**PHASE6.1: NOT_AUTHORIZED**
**DB_VERSION: v6**
**MIGRATIONS: NONE**
**SCHEMA_FILE_COUNT: 86**
**NEW_SCHEMA_FILES: 0**

## 1. 前置门（满足）

- P7-D1/P7-D2/P7-D3 = PASS / MERGED（master `921fe95`，2026-08-18）
- 分支 `phase7/d4-cninfo-financial-extraction-mvp` 从新 master 建立

## 2. 实施内容

### M1 company_document 采集链
- `documents/disclosure_materializer.py`：`TransientDisclosureMaterializer`（方案 B）
  - CNINFO 年报 → `download_official_document`（复用全部安全校验）+ PDF magic header /
    Content-Type / HTML 拒绝 / zero-byte / checksum before parsing
  - transient temp PDF → pypdf 原生文本解析 → 删除 temp（不永久保存完整 PDF）
  - DocumentRecord（storage_policy=metadata_and_excerpt, local_path=null）/
    DocumentBlock / Evidence 幂等持久化（UUID5：sha256+company+period+type）
  - 幂等：同 checksum/company/period/type → reuse
- pypdf 转正式 project dependency（pyproject.toml）；缺失 → CONTROL_PLANE_CONFIGURATION_ERROR

### M2 derive_existing（首次正式实现）
- `data_layer/derivation.py`：
  - `DerivationPrerequisiteResolver`（§19 的 11 项证明；ZERO NETWORK / ZERO WRITE）
  - `FinancialDerivationService`（DocumentRecord+Blocks → FinancialDataManifest/Report/Facts，
    原子 upsert，UUID5 幂等）
  - `FinancialDerivationExecutor`（execution 协议适配，subject 唯一性）
- `execution.py`：`derive_existing` action 分支（未注入 executor → DERIVATION_FAILED fail closed）；
  dependencies 强制（前置 step 未 completed → DERIVATION_PREREQUISITE_MISSING，含 early-rejection 路径）
- `planning.py`：`AcquisitionPlanner(derivation_prerequisites)` 生成 dependencies
  （financial_statement_data ← company_document）

### M3 FinancialStatementExtractor
- `financials/disclosure_extractor.py`：deterministic 三表提取
  - 仅 CORE_FINANCIAL_CODES / consolidated / audited annual report
  - exact taxonomy lookup 才自动接受；fuzzy 只产生 warning
  - current-period 列由列标题 authority 证明 + 资产负债表恒等式交叉校验（失败整表 reject）
  - currency/unit 必须可证明；Decimal 字符串（normalize_decimal_string）
  - 任何不确定 → reject（诊断进 manifest.validation_errors）

### M4 Schema 契约演化（backward-compatible，86 保持）
- `AcquisitionExecutionStepResult` 增加 optional `produced_record_refs` / `reused_record_refs`
  （格式 `document_record:<id>` / `financial_report:<id>` / `financial_fact:<id>`）
- reason code 枚举增加：DOCUMENT_DOWNLOAD_FAILED / DOCUMENT_TYPE_INVALID /
  DOCUMENT_PARSE_FAILED / DOCUMENT_NATIVE_TEXT_UNAVAILABLE /
  DERIVATION_PREREQUISITE_MISSING / DERIVATION_FAILED / DERIVED_RECORD_SCHEMA_INVALID
- 旧 artifact 不含新字段仍合法（optional）

### M5 离线测试
- `tests/unit/test_financial_disclosure_extractor.py`（11）
- `tests/unit/test_document_materializer.py`（11）
- `tests/unit/test_financial_derivation_prerequisite.py`（12）
- `tests/unit/test_derive_existing_execution.py`（7）
- `tests/integration/test_financial_derivation_pipeline.py`（2：materialize→derive→recheck 完整链 + PIT）
- 全部离线（synthetic PDF/fixture/mock 下载）

### M6 在线验收 harness
- `scripts/acceptance/run_d4_financial_acceptance.py`（acceptance-only；--live-data 门）

## 3. 真实发现与修复（离线/实现驱动）

1. `FinancialFact.raw_value` 走 decimal 校验 → 千分位逗号确定性去除后再规范化。
2. 资产负债表恒等式校验可证明 current-period 列选择（不成立整表 reject，禁止猜测）。
3. extractor section 边界：每个三表 section 止于下一 section（修复跨表行归属）。
4. capability：company_document / financial_statement_data → WORKFLOW_WIRED
   （deterministic_derivation 保守保持 false，独立验收后 closeout 才允许 true）。

## 4. 安全与治理边界（全部保持）

- 未新增 Schema（86）、未 DB migration（v6）、未新增 Router、未新增 source、未新增
  Collector、未接付费、未改 RawItem、无 LLM 财务提取、无 OCR、无 Graph write、
  Phase 6.1 NOT_AUTHORIZED；PDF 只 transient（不永久保存完整 PDF）。
- `--live-data` 显式门；dry-run 零网络零落盘（沿用 D3 惰性 db + close 特判）。

## 5. 已知限制（D4 不解决）

- financial_segment_data / peer_financial_data / quarterly / interim extraction：NOT AUTOMATED
- 扫描件 PDF / OCR：NOT SUPPORTED；无原生文本 → DOCUMENT_NATIVE_TEXT_UNAVAILABLE
- 历史日线 / 实时行情 / 付费数据 / Graph / Phase 6.1：NONE / NOT_AUTHORIZED

## 6. 工程交接（待独立验收复核）

```text
IMPLEMENTATION_STATUS: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE
SOURCE_SCOPE: cninfo
NEW_SOURCE_REGISTRATION: 0
NEW_COLLECTORS: 0
DATA_TYPES: company_document / financial_statement_data
DOCUMENT_SCOPE: annual_report
PERMANENT_FULL_PDF_STORAGE: 0
PYPDF_RUNTIME: PASS（正式依赖）
COMPANY_DOCUMENT_WORKFLOW: PASS（离线；在线待验收）
DERIVE_EXISTING: PASS（离线；在线待验收）
FINANCIAL_PREREQUISITE_RESOLVER: PASS
FINANCIAL_EXTRACTION: PASS（离线；在线待验收）
600519_ONLINE / 300750_ONLINE / MANUAL_NUMERIC_SPOT_CHECK: NOT_RUN（待 --live-data 在线验收）
PIT: PASS（离线；valid_from=published_at）
IDEMPOTENCY: PASS（离线；UUID5 幂等）
READINESS_RECHECK: PASS（DataPreflight 权威重算）
LLM_FINANCIAL_EXTRACTION: 0
OCR: 0
GRAPH_WRITE: 0
PHASE6.1: NOT_AUTHORIZED
PAID_SOURCE: 0
DB: v6
MIGRATIONS: NONE
SCHEMA_COUNT: 86
NEW_SCHEMA_FILES: 0
PYTEST / SCHEMA_VALIDATION / COMPILEALL / OFFLINE_CI: 待最终记录
ONLINE_ACCEPTANCE: NOT_RUN（独立验收者执行）
```
