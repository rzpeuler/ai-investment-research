# P8-B2-INTERNAL-TRIAL-001 — DeepSeek Harness 内部试运行验证

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

## 目标

验证现有 Research OS 场景能否稳定通过 Harness 执行链路运行，为 Production
Adoption 决策形成工程证据。"验证优先，不扩展功能"：不新增 Agent Framework、
不新增场景、不新增模型供应商、不新增第二套 AI 调用入口。

## 审计结论（详见 `docs/architecture/p8-b2-harness-call-path-audit.md`）

- 全仓唯一 AI 执行入口 = `LlmClient`（预算 / 校验 / 降级 / 审计统一层）。
- 默认 provider = DeepSeek Chat Completions 直连（legacy 默认，冻结）。
- 本任务新增 opt-in Harness 入口：`HarnessLlmProvider`
  （`P8_B2_SCENARIO_TRIAL=1`），经统一 LlmClient → Harness 控制面 → provider；
  默认路径不变。
- 绕过清单：无第二套 AI 路径；evening_brief / stock_review /
  industry_research 无 LLM 调用（`llm_called: false`，诚实降级，非绕过）。

## 实施内容

1. `src/research_os/llm/providers/harness.py` — `HarnessLlmProvider`
   （LlmProvider 协议；JSON 提取确定性解析；typed 错误映射；usage 仅
   provider-reported 数值；无 secret 透传）。
2. `src/research_os/llm/provider_factory.py` — `create_provider(..., harness=)`
   opt-in；默认不变。
3. `scripts/p8_b2_scenario_trial.py` — 5 场景验证脚本（first_coverage /
   earnings_expectation 走真实 EquityLlmTasks→Harness→DeepSeek；evening_brief /
   stock_review / industry_research 验证诚实 no-LLM 标记）；有界（≤16 次
   harness-backed 调用）。
4. `tests/unit/test_p8_b2_harness_llm_entry.py` — 14 个离线确定性测试
   （映射 / 失败降级 / budget / audit / 无伪造 MODEL_INFERENCE / secret）。
5. CI workflow `p8-b2-internal-trial-001.yml`（ubuntu-latest，opt-in，secret）。

## 验证结果（2026-08-21，GitHub Actions run 32406895006，head 8a3ed5c）

### 5 场景验证

| 场景 | 结果 |
|---|---|
| first_coverage | EquityLlmTasks 5 任务经统一 LlmClient→Harness→DeepSeek（真实调用 2 次 attempt；共享 flash 预算 2/2 耗尽后其余任务 budget-denied 未调用）；输出未通过严格项目 schema → 诚实 fallback（schema_valid=False，无 MODEL_INFERENCE） |
| earnings_expectation | 3 任务，真实 harness attempt 4 次；同样诚实 fallback 语义 |
| evening_brief | honest no-LLM 标记 PASS（llm_called: false + semantic_llm_modules_not_connected） |
| stock_review | honest no-LLM 标记 PASS（llm_called: false） |
| industry_research | honest no-LLM 标记 PASS（deterministic_fallback, llm_called: False） |

汇总：`status=COMPLETED, harness_attempts=6, audit_rows=8, total_tokens=0`
（0 次 schema-valid 成功 → provider_usage 仅在成功记录中携带，故 token 0 —
provider-reported 语义，无推断），`default_runtime=legacy`。

### 验证结论

1. **Harness 链路真实可用**：场景 LLM 任务经统一 LlmClient → Harness 控制面 →
   DeepSeek 真实执行（有界 6 次 attempt），Harness 进程稳定（无崩溃）。
2. **验证器未被绕过**：Harness 输出一律经真实项目 schema 校验；不合格 →
   诚实回退（无伪造 MODEL_INFERENCE）——本次运行 0 次 schema-valid 成功本身
   证明校验链有效（Production Adoption 风险：Harness 直出格式与严格 schema
   的符合率需提升，否则任务大量回退）。
3. **Budget governance 有效**：flash 共享预算 2/2 上限被尊重；预算耗尽任务
   零 provider 调用。
4. **审计完整**：8 行 llm_call_records（call_id/task_id/module/status/model/
   latency/usage/fallback）；provider 层记录每次 attempt 及状态。
5. **确定性场景诚实**：3 个非 LLM 场景显式 `llm_called: false`。
6. **默认 runtime 保持 legacy**。

### Production Adoption 前风险清单

1. **默认 runtime 未切换**：场景默认仍直连 provider；Harness 路径仅 opt-in。
   Production Adoption 需独立授权（P8-B3）。
2. **Harness 输出 schema 符合率低**：本次验证 0/6 次 attempt 通过严格项目
   schema（诚实回退兜底，但若持续偏低将影响任务成功率）——需评估 prompt/
   输出规范化或 schema 适配。
3. **模型路由粒度**：经 Harness 的调用由 Harness profile 模型执行；
   LlmClient 的 flash/pro 预算语义保留，但 provider 报告的 model_id 为
   `deepseek-harness/<class>`（Harness 响应不暴露实际模型名）。
4. **失败 attempt 的 usage 不入 audit**：LlmClient 只在成功分支记录
   provider_usage（accepted 语义）；失败 attempt 的 token 用量不落 audit。
5. **确定性场景无 LLM**：evening_brief / stock_review / industry_research
   的语义模块未连接；接入属未来 taskbook。
6. **Harness upstream 为 developer preview**（rc.7）；升级需重新验收。
7. **凭证边界**：正式执行仅限 GitHub Actions secret；本地/临时环境禁止。

## 状态

- P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`；不写 `P8-B2 ACCEPTED`。
- 本任务未执行正式 acceptance corpus（场景验证有界、opt-in、非计数）。
