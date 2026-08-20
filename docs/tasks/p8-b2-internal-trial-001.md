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

## 验证结果（见验收报告）

- 5 场景验证：equity 场景真实 Harness 调用成功、schema 校验保持、审计记录完整；
  确定性场景诚实 no-LLM。
- Failure/degradation：provider timeout → typed retryable；invalid JSON →
  invalid_response；schema invalid → 诚实回退（无 MODEL_INFERENCE）；
  budget 耗尽 → 跳过不调用。
- 全量 pytest / schema 86/86 / compileall：见验收报告。

## Production Adoption 前风险清单

1. **默认 runtime 未切换**：场景默认仍直连 provider；Harness 路径仅 opt-in。
   Production Adoption 需独立授权（P8-B3）。
2. **模型路由粒度**：经 Harness 的调用由 Harness profile 模型执行；
   LlmClient 的 flash/pro 预算语义保留，但 provider 报告的 model_id 为
   `deepseek-harness/<class>`（Harness 响应不暴露实际模型名）。
3. **预算**：1M token 上限（BUDGET-DECISION-01）下 20-turn corpus 可完成；
   实际用量以正式 trial evidence 为准。
4. **确定性场景无 LLM**：evening_brief / stock_review / industry_research
   的语义模块未连接；接入属未来 taskbook。
5. **Harness upstream 为 developer preview**（rc.7）；升级需重新验收。
6. **凭证边界**：正式执行仅限 GitHub Actions secret；本地/临时环境禁止。

## 状态

- P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`；不写 `P8-B2 ACCEPTED`。
- 本任务未执行正式 acceptance corpus（场景验证有界、opt-in、非计数）。
