# financial-analysis

Capability skill for financial / cash-flow analysis.

## 使用场景 (Use case)
User asks to analyze financials or cash flow for a company in an ongoing
session (e.g., "继续分析现金流"): use Research OS structured financial results
and trigger the appropriate research workflow.

## Exploration Execution Contract (P8-A3-R1)
- objective: 生成财务/现金流分析探索笔记，输出 findings /
  unanswered_questions / next_actions 后立即结束。
- allowed_tools: get_company_profile, check_data_readiness,
  run_research_scenario (bounded trigger)
- budget: max_turns=3, max_tool_calls=6, turn_timeout=120s
- completion: 输出包含 findings、unanswered_questions、next_actions 即完成。
- failure: 达到 max_turns 或 max_tool_calls 仍未完成 -> exploration_incomplete。
- empty_data: 工具返回空/数据不足时记录 data_gap 并结束，不重试。

## Tool 选择 (Tool selection)
- `get_company_profile` — confirm the company identity when the target is new.
- `check_data_readiness` — confirm financial data availability.
- `run_research_scenario` — trigger the formal financial research workflow
  through Research OS when structured analysis is needed.

## 工作方法 (Working method)
1. Reuse the session target; re-resolve identity only if ambiguous.
2. Confirm data readiness for financial data.
3. Trigger the formal workflow via `run_research_scenario`.
4. Use only structured Research OS results; preserve status, as-of, source,
   and evidence references.
5. Do not invent facts or make recommendations.

## 禁止 (Boundaries)
- No target price, buy/sell rating, or position advice.
- No collector call, database write, or graph write.
- 完成 required_output_fields 后必须停止；禁止无限探索。

