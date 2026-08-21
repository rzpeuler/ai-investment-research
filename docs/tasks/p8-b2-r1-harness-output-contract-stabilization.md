# P8-B2-R1 — Harness Output Contract Stabilization

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

## 1. Problem

P8-B2-INTERNAL-TRIAL-001 验证发现：Harness 真实调用成功后，模型输出经常无法
通过 Sol 严格 schema 校验（schema-valid success = 0/6）→ 全部诚实回退。
瓶颈不是模型调用，而是 Harness 输出契约与 Sol typed research schema 之间
缺少稳定适配层。

## 2. 方案（三层边界，禁止降标准/绕过验证器/直写 Research Object）

```text
Harness Response
      ↓
Deterministic Output Normalizer   ← 本任务新增（纯确定性，无 LLM）
      ↓
Sol Schema Validation             ← 原验证器不变
      ↓
Research Artifact
```

三层边界：

1. **raw harness output**：响应文本中解析出的 JSON 对象（`_extract_json_object`）；
2. **normalized output**：`normalize_harness_output(parsed, schema)` 的确定性映射；
3. **validated artifact**：通过 `LlmClient → LlmOutputValidator`（真实项目 schema）
   的最终结果。

规范化器只做三类确定性变换（`src/research_os/llm/normalization.py`）：

- **unwrap**：顶层键与 schema properties 无交集且恰有一个对象值时，解包
  （处理 `{"result": {...}}` / `{"output": {...}}` 包装）；
- **key conformance**：模型键名大小写不敏感匹配到 schema 精确属性名
  （`CompanyEntityId` → `company_entity_id`）；
- **prune**：删除 schema 未声明的键（符合 `additionalProperties: false`）。

**禁止行为（明确）**：不发明缺失字段、不改动值、不降低 schema 标准。
规范化后仍违反 schema（如必填字段缺失、枚举/格式不符）→ 继续诚实回退。

另：Harness 路径 prompt 指令强化（确定性，属 harness 入口范围）：
"只输出一个 JSON 对象…不要调用任何工具，不要输出 JSON 之外的任何文字" —
直接针对 Harness agent 的叙述/工具调用行为。

## 3. Audit 增强

- 新增 `resolved_model_id`：从 observed composed config（`agent-default-model`）
  解析（deepseek-v4-flash），非猜测；随 provider result 与
  `usage.resolved_model_id` 进入 audit payload。
- `model_id` 保持兼容（`deepseek-harness/<class>`）。

## 4. 验证结果（GitHub Actions run 32440917679，head 5973f05）

**关键指标：schema-valid success = 1 > 0 ✓（R1 gate 达成）**

- `earnings_expectation:catalyst_candidates`：called=True, status=success,
  **schema_valid=True, errs=0**（真实 Harness → DeepSeek → 规范化 → 通过
  严格 catalyst schema）。
- 其余任务诚实回退（无伪造）：
  - research_questions ×2：Harness 响应无 JSON 内容（invalid_response）；
  - business_description_normalization：`company_entity_id: 'UNKNOWN'` 不符合
    `^company:`（值级问题，规范化器不伪造）；
  - 预算耗尽任务（flash 2/2）：零 provider 调用。
- 汇总：harness_attempts=6，audit_rows=8，default_runtime=legacy，
  失败均有有界错误摘要（validation_error_count / first_validation_error）。

**成功率变化**：schema-valid success 0/6 → **1**（真实 Harness 路径首个
通过严格 schema 的 EquityLlmTask）。

## 5. 测试

`tests/unit/test_p8_b2_harness_output_normalization.py`（13 个）：
valid/wrapper/case/extra/missing/malformed/不修改输入/非对象 schema/真实
catalyst schema 通过/缺失字段不被伪造/resolved_model_id 观测非猜测。
加既有 harness entry 14 个 = 27 个离线测试全过；full pytest / schema /
compileall / CI：见验收报告。

## 6. 剩余风险（更新）

1. 默认 runtime 未切换（P8-B3 未授权）——不变。
2. **Harness 输出 schema 符合率（更新）**：规范化层已把 0 提升到 >0（首个
   schema-valid 成功）；但多数任务仍因值级问题（`UNKNOWN` 枚举/格式不符）
   或无语义 JSON 输出而回退 —— 属于模型行为问题，不属适配层缺陷；进一步
   提升需模型/提示策略调整（独立评估）。
3. 模型路由粒度：resolved_model_id 现由 observed profile 提供
   （deepseek-v4-flash）；Harness 响应仍不暴露每调用实际模型。
4. 失败 attempt 的 usage 不入 audit（LlmClient accepted 语义）。
5. 确定性场景（brief/review/industry）语义 LLM 模块未连接。
6. Harness upstream developer preview（rc.7）。

## 7. 状态

- P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`；不写 `P8-B2 ACCEPTED`。
- 未执行正式 acceptance corpus；未降 schema 标准；未绕验证器。
