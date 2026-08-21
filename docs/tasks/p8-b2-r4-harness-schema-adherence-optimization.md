# P8-B2-R4 — Harness Schema Adherence Optimization

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

## 1. 目标

将 schema_valid_rate 从 0.50 提升至 ≥0.70（P8-B3 Benchmark PASS 前置）。

## 2. 实施内容（task-specific contract guidance）

1. **Task Schema Slice**（`build_task_schema_slice` / `describe_schema`）：
   仅含必填字段 + 字段约束 + 合法示例（减少上下文噪音）；优先支持
   research_finding_generation / catalyst_candidates / earnings_analysis。
2. **Required Completion Checklist**：prompt 增加"必填字段完成清单"（输出前
   逐项确认全部存在，禁止缺字段输出）。
3. **Self Validation Instruction**：模型内部自检（JSON 合法 / required 存在 /
   enum 正确），禁止输出自检说明文字。
4. **Benchmark Failure Tracking（field-level）**：runner 捕获全部验证错误，
   聚合 `missing_field_stats`（如 `finding_id missing: 5`）。

**未修改**：Research Schema / Validator / Normalizer / Benchmark threshold /
Production routing。

## 3. 实证迭代（同一 corpus 13 cases，GitHub Actions）

| Prompt 变体 | runs | schema_valid_rate |
|---|---|---|
| R3 结构（完整 schema + 必填约束 + 示例） | R3 原始 / R4 重测 | **0.5 / 0.4** |
| R4 slice-only（移除完整 schema + checklist） | 1 | 0.3 |
| R4 组合（完整 schema + checklist + 自检） | 2 | **0.2 / 0.2** |

**实证结论**：完成清单与自检指令系统性**降低**了符合率（组合 0.2×2，一致）；
slice-only 也低于基线。允许范围内的 prompt 杠杆已达到测量最优（R3 结构
0.4-0.5）。运行间方差显著（0.2-0.5）。

## 4. Benchmark Before/After

- **Before（R3 测量）**：schema_valid_rate = **0.50**
- **After（R4 分支 HEAD，R3 结构重测）**：schema_valid_rate = **0.40**
- R4 新指令（checklist/自检）实测：0.20-0.30（回归，已回退）
- 目标 **≥0.70：未达成**（如实记录）

## 5. 失败字段统计（未达标的必需输出）

最新 run（32454796025，R3 结构）：missing_required_field = 5 cases，
json_format_failure = 1。字段级缺失（每个字段在 5 个 case 中缺失）：

```
as_of, claim_type, company_entity_id, confidence, counter_evidence_ids,
evidence_ids, finding_id, finding_type, invalidation_conditions, materiality,
model_route, object, predicate, request_id, section_id, statement, status,
support_level, supporting_object_ids, title  (各 ×5)
```

系统性模式：模型输出 JSON 对象但**省略 research_finding 的 20 个必填字段**
（finding_id 等）— 不是格式问题，是字段完成度问题；prompt 级指令（清单/
自检/示例）均无法系统性修复。

## 6. 测试与回归

- R4 测试（prompt 结构 / slice / 字段统计）全过；
- 最新 run 内 full pytest **3831 passed / 6 skipped / 1 warning / 0 failed**；
- schema 86/86；compileall PASS；secret scan CLEAN。

## 7. 结论与 P8-B3 建议

**P8-B3：暂不进入**。允许范围内的 prompt/context 优化已达到测量上限
（0.4-0.5）；0.70 目标需要超出本任务范围的杠杆，例如：

1. Harness profile / 模型策略变更（governance 决策，本任务禁止）；
2. Provider 层结构化输出强制（如 response_format json_object — Harness
   控制面内不可控，需架构评估）；
3. Benchmark 多次运行取均值 vs 单次运行判定（测量方法治理）。

这些属于后续独立 taskbook / 治理决策；本任务如实输出未达标结果与失败字段
统计，不伪造、不降标准。

## 8. 状态

- P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`；不写 `P8-B2 ACCEPTED`。
- Schema / Validator / Normalizer / threshold 未变。
