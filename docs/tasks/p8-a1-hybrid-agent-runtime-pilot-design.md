# P8-A1 — Hybrid Agent Runtime Pilot Design

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

Task: P8-A1-HYBRID-AGENT-RUNTIME-PILOT-DESIGN
（设计任务：不实现代码；建立 Hybrid Agent Runtime 生产试点使用规范）

## 1. 目标

设计 DeepSeek Harness 在 Research OS 中的生产试点方案，建立 Hybrid Agent
Runtime 使用规范：明确 Harness 能做什么 / 不能做什么 / 如何治理 / 如何进入
后续生产试点。

## 2. 范围

### 允许

- architecture docs
- governance docs
- pilot plan

### 禁止

- 默认 runtime 切换
- 删除 Legacy
- 修改 LlmClient
- 修改 Schema
- 修改 Validator

本任务不改变任何运行路径；默认 runtime 保持 legacy；Harness 保持 opt-in。

## 3. 完成内容

### 3.1 架构设计文档

`docs/architecture/p8-a1-hybrid-pilot-design.md`：

1. **Task Classification**：HARNESS_ALLOWED（industry exploration / research
   preparation / evidence discovery assistance / multi-turn analyst assistant /
   hypothesis generation；输出不直接成为正式 Research Artifact）vs
   LEGACY_REQUIRED（FinancialFact / ResearchFinding / Catalyst / Risk /
   Evidence binding / Final report sections；需严格 Validator）。
2. **Runtime Router Design**：确定性 Router（非 LLM 决策），输入 task_type /
   output_contract / risk_level / authority_requirement，输出 LEGACY_ONLY /
   HARNESS_ALLOWED / HYBRID；默认 LEGACY_ONLY，白名单为配置工件。
3. **Permission Model**：ALLOW（company profile / graph query / data
   readiness / bounded scenario trigger）vs DENY（graph write / evidence
   mutation / financial fact creation / datasource direct access）。
4. **Session Governance**：session lifetime / timeout budget（区分 LLM request
   timeout 60s / agent turn timeout 300s / tool timeout 30s）/ token budget
   （provider-reported，≤ 治理上限）/ audit requirements。
5. **Audit Boundary**：记录 runtime_selection / harness_session_id / skill_used /
   tools_called / authority_checks / final_artifact_source；支持回答"这个研究
   结论由哪个 runtime 产生？"。
6. **Pilot Acceptance Criteria**：Reliability（session success / cleanup
   evidence）/ Governance（audit completeness / zero unauthorized）/
   Value（analyst usefulness / exploration quality）/ Cost（latency / token）。

### 3.2 文档更新

- DECISIONS.md：Decision #82（P8-A1 Hybrid Pilot Design）
- CURRENT_STATE.md：`HARNESS_IMPLEMENTATION: SPIKE_COMPLETE`；新增 P8-A1 条目
- NEXT_PHASE.md：P8-A2 序列（POSIX CI 重跑 → P8-A2 试点实施授权）
- KNOWN_LIMITATIONS.md：P8-A1 设计限制（未实现 / 未授权）

## 4. 验收

- 文档一致性：无矛盾架构描述（继承 #54 / #80 / P8-A0 / R6）；
- 无提前宣布生产采用（HARNESS_IMPLEMENTATION=SPIKE_COMPLETE、
  PRODUCTION_ADOPTION=NO）；
- 默认 runtime 不变；D4 范围不变。

## 5. 测试 / 检查

- 交叉引用检查：新增文档引用的路径 / Decision 编号存在；
- git diff 检查：production code 0 changes；
- 无代码测试（纯文档设计任务）。

## 6. 状态

- P8-A1 为设计任务；Agent 不得 self-accept。
- Harness 生产采用保持 NOT_AUTHORIZED；默认 runtime 保持 legacy。
