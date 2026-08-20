# P8-B2-INTERNAL-TRIAL-001 — Harness 调用路径审计报告

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

## 1. 审计范围与方法

- 范围：`src/research_os/` 下全部 LLM 调用入口（llm/、harness/、orchestration/、
  scenarios/、validation/ 相关模块），审计基于代码级静态分析与既有测试证据。
- 方法：grep 全量 `LlmClient(` 构造点与 provider 注入点；检查 gateway /
  harness adapter 的接线；核对各场景管线的 `llm_called` 标记。

## 2. 当前调用路径图

```text
场景（7 大研究场景）
   │
   ▼
Orchestrator（scenario runners）
   │
   ▼
Pipeline / Runner（equity_research / brief / review / industry…）
   │
   ├── 无 LLM 的确定性路径（evening_brief / stock_review / industry_research
   │      当前语义模块未连接：输出显式 llm_called: false）
   │
   ▼
LlmClient（统一 LLM 入口，唯一入口；预算 / 校验 / 降级 / 审计都在此层）
   │
   ├── 默认（legacy）：DeepSeekChatCompletionsProvider（直连，P8-B1 前路径）
   │
   └── 内部试运行 opt-in（P8_B2_SCENARIO_TRIAL=1）：
          HarnessLlmProvider → HarnessAgentRuntimeAdapter
            → pinned DeepSeek Harness（dsh 0.1.0-rc.7）
            → DeepSeek provider（Harness 控制面内）
   │
   ▼
Evidence Validator（schema 校验，输出不合格 → 诚实回退）
   ▼
ResearchFinding / Claim（仅通过校验的模型输出可进入）
   ▼
Markdown Report
```

## 3. LLM 入口清单（审计结果）

| 构造点 | 用途 | Provider |
|---|---|---|
| `llm/client.py` `LlmClient` | 统一入口（budget/validation/fallback/audit） | 注入式 |
| `equity_research/pipeline.py` | 场景管线（first_coverage / earnings_expectation 等） | 默认 None（诚实回退）；live 时直连 |
| `orchestrator/runners/equity_research.py` | 正式 runner | `create_provider(live=True)` |
| `dashboard/runtime.py` | P7-UX1 Chat | `create_provider(live=True)` |
| `knowledge/candidate_pipeline.py` | Graph 候选 | 同统一入口 |
| `agent_runtime/gateway.py` + `harness_adapter.py` | Harness 控制面（chat / trial / 本任务 opt-in） | Harness |

## 4. 绕过路径清单（真实发现，按严重度）

1. **（by design，非缺陷）场景默认直连 provider**：七大场景经
   `LlmClient → DeepSeekChatCompletionsProvider` 直连 —— 这是冻结的
   `DEFAULT_RUNTIME = legacy`（Decision #54/#55；P8-B2 未授权生产默认切换）。
   **修复建议**：在 Production Adoption 决策前保持 legacy 默认；本任务提供
   opt-in Harness 入口用于验证，不切换默认。
2. **（by design，诚实降级）evening_brief / stock_review / industry_research
   无 LLM 调用**：语义模块未连接，输出显式 `llm_called: false` +
   `semantic_llm_modules_not_connected`。这不是绕过，是如实的能力边界。
3. **无第二套 AI 执行路径**：全仓所有模型调用均经 `LlmClient`；不存在绕过
   LlmClient 直连 SDK 的入口（审计确认）。

## 5. 场景 LLM 接线结论

| 场景 | LLM 接线 | 证据 |
|---|---|---|
| first_coverage | EquityLlmTasks（≥5 任务）经 LlmClient | equity pipeline / tasks |
| earnings_expectation | EquityLlmTasks（≥3 任务）经 LlmClient | equity pipeline / tasks |
| evening_brief | 无（llm_called: false） | brief/renderer.py:73-75 |
| stock_review | 无（llm_called: false） | review/stock.py:248 |
| industry_research | 无（deterministic_fallback, llm_called: False） | runners/industry_research.py:147 |

## 6. 关键保障（验证结论）

- LLM 输出不能直接成为事实：所有输出经 `LlmClient → LlmOutputValidator`
  （真实项目 schema）校验，不合格 → 诚实回退，不产生 MODEL_INFERENCE
  （离线测试锁定）。
- Budget governance：`EquityLlmTasks.BudgetTracker`（flash 上限 / pro 升级 /
  共享预算）+ `TrialBudget`（max_retries=0）在 LlmClient 层统一执行。
- 审计：`llm_call_records` 记录 call_id / task_id / module / status /
  model / provider / latency / usage / failure / fallback。
- Evidence 链：RawItem → Evidence → Claim → ResearchFinding → Report 未受
  Harness 入口影响（Harness 仅作为模型调用控制面；authority 仍在 Research OS）。

## 7. 修复建议汇总

1. 保持 legacy 默认（冻结）；Production Adoption 决策前不做默认切换。
2. Harness 入口以 opt-in 方式存在（本任务已实现 `HarnessLlmProvider`），
   供 Production Adoption 决策采集工程证据。
3. evening_brief / stock_review / industry_research 的语义 LLM 模块接入属
   未来独立 taskbook（本任务不扩展）。
