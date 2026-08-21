# P8-B2-R5-A — Harness Generation Controller Implementation

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

## 1. 完成内容

实现 `GenerationControlledProvider`（`src/research_os/llm/providers/
generation_controller.py`）与 `repair.py`（字段级错误提取 + 修复 prompt
构建器），实现有界 generate-validate-repair 循环。

## 2. Controller 架构

```text
LlmClient（唯一 AI 入口，不变）
  ↓
GenerationControlledProvider（provider 包装层，LlmProvider 协议）
  ├─ pass 1: base_provider.complete_json
  ├─ Validation Layer: 既有 LlmOutputValidator（未修改）
  ├─ [字段级错误] → Repair Layer: build_repair_prompt（只修错误字段）
  ├─ repair pass（有界 max_repair_passes=2，计入 provider 调用/token/audit）
  └─ Success（输出通过同一 validator） / repair_exhausted（诚实 fallback）
```

- 状态：`GenerationState`（task_id / attempt / repair_round /
  validation_errors / partial_output / usage / provider_calls）— 进程内、
  不落 DB、不跨任务共享；
- Audit 扩展（向后兼容）：usage 增加 generation_pass / repair_round /
  provider_calls / validation_error_summary；
- 原则：validator 是唯一质量判断来源；repair 不绕过 schema；不伪造字段；
  所有 provider 调用记录在案（无隐藏 retry）。

## 3. Repair 流程

1. pass 1 生成 → validator 校验；
2. 失败 → `extract_field_errors` 分类（missing_required / enum_error /
   value_format / json_format / other）；
3. `build_repair_prompt`：原任务目标 + 当前部分输出 + 字段错误 + 证据；
   明确只修复错误字段、禁止虚构证据引用；
4. repair pass（≤2 轮）→ 同一 validator 终验；
5. 仍失败 → `repair_exhausted`（非重试型）→ LlmClient 诚实 fallback
   （无伪造 MODEL_INFERENCE）。

## 4. 测试结果

- `tests/unit/test_p8_b2_generation_controller.py`（9 个 fake-provider 测试）：
  first-pass success / repair success / repair exhaustion / provider error
  passthrough / 经 LlmClient 无伪造 MODEL_INFERENCE / repair prompt 结构 /
  字段错误分类 / 状态隔离 / 真实注册 validator 路径 — 全过；
- run 内 full pytest **3840 passed / 6 skipped / 1 warning / 0 failed**；
- schema 86/86；compileall PASS；secret scan CLEAN。

## 5. Repair Metrics（benchmark run 32460687556）

| 指标 | 值 |
|---|---|
| repair_success_rate | 0.333（6 个需修复 case 中 2 个经 repair 转 valid） |
| average_repair_rounds | 1.67 |
| added_provider_calls | 10（10 个 live case 累计修复调用） |
| cases_needing_repair | 6 |

## 6. Benchmark 变化（R5-A vs 基线）

| 指标 | R3/R4 基线 | R5-A |
|---|---|---|
| schema_valid_rate | 0.4-0.5（方差带 0.2-0.5） | **0.3**（本 run；方差带内） |
| **missing_required_field** | **3-5 cases** | **0 cases（repair 完全消除）** |
| json_format_failure | 1-5 | 5（属 fallback 类，不在 repair 范围） |
| legacy 对照 | 0.8-0.9 | 0.9 |
| threshold 0.70 | NOT_MET | NOT_MET（如实） |

实证结论：repair loop 对 missing_required_field 类失败**有效**（3-5 → 0，
字段级统计为空）；json_format（无 JSON 输出）类按任务书走诚实 fallback；
整体率仍在运行方差带内（0.2-0.5），0.70 未达 — 本任务不要求达到。

## 7. 修改文件

- src/research_os/llm/providers/generation_controller.py（新增）
- src/research_os/llm/repair.py（新增）
- scripts/run_harness_benchmark.py（controller 接入 + repair metrics）
- tests/unit/test_p8_b2_generation_controller.py（新增）
- .github/workflows/p8-b2-eval-001-benchmark.yml（R5-A 触发；已移除）
- docs/project-state/{CURRENT_STATE,NEXT_PHASE,KNOWN_LIMITATIONS,DECISIONS}.md

## 8. P8-B2 下一步建议

1. Sol 验收 R5-A；
2. R5-B：Harness JSON-mode 结构化输出探测（治理决策）— 针对
   json_format_failure 类（当前主导失败，repair 不覆盖）；
3. R5-D：benchmark 重跑评估（目标 0.70，P8-B3 Benchmark PASS 前置）；
4. P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED。
