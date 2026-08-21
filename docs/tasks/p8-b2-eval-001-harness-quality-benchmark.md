# P8-B2-EVAL-001 — Harness Quality Benchmark

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

## 1. 目标

建立 DeepSeek Harness 质量评估体系，为 P8-B3 Production Adoption 决策提供
客观工程数据。本任务仅建立评估能力，不改变生产运行路径。

## 2. Corpus 定义（初始 13 cases，完全与 LIVE-01 解耦）

`config/harness_benchmark/corpus.yaml`（version 1.0.0）：

| 类别 | 数量 | cases |
|---|---|---|
| Equity tasks | 5 | eq_catalyst_candidates（真实 EquityLlmTasks）/ eq_business_description_normalization / eq_research_questions / eq_earnings_analysis / eq_company_summary |
| Research tasks | 5 | rs_industry_summary / rs_theme_analysis / rs_market_context / rs_research_finding_generation / rs_report_section_generation |
| Failure cases | 3 | fl_invalid_json / fl_timeout / fl_schema_violation（确定性 fixture） |

- **Benchmark Corpus ≠ LIVE-01 Acceptance Corpus**（完全解耦：benchmark case
  不计入 sessions/turns；验证目的不同）。
- 不修改 Schema / Validator / Evidence Contract / Production routing /
  default runtime。

## 3. 指标（runner 输出 reports/harness_benchmark_latest.json）

- Quality：schema_valid_rate / task_success_rate / fallback_rate
- Reliability：retry_count / timeout_count / invalid_response_count / silent_retry
- Cost：provider_calls / token_usage（provider-reported）/ latency p50
- Compatibility：harness_schema_valid_rate vs legacy_schema_valid_rate
  （同 case 直连 provider 对照）

## 4. 阈值（P8-B3 进入条件，治理决策）

| 指标 | 要求 | 首次运行观测 | 状态 |
|---|---|---|---|
| schema_valid_rate | ≥ 0.70 | 0.10 | **NOT_MET** |
| fake MODEL_INFERENCE | 0 | 0 | MET |
| validator bypass | 0 | 0 | MET |
| audit completeness | 100% | 1.0 | MET |
| budget violation | 0 | 0 | MET |
| secret leakage | 0 | 0 | MET |
| silent retry | 0 | 0 | MET |

**Production Adoption 判断规则（治理）**：Benchmark PASS **且** LIVE-01 PASS
**且** 成本评估通过 **且** 人工研究体验确认 → P8-B3 Decision。单项指标
（如 schema_valid_rate）不等于 Production。

## 5. 首次真实 Benchmark 运行结果（2026-08-21，GitHub Actions run 32444324435，head e4fd1e2）

- corpus_size=13，decoupled_from_live01=True，default_runtime=legacy
- **Quality**：schema_valid_rate=0.10（1/10），task_success_rate=0.10，
  fallback_rate=0.90
- **Reliability**：retry_count=0，timeout_count=1，invalid_response_count=6，
  silent_retry=0
- **Cost**：provider_calls=23（10 harness + 10 legacy + 3 failure），
  token_usage=0（fallback 记录不携带 provider_usage — accepted 语义，
  已知限制），latency_p50=26.7s
- **Compatibility**：harness 0.10 vs legacy 0.80（同 10 个 live cases）—
  客观量化：Harness agent 上下文下模型输出与严格 schema 的符合率显著低于
  直连路径
- 成功 case：eq_catalyst_candidates（harness 与 legacy 均 valid）
- Failure cases：3/3 诚实回退（fallback、audit 完整、无伪造）
- 测试：full pytest 3824 passed / 6 skipped / 1 warning；schema 86/86

## 6. P8-B3 建议（首次运行结论）

**暂不建议进入 P8-B3 决策**：schema_valid_rate=0.10 未达 0.70 门槛。评估
体系已建立并产出对比数据（legacy 0.80 vs harness 0.10），差距明确指向
Harness agent 上下文（persona/工具指令）对严格 schema 输出的影响 —
需后续专项（如 prompt 策略 / 输出适配增强）提升后重跑 benchmark，再进入
P8-B3 决策流程。

## 7. 测试

`tests/unit/test_p8_b2_harness_benchmark.py`（10 个离线测试）：corpus 结构 /
解耦性 / 任务注册 / failure 语义（invalid_json / timeout / schema_violation
诚实回退）/ audit 记录 / 阈值常量 / 报告路径 gitignore。加既有 P8-B2 测试全绿。

## 8. 状态

- P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`；不写 `P8-B2 ACCEPTED`。
- Benchmark 不计入 LIVE-01 acceptance corpus；未改任何冻结边界。
