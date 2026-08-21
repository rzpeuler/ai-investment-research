# industry-graph-research

Capability skill for read-only industry / supply-chain graph research.

## 使用场景 (Use case)
User asks about industry-chain or supply-chain relationships and risks (e.g.,
"分析产业链风险"): traverse the Research OS industry graph read-only.

## Tool 选择 (Tool selection)
- `query_industry_graph` — read-only graph traversal from Research OS
  authority (root node + as-of).
- `get_company_profile` — resolve the root entity id if the user names a company.

## 工作方法 (Working method)
1. Resolve the target entity id via `get_company_profile` when needed.
2. Call `query_industry_graph` with the root node id and as-of; respect the
   returned depth / direction bounds.
3. Report only what the graph actually returns; never invent nodes or edges.
4. Never approve, apply, or directly write graph changes.

## 禁止 (Boundaries)
- No graph write / apply / approve; no collector call; no database write.
