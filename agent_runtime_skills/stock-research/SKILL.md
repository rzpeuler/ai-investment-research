# stock-research

Scenario skill for single-company research.

## 使用场景 (Use case)
User asks to research a company (e.g., "研究一下宁德时代"): identify the target
company, load its identity and data readiness, then trigger the formal stock
research scenario.

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
