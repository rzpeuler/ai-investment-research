# Phase 6 Shared Contract（P6-F0 冻结）

> 状态：**FROZEN → UPDATED for Serial (2026-08-09)**
> 依据：`docs/engineering-guide.md` V1.3（第 69 节）、`docs/project-state/DECISIONS.md` #41、#43、#44、
> `docs/tasks/phase6-research-workflows.md`（P6-F0 里程碑）。
> 用途：6A / 6B / 6C 三个业务 Track 串行开发的**唯一共享边界**。
> 三个 Track 的 Agent 只需读取本文件 + engineering-guide V1.3 + serial taskbook，
> 即可确定自己的共享边界。
> 本文件只冻结契约，不实现任何 Phase 6 业务研究能力。

---

## 1. 目的与定位

F0 回答四个问题：

```text
多个 Agent 会共同依赖什么   → 统一控制面 + 共享契约（本文件）
多个 Agent 绝对不能各自定义什么 → 见 §3 统一控制面、§9 共享状态、§11 as_of 等
哪些 shared files 禁止未经授权修改 → 见 §7 Shared-file Ownership（CONFLICT ZONE，仅 P6-S5 可修改）
每个 Track 通过什么接口测试和集成 → 见 §8 isolated registry 注入 + §30 集成方式
```

原则（正式冻结）：

```text
契约串行冻结
+ 业务 Track 串行（按 S1→S2→S3→S4 顺序）
+ 共享控制面串行 enablement（P6-S5）
```

F0 PASS 后各 Track 按串行顺序依次开始（S1→S2→S3→S4），不得同时进行；
F0 本身不实现业务研究能力。

## 2. 七个 Scenario ID（FROZEN）

唯一正式名称（snake_case，与 `schemas/task.schema.json` scenario enum 及
`src/research_os/cli/main.py` `--scenario` choices 一致，均已存在）：

```text
6A：industry_research、theme_discovery
6B：evening_brief、daily_review、stock_review
6C：first_coverage、earnings_expectation
```

- **已存在于 `schemas/task.schema.json` enum 与 CLI choices；F0 及后续不得为 Phase 6
  再修改该 enum**，也不得创造同义名称（如 industry_analysis / theme_research /
  night_brief / company_review / earnings_forecast）。
- 新场景 Runner 的 `scenario` 类属性必须精确等于上述 ID。

## 3. 统一控制面（FROZEN，禁止第二套）

Phase 6 继续且只复用：

```text
Task（schemas/task.schema.json + src/research_os/models/core.py Task）
Plan（src/research_os/orchestrator/orchestrator.py Plan）
ScenarioRunner（src/research_os/orchestrator/scenario_runner.py）
ScenarioRegistry（src/research_os/orchestrator/scenario_registry.py）
Orchestrator.execute()（src/research_os/orchestrator/orchestrator.py）
ScenarioExecutionResult（src/research_os/orchestrator/scenario_runner.py）
RunDirectory（src/research_os/orchestrator/run_directory.py）
```

禁止创建：

```text
Phase6Orchestrator / IndustryOrchestrator / ReviewOrchestrator / CoverageOrchestrator
```

禁止创建第二套任务状态机、第二套执行结果类型、第二套运行目录逻辑。

## 4. ScenarioRunner Contract（FROZEN）

```text
scenario: str
version: str

validate_request(request) -> normalized request
build_plan(request, context) -> steps + data_requirements + model_policy + ...
execute(request, context) -> ScenarioExecutionResult
```

明确：**ScenarioRunner = orchestration adapter**。Runner 可以验证请求、组合已有模块、
生成 Plan、调用既有 Pipeline、组织统一执行结果。Runner 不得自己实现：

```text
财务算法 / 估值算法 / Evidence loader / graph traversal / graph lifecycle /
模型 Provider / 共享预算系统 / 数据库生命周期规则
```

Runner 的 `execute()` 必须返回既有 `ScenarioExecutionResult`（§9），不得返回自定义
结果类型（见 taskbook 4.1 F0 escalation 例外，任何自定义必须先 STOP 提交
shared-contract escalation，不在本窗口之外私自扩展）。

## 5. Plan Contract（FROZEN）

Phase 6 每个 Scenario 的 Plan 必须满足：

```text
Plan.steps 不得为空
Plan.data_requirements 不得为空
```

必须继续表达：`steps`、`data requirements`、`runtime budget`、`model policy`、
`fallback policy`、`output paths`、`as_of`。场景不得通过空 Plan 绕过控制面。
Orchestrator `create_plan()` 已机械强制非空 steps/data_requirements（空即 ValueError），
该行为不得被旁路。

## 6. Task ID Lineage（FROZEN）

所有新场景必须满足：

```text
Task.task_id = Plan.task_id = Scenario Request.task_id
= Scenario Run.task_id = ScenarioExecutionResult.task_id
```

若存在业务 artifact（ResearchFinding / Candidate / report metadata），也必须可回溯至该
Task。禁止新 Runner 自己生成第二个业务 task_id。
Orchestrator `_finalize_execution` / `_validate_business_lineage` 已机械校验
`<scenario>_request.json` / `<scenario>_run.json` 的 task_id 血缘；新场景 artifact
命名接入后（§8），该血缘校验须覆盖新场景文件名。

## 7. Shared-file Ownership（CONFLICT ZONE，FROZEN）

业务 Track 串行阶段默认**不得修改**以下文件。任何 Track 认为必须修改时：

```text
STOP → shared contract change proposal → 串行审查
→ 先 merge shared change → 所有 Track rebase
```

不得各分支自行解决。

```text
src/research_os/orchestrator/orchestrator.py
src/research_os/orchestrator/runners/__init__.py
src/research_os/orchestrator/scenario_runner.py
src/research_os/orchestrator/scenario_registry.py
src/research_os/orchestrator/run_directory.py
src/research_os/cli/main.py
schemas/task.schema.json
src/research_os/models/core.py
src/research_os/storage/migrations/*（migration files）
src/research_os/llm/client.py
src/research_os/llm/routing.py
config/model_routing.yaml
config/llm_providers.yaml
registry/sources.yaml
registry/source_groups.yaml
knowledge/ontology/*
src/research_os/knowledge/query.py
src/research_os/knowledge/context_builder.py
```

说明：
- 路径均为仓库相对路径（与 `schemas/task.schema.json` 等一致，从仓库根计数）；
- `src/research_os/knowledge/query.py` 与 `context_builder.py` 同时受 §18
  Graph→Research API Ownership 约束：只读复用，禁止第二套实现；
- `config/model_routing.yaml`、`config/llm_providers.yaml`、`src/research_os/llm/*`
  同时受 §21 模型治理约束：禁止第二套 LlmClient / budget / routing；
- ontology 允许目录下存在各 Track 只读引用，但新增/修改 node type、relation、
  seed 内容均受 §25 Ontology Gate 约束。

中央注册（`runners/__init__.py`）统一留给后续 serial enablement（P6-S5 阶段），
业务 Track 不得为让自己 Runner 工作而提前修改。CONFLICT ZONE 文件保持现状，任何修改须经串行门控（仅 P6-S5）。

## 8. Request / Run / Result Artifact Naming（FROZEN）

沿用既有正式 convention（`<scenario>_request.json` / `<scenario>_run.json` +
统一 `scenario_execution_result.json`）。冻结七个场景的确定性文件名：

```text
industry_research_request.json      industry_research_run.json
theme_discovery_request.json        theme_discovery_run.json
evening_brief_request.json          evening_brief_run.json
daily_review_request.json           daily_review_run.json
stock_review_request.json           stock_review_run.json
first_coverage_request.json         first_coverage_run.json
earnings_expectation_request.json   earnings_expectation_run.json
```

统一执行结果仍使用既有：

```text
scenario_execution_result.json
```

不要每个 Track 发明自己的 execution-result filename。规则：snake_case scenario id、
稳定文件名、Task ID lineage、无 filename collision。

## 9. 统一状态词汇（FROZEN）

研究模块继续使用既有正式状态：

```text
success / partial_success / degraded / insufficient_evidence / failed
```

若业务场景需要 `UNEXPLAINED` / `UNKNOWN` / `NOT_APPLICABLE` 等细节，优先放入
`reason` / `warnings` / `limitations` / domain-specific field，不得随意扩 shared
status enum（`ScenarioExecutionResult.status`、Task.status、Schema enum）。

## 10. as_of 总契约（FROZEN）

```text
timezone = Asia/Shanghai
as_of = explicit business cutoff
```

- 禁止：缺失 as_of 时在业务 Pipeline 内悄悄使用 now。
- Orchestrator 既有 contract 会显式构造 `as_of`（`create_task` 中 `as_of=as_of or now`，
  Task schema 中 as_of required）；**复用该 contract**，每个场景不得重新定义时间语义。
- 各 Runner `validate_request()` 必须像既有 `morning_brief` 一样显式归一化 as_of
  （业务窗口推导或校验），不得把空 as_of 透传给业务 Pipeline 让其在内部静默取 now。

## 11. 6A Graph as_of（FROZEN）

```text
GraphQueryService / KnowledgeContextBuilder 的 as_of = business validity time
```

必须完整继承 Phase 5 HistoryService 生命周期语义（as_of 读取 = 该时点合法有效的
版本化知识状态；禁止 future leakage）。禁止 6A 再写第二套生命周期算法，例如：

```text
resolve_graph_as_of() / industry_graph_snapshot() / theme_graph_snapshot()
```

## 12. 6B 时间契约（FROZEN）

### evening_brief

默认窗口：

```text
[08:00, 20:00) Asia/Shanghai
（inclusive start, exclusive end；与 engineering-guide V1.2 第 69.8 节一致）
```

延迟执行时 business window 不随实际启动时间漂移：例如 21:15 补跑仍是该业务日
08:00→20:00 窗口，而不是 08:00→21:15。

### daily_review

冻结：`review_business_date`、`as_of`、`market/session identity`。
不得把"实际执行日期"与"所复盘交易日"混为一体。

### stock_review

冻结：`entity`、`review window`、`as_of`、`previous research cutoff`。
必须是增量复盘，不得每次重跑完整 Phase4 研报（复用 Phase4 已验收产物）。

## 13. 6C 三时间治理（FROZEN）

earnings_expectation 必须严格区分：

```text
as_of（研究时点 / business cutoff）
historical_input_period（历史输入期间）
forecast_period（预测期间）
```

禁止：未来已经发布的财务数据用于历史时点预测（future leakage blocker）。
确定性算术（期间计算、聚合、比率）必须由代码完成，不得交给 LLM。

## 14. Evidence Lineage（FROZEN）

永久路径：

```text
RawItem → Evidence → Claim → ResearchFinding / Event → Markdown
```

明确 ID 不可互换：

```text
Claim ID != Evidence ID
ResearchFinding ID != Evidence ID
Graph ID != Evidence ID
Candidate ID != Evidence ID
```

报告关键事实必须能反查合法 Evidence（`evidence_ids` 指向真实 Evidence）。

## 15. Graph Context / Evidence Contract（FROZEN）

```text
KnowledgeContext != Evidence
```

合法 Graph→Research 唯一路径：

```text
GraphQueryService → KnowledgeContextBuilder → Research Context
```

KnowledgeContext 只用于：研究导航、实体发现、关系发现、产业坐标、检索方向、
上下文组织。不得直接证明报告事实。

## 16. Graph FACT 回证据规则（FROZEN）

研究模块希望使用 Graph FACT 时，必须：

```text
Graph node / edge
→ evidence_ids
→ authoritative Evidence reload
→ Evidence eligibility validation
→ time validation
→ source validation
→ Claim / ResearchFinding
```

禁止：

```text
Graph payload → Markdown FACT
```

## 17. MODEL_INFERENCE 语义（FROZEN）

Graph 中的 `MODEL_INFERENCE` 永远保持 `MODEL_INFERENCE`。即使 human reviewed、
已进入 active graph，也不得自动升级为 `FACT`。

## 18. Graph→Research API Ownership（FROZEN）

Phase 6A 必须复用：

```text
GraphQueryService（src/research_os/knowledge/query.py）
KnowledgeContextBuilder（src/research_os/knowledge/context_builder.py）
HistoryService / GraphRepository（src/research_os/knowledge/）
```

或后续经过正式 shared-contract review 的 successor。禁止：

```text
scenario direct SQLite SELECT graph_nodes / graph_edges
scenario parse JSON mirror as authority
second graph traversal implementation
second lifecycle implementation
second Evidence graph loader
```

## 19. DB Gate（FROZEN）

```text
DB = v6
F0 默认 NO MIGRATION
6A / 6B / 6C 业务 Track 不得自行迁移 DB（S1→S4 每个 milestone 各自 DB v6 基线）
```

若发现七场景无法在 v6 + run artifacts 下实现：不迁移，只输出
`DB_MIGRATION_REQUIRED: YES + JUSTIFICATION`，P6-F0 置 BLOCKED 交回架构审查。

## 20. Schema Ownership（FROZEN）

- JSON Schema = authoritative；Pydantic = constructor；`model_dump()` → schema validate。
- 各 Track 后续可创建自己拥有的新 Phase 6 schema（6A-owned / 6B-owned / 6C-owned），
  但**禁止未经授权修改 shared core schema**
- 若必须修改 shared schema：STOP → serial contract change。
- F0 不为七场景预先建立猜测性 Schema；只有同时满足（三个 Track 都必须共享、语义已
  冻结、没有它无法安全实现、不属于某 Track 自有业务对象）才在 F0 新增 shared Schema。
  当前 F0 判定：**无新增 shared Schema 必要**——既有 Task/Plan/ScenarioExecutionResult
  + run artifacts 已足够承载七场景契约。

## 21. 模型治理（FROZEN）

所有 Track 继承：

```text
deterministic first / Flash default / Pro escalation only
```

继续复用既有：

```text
LlmClient（src/research_os/llm/client.py）
routing policy（src/research_os/llm/routing.py）
task-level shared budget（CallBudget）
provider accounting / degradation semantics
```

禁止创建 `IndustryLlmClient / ThemeLlmClient / CoverageLlmClient / ReviewLlmClient`。

## 22. Provider failure / complexity separation（FROZEN）

必须继续区分 business complexity 与 provider failure（timeout / rate limit /
network failure）。Provider failure 不得成为自动升级 Pro 的业务理由，除非既有正式
routing policy 明确允许。

## 23. 输出安全 Shared Contract（FROZEN）

七场景统一禁止：

```text
目标价 / 买入评级 / 卖出评级 / 增持 / 减持建议 / 仓位建议 /
明日交易建议 / 自动荐股 / 诱导性交易语言
```

明确：

```text
theme_discovery != stock picking
first_coverage != brokerage rating
earnings_expectation != trading signal
daily_review != next-day trading plan
```

既有机械校验器（`config/report_policy.yaml` forbidden_outputs / forbidden_words +
`src/research_os/reports/` validator）为共享输出安全能力；Phase 6 场景报告必须继续
通过既有报告校验，F0 不实现场景报告，也不提前扩展校验器。

## 24. Research→Graph 顺序（FROZEN）

所有 Track：

```text
Research Capability PASS → 独立授权 → Research → GraphChange Candidate
```

禁止新场景第一次实现与 Candidate integration 一起上线；禁止场景直接 active graph
write。Phase 6 全部候选集成继续走既有 `GraphChange Proposal → Candidate →
Human Review → Validator → Deterministic Apply` 链路（`src/research_os/knowledge/`）。

## 25. Ontology Gate（FROZEN）

Phase 6 Track 默认不得增加 node type / relation type / relation semantics /
ontology seed。若现有 ontology 无法表达：record limitation → architecture review，
不得自行解决。

## 26. Source Expansion Gate（FROZEN）

Phase 6 Track 不得因业务需要直接加网站。正式来源扩张必须单独经过既有
source-governance 流程（discovery → probe → source governance → verification →
registry update）。F0 只冻结规则，不做来源扩张。

## 27. 串行业务开发与中央集成方式（FROZEN）

各 Track 开发时**不得修改默认中央注册表**；测试通过 isolated registry 注入：

```python
registry = ScenarioRegistry()
registry.register(MyScenarioRunner())
orch = Orchestrator(project_root, db=db, registry=registry)
```

不得为了让新 Runner 工作提前修改 `orchestrator.py` 或 `runners/__init__.py`。
中央注册统一留给 P6-S5 serial enablement。

## 28. F0 范围与产出

F0 交付：本契约文档 + 机械测试（见 `tests/unit/test_document_governance.py`
`test_phase6_shared_contract_frozen`）+ 状态文档同步。
F0 不实现：任何 Phase 6 ScenarioRunner / Pipeline / 中央 enable / migration /
Graph write 扩张 / ontology / source 扩张。

## 29. 验收标准

- 七个 scenario ID 与设计一致且未漂移（task.schema.json enum + CLI choices 复用）；
- 仍只有一个 Orchestrator 与一个 ScenarioRegistry contract；
- isolated registry 注入测试方式冻结（§27）；
- shared-file conflict zone 冻结（§7，仅 P6-S5 修改）；
- artifact naming / Task ID lineage / as_of / 6B 时间 / 6C 三时间 / Evidence lineage /
  Graph→Research read-only / KnowledgeContext != Evidence / MODEL_INFERENCE 语义 /
  DB v6 / 无 migration 全部冻结；
- 全量测试 0 failed；Schema 全部有效；DB v6 不变；Phase 2/3/4/5 回归 = 0；
- 独立 review（Codex/等价架构审查）0 blocker。
