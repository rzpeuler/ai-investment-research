# P8-A0 Hybrid Runtime Spike Report

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

Task: P8-A0-HARNESS-HYBRID-RUNTIME-SPIKE
（验证 DeepSeek Harness 作为 Research OS Agent Orchestration Runtime 的可行性；
最小 Hybrid Runtime Spike：Harness + Skills + MCP + Research OS Tools）

## 1. Harness 版本

- 运行时：`@deepseek-ai/dsh@0.1.0-rc.7`（exact pin，SDK 与 runtime-bin 同版本）
- profile：`research-headless`（deny-by-default：bash/pwsh/fs-write/editor/jobs/
  subagent/workflow/todo/goal/direct-web/web-search 全关）
- MCP namespace：`research-os-mcp/v1`；协议协商沿用 REPAIR-01 修复
- 宿主：Windows（win32）；Node v24；DEEPSEEK_API_KEY 可用

## 2. MCP 架构（Hybrid 4-Tool Facade）

```text
DeepSeek Harness (pinned rc.7)
  ↓ MCP stdio (research-os-mcp/v1)
Research OS MCP Server（spike 4-tool surface）
  ├─ get_company_profile       （公司身份解析，Research OS authority）
  ├─ check_data_readiness      （研究数据完整性检查，dry-run 零网络）
  ├─ query_industry_graph      （产业链/行业关系读取，只读 GraphQueryService）
  └─ run_research_scenario     （触发已有 Research Workflow，bounded trigger）
  ↓
Existing Python Research OS（Orchestrator / Registry / DataPreflight / GraphQuery）
```

- **默认不变**：未设置 `P8_A0_HYBRID_SPIKE=1` 时，stdio MCP server 仍暴露冻结的
  2-tool 表面（P8-B1/P8-B2 契约不变）；spike 为 opt-in。
- **禁止开放**（DENY，机械校验）：`cninfo_fetch` / `nbs_fetch` / `sina_fetch` /
  `collector_execute` / `sql_query` / `graph_write` / `graph_apply` /
  `graph_approve` / `apply_graph_change` / `direct_data_source_access` /
  `approve_graph_change`。
- 新增 handler 均为只读 / bounded：`query_industry_graph` 走只读
  `GraphQueryService`；`run_research_scenario` 只校验场景注册并返回
  task/plan 投影，不写 DB、不写图、不执行 LLM 重管线。

## 3. Skill 列表（3 个，可发现）

| Skill | kind | 内容 |
|---|---|---|
| stock-research | scenario | 使用场景 / Tool 选择（get_company_profile + check_data_readiness + run_research_scenario）/ 工作方法 / 禁止边界 |
| financial-analysis | capability | 现金流/财务分析场景 / Tool 选择 / 工作方法 / 禁止边界 |
| industry-graph-research | capability | 产业链只读研究场景 / Tool 选择（query_industry_graph）/ 工作方法 / 禁止边界 |

- 位置：`agent_runtime_skills/`（profile `customSkillDirs` 挂载）；
- Skill 只含：能力说明 + 工作方法 + Agent routing metadata；**不含业务代码**。

## 4. Session 测试结果

（`scripts/p8_a0_hybrid_runtime_spike.py` 输出，完整数据见
`reports/p8_a0_hybrid_spike.json`；spike_run_id `a0-spike-41f9ca6f8c89`）

**STATUS: COMPLETED** — 真实连续 4-turn 会话全部完成；`same_session_all_turns=true`
（同一内部 Harness session 跨 4 turn，session continuity 验证通过）。

| Turn | 内容 | Skill | 结果 | Tool 调用 |
|---|---|---|---|---|
| 1 | 研究宁德时代 | stock-research | completed | get_company_profile×1, check_data_readiness×1, run_research_scenario×1 |
| 2 | 继续分析现金流 | financial-analysis | completed | get_company_profile×1, run_research_scenario×8 |
| 3 | 分析产业链风险 | industry-graph-research | completed | query_industry_graph×7 |
| 4 | 比较亿纬锂能 | stock-research | completed | get_company_profile×10, check_data_readiness×2 |

- 全程 unauthorized_tools = {}（0 次越权）；每 turn 均 `same_session=true`；
  response 只记录 sha256（不落原始文本）；usage 为 provider-reported。
- 各 turn 延迟：21.2s / 34.4s / 27.1s / 26.8s（真实 agentic 多轮）。
- 首次尝试（180s turn 超时）在第 2 turn 触发 `TURN_TIMEOUT`（agentic 延迟
  超预算）→ 提高至 300s 后 4 turn 全部完成。这与 P8-B2 观察到的
  TURN_TIMEOUT 特征一致，如实记录。

## 5. Tool 调用链

（由 MCP event log 记录；event_count=32）

```text
Turn 1 → get_company_profile → check_data_readiness → run_research_scenario
Turn 2 → get_company_profile → run_research_scenario（agent 多次触发）
Turn 3 → query_industry_graph（×7 遍历产业链）
Turn 4 → get_company_profile（×10 解析两家公司）→ check_data_readiness

会话累计：get_company_profile=12, query_industry_graph=7,
          check_data_readiness=3, run_research_scenario=9
```

4 个 Research OS Tool 全部被真实调用；无未授权工具调用。

## 6. Authority 边界验证

| 边界 | 结果 |
|---|---|
| 默认 runtime 保持 legacy | PASS（未切换） |
| graph write / apply / approve | DENY（机械校验，spike 事件日志 0 次） |
| collector / source 直连 | DENY（0 次） |
| sql / db write | DENY（0 次） |
| Evidence 修改 | DENY（无写 Evidence 的 Tool） |
| Validator bypass | 0（无 bypass 路径；schema 86/86 不变） |
| secret leakage | 0（含 DEEPSEEK_API_KEY 全量扫描，4 turn 均 0） |
| 进程清理 | root TERMINATED；tree NOT_VERIFIED（Windows fail-closed，如实记录） |

## 7. Audit 结果

- 每 turn 记录：status / same_session / duration_ms / tool_calls /
  unauthorized_tools / usage（provider-reported，不推断）/ response_sha256；
- MCP event log 全量统计：event_count=32；allowed tool 调用
  （get_company_profile=12, query_industry_graph=7, check_data_readiness=3,
  run_research_scenario=9）；unauthorized=0；secret_scan 4 turn 全 0；
- 进程清理：owned process-tree cleanup 状态（Windows 为 fail-closed
  NOT_VERIFIED 语义，如实记录，不宣称 NO）。

## 8. 风险（如实）

1. **Windows 宿主限制**：accepted 清理证据模型在 Windows 无法机械枚举 owned
   process tree → `process_residue` 只能 NOT_VERIFIED（fail-closed），不能宣称
   `NO`；正式接受建议在 POSIX CI（GitHub Actions ubuntu）重跑。
2. **Harness 不是严格结构化生成 runtime**（P8-B2 已实证 0.10 vs 0.90）：
   spike 只验证 Orchestration / MCP / Tool / Session 闭环，不改变默认生成路径。
3. **Agentic 延迟 / TURN_TIMEOUT**：180s turn 超时下第 2 turn 超时；提高至 300s
   后 4 turn 全部完成。生产需为 agentic turn 配置充足预算，或拆分更小的回合。
4. **token 成本**：agentic 多轮 token 用量高于 legacy 单轮（本 spike 单 turn
   provider-reported ~612k tokens 含缓存）；spike 有界（4 turn），报告如实记录。
5. **run_research_scenario 是 bounded trigger**：返回 task/plan 投影，不执行
   完整 LLM 研究管线（保持 Research Workflow authority 不变）。

## 9. 测试 / 检查结果

- 新增 `tests/unit/test_p8_a0_hybrid_spike.py`：spike 4-tool catalog / server
  handshake / deny 校验 / 冻结 2-tool 契约不变 / profile verifier 4-tool /
  supervisor handshake 4-tool / skill 发现（3 个，无业务代码）/ 会话连续性
  （offline fake）/ 报告 bounded shape / opt-in 开关。
- 既有 P8-B1/P8-B2 冻结测试：PASS（2-tool 契约不变）。
- 全量单元测试：`python -m pytest tests/unit/` → **2828 passed / 4 skipped /
  1 warning**（0 failed）。
- schema：**86/86 PASS**（未增删 schema）。
- 无 production routing / provider / schema / validator / LlmClient 修改。

## 10. 修改文件

- src/research_os/agent_runtime/tool_catalog.py（+SPIKE 4-tool 表面，冻结 2-tool 不变）
- src/research_os/agent_runtime/research_capabilities.py（+query_industry_graph /
  run_research_scenario handlers）
- src/research_os/agent_runtime/mcp/{tools,server,contracts}.py（spike server +
  参数化 allowed_tools，默认冻结）
- src/research_os/agent_runtime/{runtime_supervisor,profile_verifier}.py（spike
  toolset 兼容，默认冻结）
- src/research_os/agent_runtime/production_runtime.py（+build_hybrid_spike_harness_adapter）
- scripts/p8_b1_mcp_server.py（env-gated spike 4-tool surface，默认冻结）
- scripts/p8_a0_hybrid_runtime_spike.py（新增 spike runner）
- tests/unit/test_p8_a0_hybrid_spike.py（新增）
- agent_runtime_skills/{stock-research,financial-analysis,industry-graph-research}/SKILL.md
- docs/project-state/{CURRENT_STATE,NEXT_PHASE,KNOWN_LIMITATIONS,DECISIONS}.md
- tests/unit/test_document_governance.py（V1.8 → V1.9 同步，P8-ARCH-001 遗留）

## 11. 是否建议进入 P8-A1

**建议：有条件进入 P8-A1（Hybrid Agent Runtime 正式设计/实施评估）。**

条件：
1. 在 POSIX CI（ubuntu）重跑 spike，取得 `process_residue=NO` 的机械证据；
2. 独立验收本 spike（MCP 4-tool 表面、Skill 定义、Session 结果、Authority）；
3. P8-A1 taskbook 明确范围：仍保持 legacy 默认，Harness 仅限白名单探索类任务；
4. 不将 Harness 作为默认严格结构化生成 runtime（P8-B3 门槛维持 0.70 对 legacy）。

若以上条件满足，P8-A1 可评估：Conversation Memory / durable session 的产品化、
Skill 目录正式化、MCP 4-tool 表面进入受治理 catalog、以及 Hybrid 两阶段
（Harness 探索 → Legacy 成稿）的最小实现。
