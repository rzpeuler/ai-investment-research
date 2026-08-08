# Phase 5：产业图谱与长期知识库闭环——正式工程任务书

**TASKBOOK_STATUS: APPROVED**
**IMPLEMENTATION_STATUS: IN_PROGRESS**
**COMPLETED_MILESTONE: M5_HUMAN_REVIEW_WORKFLOW**
**NEXT_MILESTONE: M6_DETERMINISTIC_APPLY_ENGINE**
**NEXT_MILESTONE_AUTHORIZATION: AUTHORIZED**

> M1 PASS（SHA `b097996`）。M2 PASS（SHA `565d500`）。M3 PASS（SHA `242e039`）。M4 PASS（SHA `20b7a15`）。M5 PASS（SHA `92649a7`，Offline CI `31251491357`，1725 passed / 5 skipped / 0 xfail，55/55 schemas）。M6 已由用户于 2026-08-08 明确授权。

**任务书创建基线：**

```text
repository:
rzpeuler/ai-investment-research

base_branch:
master

base_sha:
ea026f18ce09efd2f0a24bab8a38255e75233911

baseline_ci:
Offline CI PASS
Ubuntu / Python 3.12
1133 passed / 5 skipped
51/51 schemas
compileall PASS
```

在用户明确授权实施前：

```text
Phase 5 = BLOCKED
```

本文件完成并通过顶层设计审核，不自动解除 `BLOCKED`。

---

# 1. Phase 5 目标

Phase 5 建设的不是“让 LLM 自动画产业链”，而是建立一个：

> 可持续积累、可追溯证据、可处理时间变化、允许模型提出候选修改、但模型不能自行篡改核心知识的产业知识系统。

最终必须形成：

```text
RawItem
→ Evidence
→ Claim / Event / ResearchFinding
→ GraphChange Proposal
→ GraphChange Candidate
→ Human Review
→ Deterministic Apply
→ Versioned GraphNode / GraphEdge
→ Query / Knowledge Context
```

核心原则：

```text
LLM 可以提出修改
LLM 不可以批准修改

人工可以批准修改
人工批准本身不能绕过 Schema / Evidence / Validator

数据库写入、版本号、时间有效性、状态迁移、幂等：
全部由确定性代码负责
```

---

# 2. Phase 5 非目标

本阶段禁止顺手实现：

- Neo4j、NebulaGraph 等复杂图数据库；
- 图形化管理后台；
- 自动批准 GraphChange；
- 无人工审核的核心图谱写入；
- 全互联网自动构建产业图谱；
- 自动把所有晨报信息写入图谱；
- 自动把社区观点变成长期知识；
- 自动主题荐股；
- 自动交易；
- 目标价；
- 买卖评级；
- 仓位建议；
- Phase 6 的首次覆盖、晚报、复盘、主题挖掘完整场景；
- 未在本任务书定义的数据源扩张；
- 为 Phase 5 顺手重构 Phase 2/3/4 已通过验收的业务逻辑。

第一版继续采用：

```text
SQLite
+ JSON
+ Markdown
```

不得把数据库技术选型变成本阶段主体。

---

# 3. 永久知识边界

## 3.1 三套分类继续并存

不得合并为单一 taxonomy。

### 稳定行业树

第一版保留稳定行业分类入口。

### 产业链树

保留：

```text
上游材料和设备
中游制造和组件
下游产品与应用
支撑基础设施
服务与软件
```

### 动态主题

动态主题只能作为标签或 `InvestmentTheme` 节点，不得承担稳定行业树职责。

---

# 4. 首批本体范围

不得擅自扩张首批骨架。

首批领域：

```text
AI_hardware
semiconductor
AI_software
```

首批骨架沿用 `docs/engineering-guide.md` 第 39 节。

---

# 5. 图谱节点类型

只能使用以下正式节点类型：

```text
Industry
IndustrySegment
Company
Product
Technology
Material
Equipment
Application
Policy
Event
Metric
PersonOrInstitution
Report
InvestmentTheme
```

新增类型属于：

```text
ONTOLOGY_CHANGE
```

必须单独经用户批准，不得由工程 Agent 或运行时 LLM 自行增加。

---

# 6. 图谱关系类型

只能使用：

```text
BELONGS_TO
UPSTREAM_OF
DOWNSTREAM_OF
SUPPLIES
PURCHASES_FROM
PRODUCES
USES_TECHNOLOGY
APPLIED_IN
COMPETES_WITH
SUBSTITUTES
BENEFITS_FROM
HARMED_BY
AFFECTS
MENTIONED_IN
SUPPORTED_BY
CONTRADICTED_BY
HAS_METRIC
HAS_CATALYST
```

任何未登记 relation：

```text
INVALID_RELATION
```

不得自动新增。

---

# 7. 认识论分层

Phase 5 必须防止“产业图谱 = 全部内容都变成事实”。

核心图谱明确区分：

```text
GOVERNANCE
FACT
MODEL_INFERENCE
```

## 7.1 GOVERNANCE

只用于经用户批准并写入版本控制的本体骨架。

首版允许：

```text
Industry
IndustrySegment
```

及其稳定分类关系。

GOVERNANCE 不要求外部 Evidence，但必须有：

```text
origin_kind = governance_seed
```

来源只能是版本化 ontology 文件。

不得用 GOVERNANCE 为某家公司添加主营业务、供应关系、受益关系等事实。

## 7.2 FACT

必须存在 Evidence。

不得由：

```text
SOURCE_OPINION
MODEL_INFERENCE
HYPOTHESIS
```

直接升级而来。

## 7.3 MODEL_INFERENCE

允许表达：

```text
BENEFITS_FROM
HARMED_BY
AFFECTS
SUBSTITUTES
```

等需要分析推导的关系。

但必须：

- 明确标记 MODEL_INFERENCE；
- 保存 Evidence；
- 保存推理来源对象；
- 保存置信度；
- 经人工审核；
- 查询时不得渲染成 FACT。

## 7.4 SOURCE_OPINION / HYPOTHESIS

第一版不得直接成为 active core GraphEdge。

继续保留在：

```text
Opinion
Claim
ResearchFinding
```

层。

可用于产生 GraphChange candidate，但不能直接成为长期事实。

---

# 8. 新增正式契约

## 8.1 `graph_node.schema.json`

必须至少包含：

```text
node_id
node_type
name
aliases
description
status
valid_from
valid_to
evidence_ids
version
last_reviewed_at
review_status
origin_kind
originating_graph_change_id
created_at
```

### node_id

必须稳定。

已有 Company 实体不得创造第二套身份。

对于 Company：

```text
GraphNode.node_id == Entity.entity_id
```

例如：

```text
company:600519.SH
```

不得创建：

```text
company:贵州茅台
stock:600519
company:moutai
```

作为并行核心实体。

### version

整数：

```text
>= 1
```

同一 `node_id` 的新知识版本递增。

禁止覆盖历史 payload。

### status

允许：

```text
active
superseded
expired
retired
```

### review_status

active 节点必须为：

```text
approved
```

---

# 9. `graph_edge.schema.json`

至少包含：

```text
edge_id
source_node_id
relation
target_node_id
attributes
assertion_type
valid_from
valid_to
confidence
evidence_ids
review_status
version
originating_graph_change_id
created_at
last_reviewed_at
```

### edge_id

同一逻辑关系跨版本保持稳定 identity。

版本通过：

```text
edge_id + version
```

识别。

### assertion_type

只能：

```text
GOVERNANCE
FACT
MODEL_INFERENCE
```

### confidence

```text
0.0 <= confidence <= 1.0
```

confidence 不能代替 Evidence。

高 confidence 的无来源关系仍非法。

---

# 10. GraphChange 正式化

现有 GraphChange 从 Phase 0 候选容器升级为 Phase 5 正式变更对象。

不得继续长期依赖：

```text
node: arbitrary dict
edge: arbitrary dict
```

M1 后：

```text
GraphChange.node
```

必须符合 GraphNode draft 结构。

```text
GraphChange.edge
```

必须符合 GraphEdge draft 结构。

GraphChange 继续支持：

```text
add_node
add_edge
modify_attribute
retire_edge
retire_node
```

并必须保留：

```text
current_knowledge
new_evidence_ids
suggested_change
impact_scope
conflicts
verification_points
review_status
created_at
reviewed_at
```

---

# 11. 新增 `graph_change_proposal.schema.json`

LLM 不直接生成正式 GraphChange。

LLM 只允许生成：

```text
GraphChangeProposal
```

Proposal 不允许包含：

- 持久化 UUID；
- version；
- review_status；
- reviewed_at；
- 数据库主键；
- active 状态。

至少包含：

```text
proposal_type
source_object_ids
candidate_node
candidate_edge
new_evidence_ids
suggested_change
impact_scope
conflicts
verification_points
confidence
```

之后由确定性代码：

```text
Proposal
→ validate
→ qualify evidence
→ assign IDs
→ assign timestamps
→ compare current graph
→ construct GraphChange(candidate)
```

---

# 12. 人工审核审计契约

新增：

```text
graph_review.schema.json
```

至少记录：

```text
review_id
graph_change_id
decision
reviewer
reviewed_at
candidate_hash
review_patch
notes
resulting_graph_change_id
```

decision：

```text
approved
approved_with_changes
deferred
rejected
```

人工审核必须有 reviewer。

不得使用：

```text
"system"
"llm"
"auto"
```

冒充人工 reviewer。

---

# 13. GraphChange 状态机

合法：

```text
candidate
→ approved
→ apply

candidate
→ approved_with_changes
→ validated patched change
→ apply

candidate
→ deferred

candidate
→ rejected
```

禁止：

```text
candidate → active
candidate → applied
LLM → approved
```

若：

```text
conflicts != []
```

第一版视为 blocking conflict。

不得 apply：

```text
approved
```

直到冲突通过新的 Evidence / 新 GraphChange 得到解决。

允许人工：

```text
deferred
rejected
```

---

# 14. Markdown 人工审核

第一版继续采用 Markdown，不建设后台。

目录：

```text
knowledge/candidates/
```

每个 candidate：

```text
knowledge/candidates/{graph_change_id}.md
```

格式必须包含：

```markdown
# 图谱变更候选

## GraphChange ID

## 变更类型

## 当前知识

## 新证据

## 建议变更

## 影响范围

## 冲突信息

## 验证节点

## 审核选项
- [ ] 批准
- [ ] 修改后批准
- [ ] 暂缓
- [ ] 拒绝

## Reviewer

## Review Notes

## Approved Patch
```

Parser 必须机械要求：

```text
exactly one checkbox selected
```

0 个或 >1 个：

```text
INVALID_REVIEW
```

---

# 15. 核心图谱写入硬门槛

`GraphApplyEngine` 执行前必须逐项确认：

1. GraphChange 存在；
2. GraphReview 存在；
3. review decision 合法；
4. candidate hash 与审核时一致；
5. Node / Edge Schema 合法；
6. source node 存在；
7. target node 存在；
8. relation 已登记；
9. Evidence ID 实际存在；
10. Evidence 与目标实体/关系有关；
11. Evidence 时间合法；
12. Evidence 来源资格合法；
13. blocking conflict 为 0；
14. version 连续；
15. 当前 active version 与审核时基线未发生冲突；
16. 幂等键未重复 apply；
17. 操作不会覆盖历史。

任何一项失败：

```text
APPLY_REJECTED
```

不得部分写入。

整个 apply 必须事务化。

---

# 16. Evidence 规则

## 16.1 Governance seed

首版 ontology seed 可以：

```text
evidence_ids = []
origin_kind = governance_seed
```

但仅限版本控制中明确批准的产业分类骨架。

## 16.2 公司结构事实

例如：

```text
Company PRODUCES Product
Company USES_TECHNOLOGY Technology
Company SUPPLIES Company
Company PURCHASES_FROM Company
```

优先要求：

```text
S / A
```

证据。

B 级不能单独把重大公司结构关系写成 FACT。

## 16.3 行业背景关系

B 可作为补充。

## 16.4 社区内容

C/D：

不得单独支持 FACT edge。

## 16.5 模型推断

MODEL_INFERENCE 必须引用实际 Evidence。

不能出现：

```text
evidence_ids = []
assertion_type = MODEL_INFERENCE
```

---

# 17. 时间语义

继续沿用 Phase 4 已修正的时间治理。

必须区分：

```text
information time
review time
apply time
validity time
```

Evidence：

```text
published_at <= research as_of
```

Review：

```text
reviewed_at
```

是人工审核发生时间，不是知识发布时间。

Graph：

```text
valid_from / valid_to
```

表示该知识在业务世界中的有效区间。

不得把：

```text
reviewed_at
created_at
applied_at
```

冒充 `valid_from`。

---

# 18. 历史版本规则

不得：

```text
UPDATE payload = new_knowledge
```

覆盖旧版本。

修改节点或关系必须产生：

```text
version N+1
```

旧版本保留。

允许确定性关闭旧版本的：

```text
valid_to
status
```

但必须存在对应 GraphChange / Review / Apply audit。

必须能回答：

```text
2025-08-01 系统当时认为是什么？
2026-08-01 当前版本是什么？
这条关系为什么发生变化？
使用了什么新 Evidence？
谁批准了变更？
```

---

# 19. 存储设计

SQLite 为结构化权威持久化。

增加：

```text
graph_nodes
graph_edges
graph_reviews
graph_applications
```

不得删除已有：

```text
graph_changes
```

建议下一顺序迁移：

```text
006_phase5_knowledge_graph.sql
```

但执行 Agent 开始前必须重新检查 migration 目录，以实际 next migration number 为准。

---

# 20. JSON 镜像

生成：

```text
knowledge/graph/nodes/
knowledge/graph/edges/
knowledge/history/
```

JSON 为：

```text
deterministic export
```

不得与 SQLite 形成两个可独立编辑的权威源。

禁止人工直接编辑 active graph JSON 后反写数据库。

---

# 21. Ontology seed

新增版本化 ontology，例如：

```text
knowledge/ontology/industry_graph_v1.yaml
```

只包含工程指南已经批准的：

```text
AI硬件
半导体
AI软件
```

及其子节点。

Seed：

```text
deterministic
no LLM
idempotent
```

第一次导入：

```text
version = 1
origin_kind = governance_seed
review_status = approved
```

因为其授权来源是项目治理文件，而不是 LLM。

重复 seed 不产生 version 2。

Ontology 文件发生实质变化：

```text
ONTOLOGY_CHANGE
```

必须先取得用户批准。

---

# 22. Candidate Generator

模块：

```text
knowledge_ingest_decider
```

负责判断结构化对象是否值得产生 GraphChange candidate。

输入只能来自已存在结构化对象：

```text
Event
Claim
ResearchFinding
CompetitiveFactor
Catalyst
RiskFactor
BusinessSegment
CompanyProfile
Document-derived Evidence
```

不得：

```text
直接读取 Markdown
→ 建图
```

不得：

```text
网页全文
→ 绕过 RawItem/Evidence
→ 建图
```

---

# 23. LLM 路由

运行时正常关系候选：

```text
Flash first
```

满足以下任一条件：

```text
multi-hop > 3
high-grade source conflict
cross-industry reasoning
ontology implication
candidate conflicts with active graph
Flash validation failure >= 2
```

允许 Pro。

但：

```text
ontology modification
relation semantics modification
core knowledge rule modification
```

不是普通运行时 Pro 任务。

它们属于：

```text
human-governed architecture change
```

必须先取得用户批准。

---

# 24. Knowledge Context Builder

实现：

```text
knowledge_context_builder
```

输入：

```text
entity/node
as_of
max_depth
relation filters
```

输出必须区分：

```text
FACT
MODEL_INFERENCE
GOVERNANCE
```

默认：

```text
max_depth <= 2
```

超过 2 跳需显式请求。

不得因为图上存在路径就写：

```text
A 受益于 B
```

路径存在不等于因果成立。

---

# 25. 查询必须支持历史 as_of

例如：

```text
research knowledge query \
  --node company:xxx \
  --as-of 2026-01-01T00:00:00+08:00
```

必须返回该时间点有效版本。

不得始终返回当前最新版本。

---

# 26. CLI 第一版

至少提供：

```text
research knowledge seed
research knowledge candidates
research knowledge review-export --change-id <uuid>
research knowledge review-import --file <path>
research knowledge apply --change-id <uuid>
research knowledge query --node <node_id> --as-of <iso>
research knowledge history --node <node_id>
```

写操作必须支持：

```text
--dry-run
```

其中：

```text
seed
review-import
apply
```

的 dry-run 必须零副作用。

---

# 27. M0：规范冻结

**执行模型：DeepSeek V4 Pro**

只允许：

```text
docs/
config/knowledge_policy.yaml
```

任务：

1. 重新读取全部权威规范。
2. 将本任务书落库。
3. 在 `DECISIONS.md` 追加 Phase 5 正式决策。
4. 明确：
   - LLM 不可直接写 active graph；
   - Governance seed 特例；
   - GraphNode / GraphEdge 正式契约；
   - 人工 review gate；
   - SQLite 为权威持久化；
   - JSON 为 deterministic export；
   - SOURCE_OPINION / HYPOTHESIS 不直接进入 active graph。
5. 更新 NEXT_PHASE：
   - Phase 5 的设计与工程前置条件可被冻结为满足；
     只有用户另行明确授权后才可进入工程实施，
     且不得提前标 PASS。
6. CURRENT_STATE：
   - Phase 5 `IN_PROGRESS` 只能在用户正式授权后写入。

禁止实现 Python。

验收：

```text
docs only
0 business code changes
```

Commit：

```text
docs: freeze phase5 knowledge graph taskbook
```

---

# 28. M1：Graph contracts

**执行模型：DeepSeek V4 Pro**

新增：

```text
schemas/graph_node.schema.json
schemas/graph_edge.schema.json
schemas/graph_change_proposal.schema.json
schemas/graph_review.schema.json
```

修改：

```text
schemas/graph_change.schema.json
src/research_os/models/core.py
src/research_os/models/__init__.py
schema registry / validator list
tests/contracts/
tests/unit/test_model_contract.py
```

禁止：

```text
DB migration
candidate generator
LLM
apply engine
```

目标：

```text
Schema ↔ Pydantic
```

完全一致。

---

# 29. M2：Persistence and ontology seed

**执行模型：Flash 实现，Pro 做里程碑审查**

实现：

```text
migration
Database mappings
graph repository
ontology loader
seed command
```

要求：

```text
idempotent
transactional
no LLM
```

攻击测试：

- second seed produces no duplicate;
- unknown node type fails;
- unknown relation fails;
- Company governance seed rejected;
- version gap rejected;
- dry-run zero writes.

---

# 30. M3：GraphChange candidate pipeline

**执行模型：Flash 默认；复杂关系 Pro**

实现：

```text
GraphChangeProposal
→ Validator
→ deterministic GraphChange builder
→ candidate persistence
→ Markdown candidate renderer
```

必须验证所有 Evidence ID 真实存在。

禁止 candidate 自动 approved。

---

# 31. M4：Knowledge Validator

**执行模型：DeepSeek V4 Pro**

建立独立机械规则，例如：

```text
KGV-001 ...
```

至少覆盖：

- Schema；
- node identity；
- relation allowlist；
- source/target existence；
- evidence existence；
- evidence entity relevance；
- Evidence time；
- source tier；
- governance seed scope；
- FACT / MODEL_INFERENCE 边界；
- conflict blocking；
- review status；
- version monotonicity；
- as_of；
- duplicate relation；
- self-loop policy；
- retired node reference；
- candidate hash；
- stale-review detection。

不得把 Validator 交给 LLM。

---

# 32. M5：Human review

**执行模型：Flash**

实现：

```text
review-export
review-import
GraphReview
Markdown parser
candidate hash
```

攻击测试：

- zero checkbox rejected；
- two checkbox rejected；
- missing reviewer rejected；
- LLM/system reviewer rejected；
- candidate modified after export rejected；
- approved_with_changes without patch rejected；
- malformed patch rejected；
- deferred cannot apply；
- rejected cannot apply。

---

# 33. M6：Deterministic Apply Engine

**执行模型：DeepSeek V4 Pro**

这是 Phase 5 高风险核心。

必须：

```text
transactional
idempotent
validated
version-aware
conflict-aware
```

严禁 LLM 参与最终写入决定。

攻击测试：

- candidate without review cannot apply；
- approved candidate applies once；
- second apply idempotent；
- evidence deleted/missing after review rejects；
- graph changed after review → stale review rejects；
- invalid version rejects；
- partial transaction rollback；
- concurrent conflicting candidate rejects。

---

# 34. M7：Supersede / expire / history

**执行模型：Flash，Pro 审查时间语义**

实现：

```text
modify_attribute
retire_edge
retire_node
superseded
expired
history query
```

不得删除旧版本。

攻击测试覆盖未来时间、历史查询和 valid interval。

---

# 35. M8：Query + knowledge_context_builder

**执行模型：Flash**

实现：

```text
node query
edge query
historical as_of
depth-limited traversal
knowledge_context_builder
```

输出明确：

```text
governance
facts
model_inferences
limitations
conflicts
evidence_ids
```

查询代码本身不得使用 LLM。

---

# 36. M9：Phase 2/3/4 Integration

**架构设计：V4 Pro**

**普通 glue code：Flash**

只建立：

```text
existing structured objects
→ GraphChange candidate
```

不得改变：

```text
Phase 2
Phase 3
Phase 4
```

已验收结论。

晨报、异动和个股研报永远不能直接：

```text
→ active graph
```

只能：

```text
→ graph_candidate
```

---

# 37. M10：端到端验收

必须至少包含以下四类。

## Case A：Governance seed

验证：

```text
AI_hardware
semiconductor
AI_software
```

骨架确定性导入、重复执行幂等。

## Case B：Evidence-backed FACT

至少一个真实 A 股公司结构事实：

```text
official Evidence
→ GraphChange candidate
→ Markdown review
→ human approve
→ apply
→ active GraphEdge
→ query
```

必须完整反查 Evidence。

## Case C：MODEL_INFERENCE

产生一个明确：

```text
assertion_type = MODEL_INFERENCE
```

的产业关系候选。

必须证明：

- 不会渲染成 FACT；
- 不会自动批准；
- 人工审批后仍保持 MODEL_INFERENCE 标签。

## Case D：Conflict / rejected path

制造或使用两个不可兼容证据。

必须：

```text
conflicts != []
```

并证明：

```text
apply rejected
```

或人工：

```text
deferred/rejected
```

不得通过删掉一方 Evidence 获得 PASS。

---

# 38. Phase 5 完成定义

只有同时满足：

```text
GraphNode / GraphEdge formal contracts
GraphChangeProposal
GraphReview
versioned persistence
ontology seed
candidate pipeline
Knowledge Validator
Markdown human review
deterministic apply
history / expiration
historical query
knowledge_context_builder
Phase2/3/4 candidate integration
4-class E2E
Offline CI PASS
independent acceptance PASS
```

才能：

```text
Phase 5 = PASS
```

测试数量本身不能改变状态。

---

# 39. Git / PR 策略

Phase 5 不使用一个超大 PR。

拆成：

```text
PR 5A
phase5/graph-foundation
M0-M5

PR 5B
phase5/graph-apply-query
M6-M8

PR 5C
phase5/pipeline-integration
M9-M10
```

每个 PR：

```text
branch
→ commits by milestone
→ push
→ Offline CI
→ independent review
→ squash merge
```

下一 PR 必须从上一 PR 已 merge 的 master 创建。

---

# 40. 每一轮 DeepSeek 指令必须重复的命令

任何一个里程碑开始时，不得省略：

```bash
git fetch origin
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/master
git log -5 --oneline
```

然后重新读取：

```text
AGENTS.md
docs/engineering-guide.md
docs/contracts/schema-model-contract.md
docs/project-state/DECISIONS.md
docs/project-state/CURRENT_STATE.md
docs/project-state/NEXT_PHASE.md
docs/project-state/KNOWN_LIMITATIONS.md
docs/tasks/phase5-industry-knowledge-graph.md
config/knowledge_policy.yaml
```

涉及 Schema 时额外读取：

```text
schemas/graph_change.schema.json
相关新 Schema
src/research_os/models/core.py
```

涉及 DB：

```text
src/research_os/storage/
全部 migrations 列表
```

涉及 LLM：

```text
src/research_os/llm/
config/model_routing.yaml
config/llm_providers.yaml
```

禁止依据上一轮聊天记忆重建这些信息。

---

# 41. 每轮结束必须运行

针对性测试之后，里程碑结束必须：

```bash
python -m pytest
python -m research_os.cli.main validate
python -m compileall -q src tests
git diff --check
git status --short
```

推送 PR 后：

```text
Offline CI must be SUCCESS
```

才能：

```text
READY_FOR_REVIEW
```

---

# 42. 每轮固定报告

必须报告：

```text
BASE_SHA:
BRANCH:
HEAD:

THIS_ROUND_SCOPE:
OUT_OF_SCOPE:

IMPLEMENTED:

FILES_CHANGED:

SCHEMAS_CHANGED:

MIGRATIONS_CHANGED:

TESTS_ADDED:

TARGETED_TEST_RESULT:

FULL_PYTEST_RESULT:

SCHEMA_RESULT:

COMPILEALL_RESULT:

DIFF_CHECK_RESULT:

OFFLINE_CI_RESULT:

LLM_ROUTE:
Flash calls:
Pro calls:
Escalation reasons:

KNOWN_LIMITATIONS:

DISCOVERED_NOT_IMPLEMENTED:

WORKTREE_STATUS:

READINESS:
```

没运行：

```text
NOT_RUN
```

禁止猜测 PASS。

---

# 43. 强制停止条件

出现以下任一情况立即停止当前实现：

```text
BLOCKED_BY_SPEC
```

- 需要新增 node type；
- 需要新增 relation type；
- 需要改变 FACT 定义；
- 需要允许 Opinion 自动入图；
- 需要允许模型直接 approve；
- 需要改变 core_write_requires_review；
- 需要复杂图数据库；
- 需要修改现有 Phase 2/3/4 研究规则；
- 需要改变来源等级政策；
- 需要改变输出禁止项；
- 需要自动批准本体变更。

停止后只报告：

```text
缺失决策
涉及文件
为什么当前任务书无法解决
建议的设计选项
```

不得自行选一个实现。

---

# 44. 阶段状态边界

任务书落库：

```text
≠ Phase 5 PASS
```

用户授权实施后：

```text
Phase 5 = IN_PROGRESS
```

M0-M10 全部完成：

```text
Phase 5 = READY_FOR_INDEPENDENT_ACCEPTANCE
```

只有独立验收签字：

```text
Phase 5 = PASS
```

不得自行提前改变状态。