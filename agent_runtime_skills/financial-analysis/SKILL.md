# financial-analysis

Capability skill for financial / cash-flow analysis.

## 使用场景 (Use case)
User asks to analyze financials or cash flow for a company in an ongoing
session (e.g., "继续分析现金流"): use Research OS structured financial results
and trigger the appropriate research workflow.

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
