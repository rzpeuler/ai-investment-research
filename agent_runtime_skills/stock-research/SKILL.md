# stock-research

Scenario skill for single-company research.

## 使用场景 (Use case)
User asks to research a company (e.g., "研究一下宁德时代"): identify the target
company, load its identity and data readiness, then trigger the formal stock
research scenario.

## Exploration Execution Contract (P8-A3-R1)
- objective: 生成公司研究准备笔记（身份 + 数据就绪 + 待验证问题），输出
  findings / unanswered_questions / next_actions 后立即结束。
- allowed_tools: get_company_profile, check_data_readiness,
  run_research_scenario (bounded trigger)
- budget: max_turns=3, max_tool_calls=6, turn_timeout=120s
- completion: 输出包含 findings、unanswered_questions、next_actions 即完成。
- failure: 达到 max_turns 或 max_tool_calls 仍未完成 -> exploration_incomplete。
- empty_data: 工具返回空/数据不足时记录 data_gap 并结束，不重试。

## Tool 选择 (Tool selection)
- `get_company_profile` — resolve the exact company/security identity first.
- `check_data_readiness` — verify research data completeness before the workflow.
- `run_research_scenario` (scenario=`stock_research_report`) — trigger the formal
  Research OS research workflow after identity and readiness are confirmed.

## 工作方法 (Working method)
1. Resolve the target via `get_company_profile`; do not guess the entity.
2. Check readiness with `check_data_readiness` and report the status/as-of.
3. Trigger `run_research_scenario` to run the formal workflow through Research OS.
4. Preserve status, as-of, and evidence references in the reply.
5. Never select a source, call a collector, or write a graph.

## 禁止 (Boundaries)
- No source selection, collector call, database write, or graph write.
- No target price, buy/sell rating, or position advice.
- 完成 required_output_fields 后必须停止；禁止无限探索。

