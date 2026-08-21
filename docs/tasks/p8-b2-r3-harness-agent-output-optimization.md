# P8-B2-R3 — Harness Agent Output Optimization

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

## 1. 目标

将 Harness schema-valid rate 从 0.10 提升至 ≥0.30（阶段目标；P8-B3 最终
门槛仍为 0.70）。

## 2. Harness 失败模式分析（基于 EVAL-001 artifact 精确归类）

| 失败模式 | 数量（9/10 失败） | 表现 |
|---|---|---|
| json_format_failure（无 JSON 内容） | 5 | `invalid_response: Harness 响应缺少有效 JSON content`（模型输出叙述/无 JSON） |
| missing_required_field（缺必填字段） | 4 | `<root>: 'finding_id' is a required property`（research_finding 20 个必填字段缺失） |
| enum / value format | 0 | 本批未出现（此前 R1 观测过 `'UNKNOWN'` 等值级问题） |

结论：问题集中在 **Harness Agent Output Layer** — 模型在 agent 上下文下
不遵循 JSON-only 约束、且省略 schema 必填字段；LlmClient / Validator /
Normalizer / Schema 均非根因。

## 3. 优化方案（Schema-aware Context Injection，已实施）

`src/research_os/llm/schema_context.py`（确定性、纯函数）：

- **JSON-only 指令强化**：只输出 JSON 对象；禁止 Markdown / 工具 / 解释文字；
- **必填字段清单**：显式列出 schema 全部 required properties；
- **字段约束摘要**：每个必填字段的 type / enum / pattern / format / minimum
  约束；
- **完整合法示例**：由 schema 约束确定性生成的占位示例对象（仅作结构参考，
  禁止照抄值 — 内容必须基于证据生成）；
- **任务上下文 + 证据**：任务名与证据片段注入 prompt。

`HarnessLlmProvider.complete_json` 改用 `build_harness_prompt(...)`。
**未修改**：Research Schema / Validator / Normalizer 规则 / Benchmark
threshold / Production runtime；示例仅作为 prompt 上下文，不伪造模型输出。

## 4. Failure Classification（benchmark 增强）

runner 新增分类：json_format_failure / missing_required_field /
enum_violation / value_format_violation / other（逐 case + 汇总），用于衡量
优化效果。

## 5. Benchmark Before/After（同 corpus 13 cases，GitHub Actions）

| 指标 | Before（EVAL-001 run 32444324435） | After（R3 run 32447199752） |
|---|---|---|
| **schema_valid_rate** | **0.10**（1/10） | **0.50**（5/10） |
| task_success_rate | 0.10 | 0.50 |
| fallback_rate | 0.90 | 0.50 |
| legacy 对照 | 0.80 | 0.90 |
| 失败分类（harness） | — | json_format 1 / missing_required 4 / enum 0 / value_format 0 |
| 其他阈值 | — | fake MODEL_INFERENCE=0 / validator bypass=0 / audit 100% / budget 0 / secret 0 / silent retry 0（全 MET） |

After 有效 cases：eq_catalyst_candidates、eq_earnings_analysis、
rs_theme_analysis、rs_research_finding_generation、rs_report_section_generation。

**阶段目标 ≥0.30 → 达成（0.50）**；P8-B3 门槛 0.70 → 仍未达（如实记录）。

## 6. 测试与回归

- 新增 `tests/unit/test_p8_b2_r3_output_optimization.py`（6 个）：
  required 清单 / 约束摘要 / 示例 schema-valid 且确定性 / prompt 结构 /
  用户请求与证据保留 / 失败分类 9 类；
- 既有 P8-B2 测试全过；run 内 full pytest **3830 passed / 6 skipped /
  1 warning / 0 failed**；schema 86/86；compileall PASS。

## 7. 结论与下一步

- 阶段目标达成：schema-valid rate 0.10 → 0.50（5 倍提升）。
- 剩余差距：4 个 missing_required_field（research_finding 必填字段仍被
  省略）+ 1 个 json_format — 需下一轮优化（如必填字段更强制/示例与输出
  对齐强化）后重跑 benchmark，目标 P8-B3 门槛 0.70。
- **P8-B3 建议：暂不进入**（0.50 < 0.70；判断规则 = Benchmark PASS +
  LIVE-01 PASS + 成本评估 + 人工体验确认）。

## 8. 状态

- P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`；不写 `P8-B2 ACCEPTED`。
- Schema / Validator / Normalizer 规则未变；benchmark threshold 未变。
