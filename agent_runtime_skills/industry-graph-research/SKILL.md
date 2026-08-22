# industry-graph-research

Capability skill for read-only industry / supply-chain graph research.

## 使用场景 (Use case)
User asks about industry-chain or supply-chain relationships and risks (e.g.,
"分析产业链风险"): traverse the Research OS industry graph read-only.

## Exploration Execution Contract (P8-A3-R1)
- objective: 生成产业链风险探索笔记（图谱只读），输出 findings /
  unanswered_questions / next_actions 后立即结束。
- allowed_tools: query_industry_graph, get_company_profile
- budget: max_turns=3, max_tool_calls=6, turn_timeout=120s
- completion: 输出包含 findings、unanswered_questions、next_actions 即完成。
- failure: 达到 max_turns 或 max_tool_calls 仍未完成 -> exploration_incomplete。
- empty_data: 图谱返回空/数据不足（insufficient_evidence）时记录 data_gap
  并结束，**不得重试**。

## Tool 选择 (Tool selection)
- `query_industry_graph` — read-only graph traversal from Research OS
  authority (root node + as-of).
- `get_company_profile` — resolve the root entity id if the user names a company.

## 工作方法 (Working method)
1. Resolve the target entity id via `get_company_profile` when needed.
2. Call `query_industry_graph` with the root node id and as-of; respect the
   returned depth / direction bounds.
3. Report only what the graph actually returns; never invent nodes or edges.
4. If the graph returns empty/insufficient evidence, record data_gap and stop
   (do NOT retry in a loop).
5. Never approve, apply, or directly write graph changes.

## 禁止 (Boundaries)
- No graph write / apply / approve; no collector call; no database write.
- 完成 required_output_fields 后必须停止；禁止无限探索。

