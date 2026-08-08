# 关键设计决策（DECISIONS）

> 不可违反的研究与工程决策。变更需走正式评审，不得私自修改。

## 1. 四个监测方向并列，不得改造成上下级关系

7×24快讯 / 财经媒体深度文章 / 社区舆情 / 机构动向 为并列的 `monitoring_channel`，
与宏观/产业/市场/公司等信息分类相互独立。一个信息对象同时具有
`monitoring_channel` 与 `classification_path`（任务 5 节）。

## 2. A 股为主体

系统以 A 股市场研究为主体（晨报窗口、分类树、来源注册表均围绕 A 股）；
港股/美股/商品/利率/汇率作为市场分类的子类存在，当前数据能力不足时明确降级。

## 3. 不保存全文

所有采集器存储策略为 `metadata_and_excerpt`：仅存标题/URL/发布者/作者/发布时间/
获取时间/来源原始 ID/内容哈希/最小摘录/结构化字段。临时正文按策略清理，
禁止全文入库（工程指南 + Phase 1 任务约束）。

## 4. 不输出目标价和交易建议

任何报告不得输出目标价、买入/卖出/增持/减持评级、仓位建议、跟随操作等。
由机械校验器（FORBIDDEN_WORDS）强制拦截，测试锁定，引文正常词语不误伤
（免责声明行"不构成目标价..."是任务书要求的固定文案，不视为违规）。

## 5. 未覆盖不等于没有信息

禁止把"没有采集能力"写成"该方向没有信息"。四方向覆盖状态必须区分：
covered / partial / manual_only / not_covered / source_failure / 窗口内确实无有效信息。
验证器强制检查（任务 5.2、22.3）。

## 6. 快照和日线严格分离

实时快照（last_price/observed_at）与历史日线（trade_date/close）是两个独立契约。
sina_quote 只能作为实时快照源；日线 primary/secondary 为空，fallback=manual_import；
快照不得映射为历史 close、不得写入日线表（Phase 1.1，任务 3 节）。

## 7. 事实、观点、推断严格分离

Claim 类型固定：FACT / SOURCE_OPINION / MODEL_INFERENCE / HYPOTHESIS / UNKNOWN / CONFLICT。
FACT 要求法定披露/公司官方/政府监管/可验证原始文件；SOURCE_OPINION 必须记录说话者/
出处/时间/对象/论据；MODEL_INFERENCE 必须说明依据与不确定性；
CONFLICT 不得通过选择更符合市场走势的一方来消除（任务 9 节）。

## 8. 默认 Flash、复杂任务升级 Pro

模型路由：默认 deepseek-v4-flash；满足升级条件（高等级来源冲突、影响链>3跳、
Flash 连续两次未通过校验、重大事件分类争议、簇内关键数值不一致、
跨多产业链影响判断）才允许升级 deepseek-v4-pro。
晨报一般任务不得默认使用 Pro；确定性任务不使用模型（任务 14 节、21 节）。

## 9. 当前规则回退不得伪装成模型推理

LLM 客户端未接入期间，新颖性/影响路径/预期差/聚类辅助以确定性规则实现，
必须如实记录：

```yaml
model_route:
  mode: deterministic_fallback
  llm_called: false
  intended_default_model: deepseek-v4-flash
  limitation: semantic_llm_modules_not_connected
```

不得把规则结果表述为"模型判断"；文档中事件聚类称"事件相似聚类（确定性第一版）"。
Phase 3 起统一 LLM Client 已实现：真实 Provider 未配置时同样诚实回退；
已调用但失败时 `llm_called: true` + `failure_stage` 如实记录（任务书 12.5）。

## 10. 确定性逻辑必须用代码，不得交给 LLM

时间/哈希/迁移/幂等/Schema 校验/日期计算/窗口/否决/权重/阈值/强制纳入/惩罚
均为确定性代码（工程指南 6.3、任务 14.1）。Phase 3 补充：异动指标、robust Z、
分位、severity、基准评分、原因评分权重与惩罚、时间因果资格、Validator 33 条
全部为确定性代码（任务书 7、8、10、11、16 节）。

## 11. 主备失败必须显式降级

数据需求主源失败后使用备源，再失败使用 fallback（manual_import/manual_inbox）；
全部失败返回 `insufficient_data` + missing_fields + warnings；
备源结果不得伪装成主源；空响应不得解释为"没有事件"（任务 8 节）。

## 12. 异动归因必须区分无法归因与证据不足（Phase 3 任务书 11.6）

- 异动事实成立但无法归因 -> `UNEXPLAINED_MOVE`（合法输出，不得生成
  "可能是资金推动"等兜底话术）
- 行情事实本身不能成立 -> `INSUFFICIENT_EVIDENCE`（不是 UNEXPLAINED_MOVE）
- 未解决高等级来源冲突 -> `SOURCE_CONFLICT`（保留冲突双方）
- 多原因共同作用 -> `MULTI_CAUSE`（有明确共同作用门槛）

## 13. 防事后选择（Phase 3 任务书 8.3）

- 基准候选 `pre_window_subtotal >= 45` 才可合格（窗口前已知关系维度）
- 概念基准 `relationship_valid_from <= window_start`
- `information_cutoff` 等于或早于异动窗口开始
- 异动期联动只用于确认，不得改变概念历史有效期

## 14. 时间因果硬规则（Phase 3 任务书 10）

- 报道发布时间晚于异动开始，默认不能是直接触发
- 收盘后发布的"原因分析"属于 `after_the_fact_explanation`
- 窗口前已广泛公开的旧闻无新增变量不得重新标为直接原因
- 同日事件无分钟级先后 -> `UNKNOWN_ORDER`，直接触发置信度上限 medium

## 15. 确定性评分不得按方向自动加减分（Phase 3 任务书 11.3）

股票上涨或下跌方向不得直接给候选新闻加分或减分；方向语义验证属于 LLM 层，
确定性引擎只提供机制覆盖度近似。

## 16. 财务数据采用离线优先混合路径（Phase 4 任务书 5.2）

CSV/JSON/XLSX 人工导入为最低可运行路径；法定公告辅助抽取须实际解析成功才能生成
财务事实；未验证的自动财务接口不得登记为 primary/secondary；离线导入、Manifest
和来源治理阻塞实施，自动来源不阻塞。

## 17. 文档、财务事实、派生指标、研究发现四层分离（Phase 4 决策 2/4/5）

DocumentRecord → DocumentBlock → FinancialFact/Claim/Evidence；
FinancialReport → FinancialFact → FinancialMetric 三层结构；
报告只能引用已进入结构化对象的内容；报告不得先于结构化对象生成；
PDF 文件存在不自动证明抽取数字正确。

## 18. 财务数值使用 Decimal（Phase 4 决策 3/任务书 3.11）

内部计算 Decimal；持久化十进制字符串；区分 null（缺失）/ "0"（报告为零）/
负数（合法原始事实）/ not_applicable / conflict；渲染四舍五入不得回写结构化对象。

## 19. Company 与 Security 分离（Phase 4 决策 6）

Entity(company) → CompanyProfile；Entity(security) → SecurityProfile(company_entity_id)；
EntityType 兼容扩展 `security`；ReportPeriod 不作顶层 Schema（标准字段组合）；
BusinessSegment 作顶层对象。

## 20. 同行冻结和防事后选择（Phase 4 决策 8）

候选宇宙版本 + 评分权重进幂等键；估值前冻结；不得按估值/涨跌结果删除同行；
relationship_valid_from <= information_cutoff；用户 --peer 只增加候选不自动合格；
样本 >=5 完整、3-4 有限、<3 不足。

## 21. 估值仅作观察，无目标价（Phase 4 决策 9）

PE/PB/PS/EV_EBITDA/FCF_Yield/股息率/历史分位/同行分位/敏感性为允许范围；
禁止目标价/合理价值/上涨空间/买卖区间/用行业平均倍数乘预测利润生成目标市值；
DCF/DDM 不实现；负 FCF Yield 允许显示但不得解释为"便宜"。

## 22. 情景预测默认关闭且不得为 FACT（Phase 4 决策 10）

CLI 默认 --include-forecast=false；假设 claim_type 只允许 SOURCE_OPINION/
MODEL_INFERENCE/HYPOTHESIS；model_generated 必须有实际模型调用；无 Provider 时
确定性回退不得伪装成模型假设；每个假设须有来源/期间/驱动/敏感性/置信度/失效条件。

## 23. Phase 3 结果只读（Phase 4 决策 11）

Phase 4 可读 AbnormalMoveRun/AttributionResult/CauseCandidate/CauseEvidenceLink；
不得修改 Phase 3 归因状态、不得把 UNEXPLAINED_MOVE 改成猜测原因、不得改写主次原因；
晨报复用结构化中间产物（CandidateItem/EventCluster/Event/Claim/manual_inbox），
不得只读 Markdown 做摘要。

## 24. 知识图谱仍属 Phase 5（Phase 4 决策 14）

Phase 4 只允许输出 GraphChange 候选、填写 knowledge_coordinates、生成待审核关系建议；
禁止自动批准图谱节点/边、禁止自动写入核心产业图谱、禁止提前实现 Phase 5。

## 25. LLM 不得修改数字或资格（Phase 4 决策 15）

允许模型参与语义候选（业务描述/管理层摘要/产品映射/竞争因素/催化剂/风险/反证/
研究问题/章节草稿）；禁止模型修改财务事实/公式/质量告警/同行资格/估值数值/
删除反证/把缺失写成事实/绕过结构化对象直接形成最终报告；统一经 LlmClient 调用。

## 26. 金融企业指标适用性（Phase 4 决策 3.16）

银行/证券/保险：EV/EBITDA、流动比率、速动比率等通用指标 N/A（合法降级）；
ROIC 对金融企业 not_applicable；周期企业 PE 仅作观察并提示周期位置。

## 27. 报告必须由结构化对象生成（Phase 4 决策 2/3.21）

研报渲染只聚合结构化对象（Findings/Result/Metrics/Segments/Peers/Valuation/...）；
必须章节无论有无数据都显示，缺数据写覆盖状态/缺失字段/不能得出的结论/降级原因；
禁止空章节套话（"公司未来可期"等）。

## 28. 文档权威、统一控制面与 Phase 4 完成定义（2026-08-07）

`docs/engineering-guide.md` 是当前唯一有效工程指南；权威顺序固定为工程指南、正式
决策、阶段任务、CURRENT_STATE、NEXT_PHASE、KNOWN_LIMITATIONS、README。阶段任务
只能细化，不能静默覆盖。指南实质变更须更新版本、日期和变更记录。

首批三个核心场景必须经显式场景注册表和统一 Orchestrator 执行。晨报和 Phase 4 的
关键事实必须保持 RawItem→Evidence→Claim→派生对象→Markdown 血缘。Phase 4 完整成功
采用集中、版本化多维覆盖判定，不再仅看可比年度数量。本决策下达时的结论为：工程基础
PASS、完整研究能力 PARTIAL_SUCCESS、Phase 5 BLOCKED；后续状态变化必须由真实验收
证据和独立签字支持，不能仅以实现或测试数量改变边界。

## 29. Phase 4.1 真实能力补齐边界（2026-08-07）

首个生产 Provider 固定为配置化 `deepseek` 适配器：API Key 只读取
`DEEPSEEK_API_KEY`，OpenAI-compatible Chat Completions Base URL 和 Flash/Pro 模型 ID
只存在于 Provider 配置层。业务 Pipeline 不得旁路 `LlmClient`，真实网络调用必须显式
`--live`，dry-run 优先且不得联网。Provider 故障与业务 Pro 升级分离；每次实际调用计入
共享任务预算并经过统一脱敏。

Phase 4 完整成功所依赖的核心财务事实必须能反查官方原件、DocumentRecord、有效
DocumentBlock/locator、checksum 和官方 URL。普通 CSV、手工金额或无关 S/A 事件不能
提升核心财务来源质量。辅助导入允许人工确认字段映射，但必须保留原值、校正和定位审计。

完整研究能力必须覆盖业务描述、管理层陈述、竞争因素、催化剂、风险、反证和研究问题
七个正式语义任务。Fake Provider、仅配置 Provider、章节非空或模型返回 JSON 均不等价于
真实覆盖。两个真实成功案例和一个预期降级案例已通过执行 Agent 的本地真实验收，当前
结论为 `READY_FOR_INDEPENDENT_ACCEPTANCE`；独立验收签字前 Phase 4 full capability
仍保持 `PARTIAL_SUCCESS`，Phase 5 保持 `BLOCKED`。Phase 4.1 不授权任何 Phase 5 实现。

## 30. Phase 5 产业图谱正式设计决策（2026-08-07）

> 本决策在 Phase 5 正式任务书获批后冻结。任务书批准 ≠ 工程实施授权；
> M1-M10 必须等待用户另行明确授权。

1. **Phase 5 建设目标**是可审计的长期产业知识系统，不是 LLM 自动建图。
2. **核心知识链**：
   `RawItem → Evidence → Claim/Event/ResearchFinding → GraphChangeProposal → GraphChange candidate → Human Review → Deterministic Apply → Versioned GraphNode/GraphEdge`
3. **LLM 不得直接生成 active graph**（禁止 `LLM → active GraphNode/GraphEdge`）。
4. **LLM 不得批准 GraphChange**；审核必须由人工 reviewer 完成。
5. **GraphNode / GraphEdge** 在 M1 通过正式 JSON Schema 契约化；Pydantic 为构造器。
6. **LLM 输出 GraphChangeProposal**；正式 `graph_change_id`、`version`、timestamps、
   `review_status` 等全部由确定性代码生成和分配。
7. **三种认识论分层** `GOVERNANCE / FACT / MODEL_INFERENCE` 必须严格区分：
   query 和 context builder 输出必须标明每条边的 `assertion_type`。
8. **SOURCE_OPINION / HYPOTHESIS** 第一版不得直接进入 active core graph；
   继续保留在 Opinion / Claim / ResearchFinding 层，可用于产生 GraphChange candidate
   但不能直接成为长期事实。
9. **Governance seed** 只允许用于版本控制中已批准的 ontology 骨架
  （`origin_kind = governance_seed`）；Company 等业务事实不得借 governance seed
  绕过 Evidence 要求。
10. **SQLite 是结构化权威持久化**；`graph_nodes`、`graph_edges`、`graph_reviews`、
   `graph_applications` 表为唯一事实源。
11. **JSON 文件**（`knowledge/graph/nodes/`、`knowledge/graph/edges/`）为
   deterministic export；不是第二权威源；禁止人工直接编辑 JSON 后反写数据库。
12. **核心图谱写入继续要求人工审核**（`core_write_requires_review: true`）。
13. **历史版本不得覆盖**：修改产生 version N+1；旧版本保留；
   必须能回答任意历史 as_of 查询。
14. **node type 和 relation allowlist 的变化**属于 human-governed architecture
   change（`ONTOLOGY_CHANGE`）；必须单独经用户批准，不得由工程 Agent 或运行时 LLM
   自行增加。
15. **Phase 5 第一版不引入复杂图数据库**；继续使用 SQLite + JSON + Markdown。
16. **Phase 2/3/4 只能产生 GraphChange candidate**；晨报、异动分析和个股研报永远
   不能直接写入 active graph。
17. **任务书获批 ≠ 工程实施获批**；在用户明确授权 M1 前 Phase 5 保持 `BLOCKED`。
18. **GraphChange 对象**从 Phase 0 候选容器升级为正式变更对象；M1 后 `node` 和
   `edge` 字段必须符合 GraphNode/GraphEdge draft 结构，不再使用 arbitrary dict。

## 31. Phase 5 M1 图谱契约语义冻结（2026-08-07）

> M1 Graph Contracts 已由用户明确授权。本决定冻结 M1 实现必须遵守的语义规则。

1. **GraphNode/GraphEdge 的双重角色**：既是 GraphChange 的 candidate payload 结构，
   也是 apply 后的正式 core graph object。对象级 `review_status` 只允许 `candidate` / `approved`；
   `approved_with_changes` / `deferred` / `rejected` 属于 `GraphReview.decision` 和
   `GraphChange.review_status`，不出现在 core graph object 上。

2. **approved_with_changes 不可原地覆盖**：原始 GraphChange candidate 内容不被 review_patch
   原地修改。规则为：original GraphChange → GraphReview(decision=approved_with_changes)
   → validated review_patch → deterministic replacement GraphChange → NEW graph_change_id。
   `GraphReview.resulting_graph_change_id` 指向新 GraphChange。原始保留。

3. **reviewer 是严格对象**：`{reviewer_type: "human", reviewer_id: non-empty, display_name: string|null}`，
   `reviewer_type` 只能 `"human"`。从 Schema 层阻止 `system`/`llm`/`auto` 冒充。

4. **review_patch 受限 JSON Patch**：仅允许 `add`/`replace`/`remove`。允许的业务路径：
   `/suggested_change`、`/impact_scope`、`/conflicts`、`/verification_points`、
   `/new_evidence_ids`、`/node/name`、`/node/aliases`、`/node/description`、`/node/status`、
   `/node/valid_from`、`/node/valid_to`、`/node/evidence_ids`、`/edge/attributes`、
   `/edge/valid_from`、`/edge/valid_to`、`/edge/confidence`、`/edge/evidence_ids` 及子路径。
   禁止 patch 系统治理字段（ID、type、version、origin、review、created_at 等）。

5. **JSON Schema `$ref` 本地解析**：GraphChange Schema 复用 `graph_node.schema.json` 和
   `graph_edge.schema.json` 的 `$ref`。validator 必须建立本地 schemas/ registry，离线解析，
   不发起 HTTP。不得复制内联 Node/Edge schema。

6. **Contract tests scope**：M1 只测试 structural validation（type、enum、required、
   additionalProperties、信心范围、时间格式、proposal 防污染字段、patch 路径白名单）。
   不测试 DB existence、entity equality、version monotonicity、graph state conflict（这些属于 M2-M6）。

## 32. Phase 5 M2 持久化与 Governance Seed 语义冻结（2026-08-07）

> 本决定在 M2 实现完成后冻结。M2 PASS 不自动授权 M3。

1. **SQLite 为结构化权威持久化**；graph_nodes / graph_edges / graph_reviews / graph_applications
   全部 append-only，绝不 UPDATE。

2. **GraphRepository 为唯一写入路径**：`Database.upsert()` 不得接收 `GraphNode` / `GraphEdge` /
   `GraphReview`；generic TABLES / PK_COLUMNS 不收录 Phase 5 图谱表。

3. **复合版本主键**：`(node_id, version)` / `(edge_id, version)`。版本规则：
   首个版本为 1；后续单调递增 N+1；gap 拒绝。
   同 (id, version) + 同 canonical payload = IDEMPOTENT_NOOP；
   同 (id, version) + 异 canonical payload = IMMUTABLE_VERSION_CONFLICT。

4. **Governance seed 节点类型仅限 Industry / IndustrySegment**；禁止 Company 等业务类型
   借 governance seed 绕过 Evidence。v1 关系仅限 BELONGS_TO，
   方向为 industry_segment → industry（child → parent）。

5. **本体 YAML 严格顶层契约**：
   `{ontology_id, ontology_version, seed_created_at, nodes, edges}`。
   `ontology_id == "industry_graph"`，`ontology_version == 1`，
   `seed_created_at` 必须显式 ISO。额外/缺失字段均为 `OntologyLoadError`。

6. **Genance governance edge ID**：
   `"edge:governance:" + sha256(source + "|" + relation + "|" + target)` lowercase hex。

7. **确定性 seed**：零 LLM / 零网络 / 零随机数 / 零动态时间戳。
   任意两次 `load_ontology()` 对同一文件产生完全相同的 Pydantic model 列表。

8. **全量 preflight + 单事务**：先校验本体完整性 → 构造全部对象 → Schema 验证全部 →
   计算 canonical payload → 预检全部 DB 冲突 → 若有冲突则 0 writes → 单事务批量写入。
   不允许逐条写后才发现冲突。

9. **Canonical JSON**：`json.dumps(obj.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))`。
   用于幂等比较和 payload 存储。

10. **dry-run 零副作用**：DB 不存在时不创建 DB；DB 存在时 read-only；
    逐对象 canonical preflight 检测冲突并报告；报告包含 `ontology_sha256` / `migration_required` /
    `conflicts` 等完整字段。

11. **M2 严格不实现**：GraphChangeProposal builder、candidate pipeline、review parser、
    apply engine、historical query、knowledge context builder、JSON mirror export、
    Phase 2/3/4 integration。M3-M10 全部未授权。

## 34. Phase 5 M4 Knowledge Validator 语义冻结（2026-08-08）

> 本决定在 M4 实现启动时冻结。M4 完成不自动授权 M5。
>
> **基线**: M3_ACCEPTED_SHA=242e039, M3_CI=31240709634, M3_TESTS=1480/5 skipped, M3_SCHEMAS=55

### KGV 规则索引（19 条代码级验证规则）

| 规则 | 语义（一行） |
|---|---|
| **KGV-001** | Schema 校验：GraphChange/Node/Edge/Evidence/RawItem 全部通过对应 JSON Schema |
| **KGV-002** | Entity 身份：node_id 存在且 entity_type 与 GraphNodeType 一致，Entity payload 通过 Schema |
| **KGV-003** | 关系允许域：relation 属于 18 个允许值之一 |
| **KGV-004** | 端点存在性：edge 的 source/target node_id 在 graph_nodes 中存在 |
| **KGV-005** | Evidence 存在：所有引用 evidence_id 在 evidence 表存在且 payload 通过 Schema；new_evidence_ids ⊆ candidate evidence_ids |
| **KGV-006** | Evidence 实体覆盖：使用 new_evidence_ids（仅新证据）→ RawItem → entities 必须覆盖 node 或 edge 端点 |
| **KGV-007** | 时间顺序：published_at ≤ retrieved_at；review 阶段 retrieved_at ≤ reviewed_at |
| **KGV-008** | 来源等级：使用 new_evidence_ids。核心结构关系 FACT 至少一个 S/A；其他 FACT 至少一个 S/A/B；MODEL_INFERENCE 无地板 |
| **KGV-009** | 本体治理范围：Industry/IndustrySegment 只能通过 governance_seed，不能通过普通 candidate |
| **KGV-010** | 认知边界：GOVERNANCE 禁止出现在 edge；MODEL_INFERENCE 必须有真实 Evidence |
| **KGV-011** | 冲突阻止：conflicts 非空阻止 apply 但不阻止 review |
| **KGV-012** | 审核状态：candidate 必须 review_status=candidate + reviewed_at=null；GraphReview 必须 reviewer_type=human + reviewer_id 非空 + reviewed_at ≥ created_at |
| **KGV-013** | 版本单调：首个版本=1，后续=N+1，不允许 gap |
| **KGV-014** | 显式截止：as_of 必传且合法 ISO；Evidence.published_at ≤ as_of；valid_from ≤ valid_to |
| **KGV-015** | 重复关系：add_edge 不能重复已有 triple；modify/retire 必须有且仅有一个身份 |
| **KGV-016** | 自环拒绝：source_node_id == target_node_id 对全部 18 个 relation 拒绝 |
| **KGV-017** | 退役节点引用：edge 端点最新版本 status 必须为 active |
| **KGV-018** | Candidate hash：sha256(canonical JSON of model_dump) 用于防篡改 |
| **KGV-019** | 过期审核：对比 current_knowledge 与当前持久化图谱状态 canonical baseline（非仅 version）；在 validate_review 阶段运行 |

### 关键实现决策
- **KGV-008 使用 new_evidence_ids**：仅新证据决定来源等级，历史证据不合并计算
- **KGV-019 使用 current_knowledge canonical baseline**：对比 current_knowledge 内容与最新持久化 node/edge payload，非仅版本号比较
- **Validator 公共 API fail-closed**：接受 dict 或 model，内部先 normalize（raw→schema→Pydantic→dump→schema），任何阶段失败均返回 SCHEMA_INVALID
- **确定性结果**：issues 按 (rule_id, code, message) 排序，checked_rule_ids 准确、唯一、稳定顺序
- **零写入**：所有 validate_* 调用不产生任何 DB INSERT/UPDATE/DELETE

## 33. Phase 5 M3 GraphChange Candidate Pipeline 语义冻结（2026-08-07）

> 本决定在 M3 实现启动时冻结。M3 完成不自动授权 M4。

1. **M3 输入只能来自已持久化、已结构化的对象**：Event、Claim、ResearchFinding、
   CompetitiveFactor、Catalyst、RiskFactor、BusinessSegment、CompanyProfile、Evidence。
   禁止 Opinion、RawItem、Markdown、网页正文、任意未持久化对象直接输入。

2. **LLM 只能生成 GraphChangeProposal**；禁止 LLM 生成 graph_change_id、node_id、
   edge_id、version、review_status、reviewed_at、created_at、active status。

3. **Evidence 存在性与子集硬门禁**：Proposal 中 source_object_ids ⊆ 实际输入 ID；
   new_evidence_ids ⊆ 实际 Evidence context 且 SQLite 中真实存在。任一不满足 → PROPOSAL_REJECTED。

4. **GraphChange builder 为确定性代码**；LLM Proposal → deterministic validate →
   deterministic build → deterministic persist。

5. **Ontology 运行时保护**：普通 candidate pipeline 禁止对 Industry/IndustrySegment
   执行 add/modify/retire。此类操作返回 ONTOLOGY_CHANGE_REQUIRES_HUMAN_GOVERNANCE。

6. **实体身份解析**：add_node 必须从输入结构化对象中提取确定 Entity ID（entities 表）。
   Company 的 GraphNode.node_id == Entity.entity_id。模糊匹配、LLM 猜测、name hash 均不可接受。

7. **GraphChange candidate 是 immutable audit object**：INSERT ONLY，同 ID 同 payload =
   IDEMPOTENT_NOOP，同 ID 异 payload = IMMUTABLE_CANDIDATE_CONFLICT。
   Generic Database.upsert(GraphChange) 被机械阻断。

8. **Candidate 审查状态**：review_status = candidate，reviewed_at = null。
   M3 永远禁止自动 approved。

9. **Markdown 只是 candidate review artifact**，不是权威数据源。

10. **dry-run 零写**：0 graph_changes writes，0 candidate Markdown writes，
    0 candidate directory creation。即使调用 LLM 也不得写候选 DB/文件。

11. **M3 不实现 M4（Knowledge Validator）、M5（Human Review）、M6（Apply Engine）**。
    M4-M10 全部未授权。

## 35. Phase 5 M5 Human Review Workflow 语义冻结（2026-08-08）

> 本决定在 M5 实现启动时冻结。M5 完成不自动授权 M6。
>
> **基线**: M4_ACCEPTED_SHA=20b7a15, M4_TESTS=1611/5 skipped, M4_SCHEMAS=55, DB v6

### M5 核心能力

1. **review_export**: 将 GraphChange candidate 渲染为冻结 13-heading Markdown 审阅文件，包含 candidate_hash、Reviewer 模板、4 个审核选项 checkbox。
2. **review_parser**: 解析填写后的 Markdown，fenced-block 内容不解析为 heading/checkbox；13 个冻结标题严格顺序且必须出现一次。
3. **JSON Patch 应用器**: 受限 RFC6902（add/replace/remove）；路径白名单由 graph_review.schema.json 定义；阻止 identity/type/version/relation/system 字段修改。
4. **ReviewWorkflow**: 协调 export/import 全流程；deterministic GraphReview ID（UUID5）；approved_with_changes 通过 patch 应用生成 deterministic replacement GraphChange（UUID5）；approved/deferred/rejected 仅持久化 GraphReview。
5. **原子持久化**: 单事务内完成 GraphReview + replacement GraphChange（如适用）写入。
6. **幂等回放**: 相同输入重复执行产生相同结果，不创建重复记录。

### 冻结 Markdown 格式（13 headings）

```
# 图谱变更候选
## GraphChange ID  (含 candidate_hash)
## 变更类型
## 当前知识
## 新证据
## 建议变更
## 影响范围
## 冲突信息
## 验证节点
## 审核选项     (4 checkboxes: 批准/修改后批准/暂缓/拒绝)
## Reviewer      (template)
## Review Notes
## Approved Patch
```

### 关键实现决策（M5-R2 冻结修正）

> 本节由 M5-R2 Final Contract Gate 修正。旧记录（review ID 只基于 candidate、
> `replacement:` 前缀、replacement review_status=approved）是未验收实现期写入的
> 错误 M5 语义，已被删除，不另立模糊决策覆盖。

- **GraphReview ID（review-intent 绑定）**:
  `UUID5(DNS, "graph-review:" + sha256(canonical review intent))`。
  review intent 为完整人工审核意图：
  `graph_change_id / decision / reviewer / reviewed_at / candidate_hash /
  review_patch / notes`；reviewer 使用完整 deterministic representation
  （reviewer_type / reviewer_id / display_name）。
  canonical intent = `json.dumps(intent, ensure_ascii=False, sort_keys=True,
  separators=(",", ":"))`。
  同一 candidate 的不同 decision / reviewer / reviewed_at / notes / patch
  产生不同 review_id，形成不同 audit records。
- **Replacement GraphChange ID（冻结协议）**:
  `UUID5(DNS, "graph-review-result:" + review_id)`。
  删除旧前缀 `"replacement:" + review_id`。
- **approved_with_changes replacement 保持 candidate-shaped**:
  replacement GraphChange 顶层 `graph_change_id = resulting_graph_change_id`、
  `review_status = candidate`、`reviewed_at = null`、
  `created_at = GraphReview.reviewed_at`；
  node/edge：`originating_graph_change_id = resulting_graph_change_id`、
  `created_at = GraphReview.reviewed_at`、`review_status = candidate`、
  `last_reviewed_at = null`。
  禁止修改 change_type / current_knowledge / node_id / node_type / version /
  origin_kind / edge_id / source_node_id / relation / target_node_id /
  assertion_type。禁止给 GraphChange 顶层添加 originating_graph_change_id。
  原 candidate 永远 immutable。
- **candidate hash 唯一 authority**:
  `KnowledgeValidator.compute_candidate_hash()`（M4）。M5 业务代码与测试不得
  持有第二套 candidate hash 算法；review-import 重算 hash 同样调用该方法。
- **review_import 流程**: parse → load GraphChange（Schema-first）→ hash verify
  → build GraphReview（Schema-first: raw → graph_review.schema → Pydantic →
  model_dump → graph_review.schema）→ M4 validate_review → patch apply（如适用）
  → replacement build（Schema-first）→ M4 validate_candidate → atomic persist
  （approved_with_changes：单事务写入 replacement + GraphReview，all or nothing）。
- **review_export 流程**: load persisted candidate → raw Schema → Pydantic →
  dump Schema → candidate hash（M4 authority）→ Evidence load/validate
  （fail-closed，任何 missing/invalid 均 ERROR）→ render Markdown →
  file conflict preflight → deterministic write
  （`knowledge/candidates/{graph_change_id}.md`）。
  文件不存在 → 写入；bytes 相同 → idempotent_noop；M3 untouched template →
  deterministic upgrade；已有人类 edit → `REVIEW_EXPORT_FILE_CONFLICT` 不覆盖。
  dry-run 执行完整预检但 0 file writes / 0 mkdir。
- **Approved/Deferred/Rejected**: 持久化 GraphReview 但不修改原 candidate；
  Approved Patch 只允许空 / 空白 / 冻结占位符，任何其他内容均 INVALID_REVIEW。
- **Approved_with_changes**: 持久化 GraphReview + 确定性 replacement
  GraphChange（candidate-shaped，见上）。
- **ImportResult eligibility**: ok / dry_run / idempotent_noop 全部报告真实
  `candidate_hash` / `review_eligible` / `apply_eligible`。
  `review_eligible=true` 且 `apply_eligible=false`（conflict / stale /
  deferred / rejected）仍可持久化合法人工审核记录——apply_eligible 不是
  review-import 门禁，M6 才决定能否 apply。
- **approved_with_changes 幂等回放**: 同一 review 重复 import 时 GraphReview
  idempotent_noop，但必须确认 replacement GraphChange 存在且 canonical
  payload 与预期一致；缺失 → `REPLACEMENT_MISSING`，payload 不同 →
  `IMMUTABLE_CANDIDATE_CONFLICT`，均不返回幂等成功。
- **Dry-run**: 完整预检（parse → load → verify → validate → patch →
  replacement build），零 DB 写入。

### 不变性保证

- 原始 GraphChange candidate 永不修改（INSERT ONLY，不可变）。
- Replacement 的 node/edge 的 `originating_graph_change_id` 指向 replacement
  GraphChange ID（= resulting_graph_change_id）。溯源链为：
  original candidate → GraphReview（resulting_graph_change_id）→ replacement。
- GraphReview 的 resulting_graph_change_id 指向 replacement
  （仅 approved_with_changes 时非 null）。

### M5 严格不实现

- M6 Apply Engine（将 approved replacement 写入 graph_nodes/graph_edges）
- 自动批准、自动应用
- 任何 GUI 或 Web 界面
- 批量审批
- M7-M10 全部未授权

## 36. Phase 5 M6 Deterministic Apply Engine 语义冻结（2026-08-08）

> 本决定在 M6 实现启动时冻结，经用户明确授权。M6 完成不自动授权 M7。
>
> **基线**: PR5A 已 merge（master=`4b0b8f7`），M5_ACCEPTED_SHA=`92649a7`，
> M5_CI=`31251491357`（1725 passed / 5 skipped / 0 xfail / 55/55 schemas），
> DB v6。PR5B branch：`phase5/graph-apply-query`（M6-M8）。

### 36.1 范围与运行时

1. **M6 只 apply `add_node` / `add_edge`**。`modify_attribute` / `retire_edge` /
   `retire_node` 必须返回 `APPLY_REJECTED` + `CHANGE_TYPE_REQUIRES_M7`，0 writes。
   M7 正式负责 modify / retire / superseded / expired / history。禁止提前实现 M7。
2. **运行时 ZERO LLM / ZERO Provider / ZERO network**。review selection、
   candidate hash、version、conflict、stale detection、apply decision、DB write、
   idempotency 全部确定性代码，严禁模型参与。
3. **M6 不新增 Schema、不新增 migration、不修改 006 migration、DB 保持 v6**。
   使用已有 `graph_applications` 表（application_id / graph_change_id /
   review_id / idempotency_key / payload / applied_at）。
4. **M6 不实现 JSON mirror export**（knowledge/graph/nodes|edges|history
   主动 export 属于 M7/M8）。SQLite 权威 apply + GraphApplication audit。

### 36.2 输入语义

5. **`--change-id` 是 original reviewed GraphChange ID**，不是默认 replacement ID。
   - `approved`：`effective_graph_change_id = original graph_change_id`
   - `approved_with_changes`：`effective_graph_change_id =
     GraphReview.resulting_graph_change_id`
6. **GraphReview selection（禁止自动策略）**：
   - 有 `--review-id`：加载精确 review，必须 `review.graph_change_id ==
     --change-id`，否则 `REVIEW_NOT_FOUND` / `REVIEW_CHANGE_MISMATCH`。
   - 无 `--review-id`：读取该 original GraphChange 的全部 GraphReview。
     0 条 → `REVIEW_REQUIRED`；恰 1 条 → 使用；>1 条 distinct →
     `AMBIGUOUS_REVIEW_SELECTION`（用户必须显式 `--review-id`）。
   - 禁止 latest wins / approved wins / highest timestamp wins / first row wins。
7. **Review 必须 Schema-first**：raw `graph_review.schema` → GraphReview →
   model_dump → `graph_review.schema`。任何 DB/JSON/Schema/Pydantic 失败 →
   `APPLY_REJECTED`，不得 silent pass。
8. **Decision gate**：仅 `approved` / `approved_with_changes` 允许继续；
   `deferred` / `rejected` → `APPLY_REJECTED` + `NON_APPLICABLE_REVIEW_DECISION`，
   0 writes。
9. **Original GraphChange 必须 Schema-first**：raw `graph_change.schema` →
   GraphChange → model_dump → `graph_change.schema`。任何失败 →
   `APPLY_REJECTED`。不得从 Markdown 重建（Markdown 在 M6 NOT AUTHORITATIVE）。

### 36.3 approved 路径

10. `decision = approved` 必须 `review_patch == []` 且
    `resulting_graph_change_id == null`（GraphReview Schema + M6 再确认）。
    effective GraphChange = original。执行
    `validator.validate_apply_preflight(original_gc, review, as_of=applied_at)`，
    必须 `structural_ok=true`、`review_eligible=true`、`apply_eligible=true`，
    否则 `APPLY_REJECTED`。

### 36.4 approved_with_changes 路径

11. `decision = approved_with_changes` 必须 `review_patch >= 1` 且
    `resulting_graph_change_id != null`。
12. **Deterministic linkage**：`expected_resulting_id =
    UUID5(DNS, "graph-review-result:" + review_id)`；必须
    `review.resulting_graph_change_id == expected_resulting_id`，否则
    `REPLACEMENT_ID_MISMATCH`。
13. **Replacement 重新构造验证**：不得只相信 persisted replacement，不得复制
    第二套 patch/replacement 算法。将 M5 deterministic replacement 构造提取为
    纯 helper `build_replacement_graph_change(original_graph_change, graph_review)`
    （pure / deterministic / zero write / zero LLM），M5 `review_import` 同样
    调用该 helper（M5 既有测试语义不变）。
    M6 必须：`expected replacement canonical payload == persisted replacement
    canonical payload`，否则 `REPLACEMENT_TAMPERED` + `APPLY_REJECTED`。
    禁止只检查 ID。
14. **Validator 组合门**：
    - 先 `validate_review(original_gc, review, as_of=applied_at)`：必须
      `structural_ok=true`、`review_eligible=true`；任何 KGV-019 stale-review
      issue 必须 `APPLY_REJECTED`（即使 review_eligible=true 也不能忽略）。
    - 再 `validate_candidate(replacement_gc, as_of=applied_at)`：必须
      `structural_ok=true`、`review_eligible=true`、`apply_eligible=true`。
    - 理由：approved_with_changes 允许 patch 消除 original 的 candidate-level
      apply blocker（conflicts / new_evidence_ids / evidence_ids / confidence /
      validity 等），但 KGV-019 baseline stale 不能靠 patch 绕过。

### 36.5 candidate hash 唯一 authority

15. `review.candidate_hash` 必须由
    `KnowledgeValidator.compute_candidate_hash(original_gc)` 验证；
    effective GraphChange 的 hash 同样使用该方法。M6 禁止第二套 hash。

### 36.6 apply-time transformation

16. M6 不 UPDATE candidate / GraphReview。只从 effective candidate 构造 approved
    core object：
    - **Node**：复制 effective `node.model_dump()`，只改变
      `review_status = approved`、`last_reviewed_at = GraphReview.reviewed_at`；
      保持 node_id / node_type / name / aliases / description / status /
      valid_from / valid_to / evidence_ids / version / origin_kind /
      originating_graph_change_id / created_at。
      `add_node` 额外要求 `status = active`，否则 `ADD_NODE_NOT_ACTIVE`。
    - **Edge**：复制 effective `edge.model_dump()`，只改变
      `review_status = approved`、`last_reviewed_at = GraphReview.reviewed_at`；
      保持 edge_id / source_node_id / relation / target_node_id / attributes /
      assertion_type / valid_from / valid_to / confidence / evidence_ids /
      version / originating_graph_change_id / created_at。
      `MODEL_INFERENCE` apply 后仍必须是 `MODEL_INFERENCE`，不得升级为 FACT。
17. **applied_at 只属于 graph_applications audit**：不得写入 valid_from /
    valid_to / created_at / Evidence.published_at / GraphReview.reviewed_at。
    `created_at` 保留 candidate/effective 值；`last_reviewed_at` 使用
    `GraphReview.reviewed_at`（不是 applied_at）。必须 `applied_at >=
    reviewed_at`，首次 apply 违反 → `APPLY_TIME_INVALID`。
18. **Core object 也必须 Schema-first**：raw `graph_node`/`graph_edge` schema →
    GraphNode/GraphEdge → model_dump → schema，通过后才允许 persistence。
19. **M6 不修改 GraphChange 状态**：apply 成功后 `graph_changes.payload`
    byte-for-byte immutable；不把 `review_status` UPDATE 成 approved/applied，
    不修改 reviewed_at。GraphReview 是审核 audit，GraphApplication 是 apply
    audit，GraphChange candidate 永久保留原样。

### 36.7 GraphApplication audit + idempotency

20. **GraphApplication internal payload**（本轮不新增 Schema）：
    `application_id / original_graph_change_id / effective_graph_change_id /
    review_id / decision / review_candidate_hash / effective_candidate_hash /
    target_kind / target_id / target_version / applied_at / status`
    （`status = applied`；`target_kind` ∈ node|edge）。
    `graph_applications.graph_change_id` 列保存 `effective_graph_change_id`
    （实际被 applied 的 GraphChange）；original ID 保留在 payload。
21. **Idempotency intent**：
    `original_graph_change_id / effective_graph_change_id / review_id /
    effective_candidate_hash / target_kind / target_id / target_version`；
    canonical = `json.dumps(intent, ensure_ascii=False, sort_keys=True,
    separators=(",", ":"))`；
    `idempotency_key = sha256(canonical intent)`；
    `application_id = UUID5(DNS, "graph-application:" + idempotency_key)`。
    禁止随机 UUID；禁止把 applied_at 放进 idempotency key（否则重复 apply
    因 wall clock 改变失去幂等）。
22. **GraphRepository 专用方法** `get_application_by_idempotency_key()` /
    `append_application()`；禁止 generic DB upsert。`append_application()`
    INSERT ONLY：同 application_id/idempotency_key + 同 payload →
    idempotent_noop；同 key/ID 异 payload → `IMMUTABLE_APPLICATION_CONFLICT`，
    不得覆盖。
23. **Idempotent replay 必须优先识别**（重复 apply 时 target 已存在，若先跑
    KGV duplicate/stale 会错误 reject）：
    1. load/Schema original candidate；
    2. resolve/Schema review；
    3. resolve/verify effective candidate；
    4. 计算 deterministic idempotency key；
    5. strict lookup existing GraphApplication；
    6. 若存在：验证 application audit integrity + target approved node/edge
       version 存在 + persisted target canonical payload 与 expected 一致；
    7. 全部一致 → `IDEMPOTENT_NOOP`（返回已有 application_id/applied_at），
       不重新 apply；若 application 存在但 target missing / payload 不同 /
       wrong version → `APPLICATION_INTEGRITY_CONFLICT`，不得冒充幂等。
24. **TOCTOU 防护**：新 apply 必须在事务内完成（SQLite write lock）：
    `BEGIN IMMEDIATE`（或仓库中等价 deterministic immediate transaction
    helper）→ 事务内 recheck idempotency → rerun current-state M4 validation →
    recheck target/version → append approved node/edge → append GraphApplication
    → COMMIT；任一步失败 ROLLBACK ALL。新增 `Database.immediate_transaction()`
    只做最小事务 helper，不改变其他 transaction 语义。
25. **Repository 禁止 fail-open**：strict read path 不得用
    `except Exception: return []` 判定 review/edge/application 缺失；
    DB error → `APPLY_REJECTED`，不是 empty state。

### 36.8 dry-run 与结果

26. `knowledge apply --dry-run` 执行完整预检（load candidate → Schema-first →
    review selection → review Schema-first → hash → replacement verification →
    M4 validation → effective validation → target build → version/current graph
    preflight → application idempotency preflight），但
    graph_nodes/graph_edges/graph_reviews/graph_changes/graph_applications
    delta = 0、files delta = 0；CLI dry-run 使用 `Database.open_read_only()`
    进一步硬化零写；不得 mkdir。
27. **ApplyResult**（frozen dataclass）：`status / original_graph_change_id /
    effective_graph_change_id / review_id / application_id / idempotency_key /
    target_kind / target_id / target_version / applied_at / dry_run / errors /
    warnings`。状态至少 `applied` / `idempotent_noop` / `dry_run` /
    `APPLY_REJECTED`；内部 error code 明确，不用模糊 failed。
28. **CLI**：`research knowledge apply --change-id <uuid>`（支持
    `--review-id <uuid>` optional deterministic disambiguation、
    `--db <path>`、`--dry-run`、`--applied-at <iso>`）。
    `--applied-at` 未提供时 `capture now_iso() once`（不得多次读取 wall clock）。
    成功输出 deterministic JSON（status / original_graph_change_id /
    effective_graph_change_id / review_id / application_id / idempotency_key /
    target_kind / target_id / target_version / applied_at / dry_run / warnings）；
    失败 non-zero exit + `status=APPLY_REJECTED` + `error_code` + errors，
    不得 silent failure。

### 36.8a M6-R1 Apply Safety Closure 补充（2026-08-08）

> M6 尚未验收，直接补充本决定；不另立 Decision #37。

29. **immediate_transaction 语义**：
    - COMMIT 失败必须异常传播（ApplyEngine 不得返回 applied）；不得
      `except OperationalError: pass` 吞掉 COMMIT/ROLLBACK 失败。
    - 进入 BEGIN IMMEDIATE 前若调用者已有活动事务（`conn.in_transaction`），
      不得自动 commit 清场——raise `ACTIVE_TRANSACTION_CONFLICT`
      （RuntimeError），由 ApplyEngine 转 `APPLY_REJECTED`。
    - 异常退出执行 ROLLBACK；若 rollback 自己失败，不得把原始业务异常变成
      成功——保留原始异常并附加 rollback context。
30. **SQLite 线程保护**：恢复 sqlite3 默认 `check_same_thread=True`
    （全局不削弱跨线程误用防护）。并发测试改为每个 worker thread
    在自己的线程内创建 Database connection（仍为 same SQLite file +
    two independent connections + BEGIN IMMEDIATE）。
31. **strict reads**：M6 不得依赖 `candidate_repo.get_candidate()`
    处理安全关键读取。新增 `_load_graph_change_strict()`（直接
    SELECT payload FROM graph_changes → DB error/missing/invalid JSON/
    Schema 失败全部映射结构化 code：CANDIDATE_READ_FAILED /
    CANDIDATE_NOT_FOUND / CANDIDATE_PAYLOAD_INVALID /
    CANDIDATE_SCHEMA_INVALID；replacement 用 REPLACEMENT_* 对应 code）。
    review selection 的 SQL error / JSON decode / malformed payload 全部
    fail-closed（REVIEW_READ_FAILED / REVIEW_PAYLOAD_INVALID）；>1 reviews
    时 ambiguity message 直接使用 DB review_id column 稳定排序，不解析 payload。
    target/version strict read 的 DB error / invalid JSON → 结构化拒绝，
    ApplyEngine public API 不得直接 crash。
32. **ApplyResult.error_code**：`error_code: str | None`；所有拒绝路径
    `status=APPLY_REJECTED` + 精确机械 code（如 REVIEW_REQUIRED /
    AMBIGUOUS_REVIEW_SELECTION / CANDIDATE_HASH_MISMATCH / STALE_REVIEW /
    APPLICATION_INTEGRITY_CONFLICT / APPLY_TIME_INVALID /
    CHANGE_TYPE_REQUIRES_M7），成功为 null；`errors` 保存人类可读信息。
    调用方不再从字符串 prefix 反解析 code。
33. **事务内 revalidation 保留 error code**：事务内 gate 失败使用内部 signal
    `_InTxnRejected(ApplyResult)`，ROLLBACK 后返回原始 ApplyResult
    （保留 STALE_REVIEW / M4_APPLY_PREFLIGHT_FAILED /
    M4_REPLACEMENT_VALIDATION_FAILED 等精确 code）；
    target/application immutable conflict 映射精确 code
    （TARGET_VERSION_CONFLICT / VERSION_VIOLATION / VERSION_GAP /
    APPLICATION_INTEGRITY_CONFLICT）。
34. **GraphApplication replay 验证完整 audit**：
    - `get_application_by_idempotency_key()` 返回全部列
      （application_id / graph_change_id / review_id / idempotency_key /
      payload / applied_at）；JSON parse failure 上抛，由 engine 转
      `APPLICATION_INTEGRITY_CONFLICT` / `APPLICATION_READ_FAILED`。
    - replay 时用 stored applied_at 构造 expected payload，canonical
      全对象相等；DB columns 全部与 deterministic 值一致
      （application_id == deterministic app_id、
      graph_change_id == effective_graph_change_id、
      review_id == review.review_id、
      idempotency_key == deterministic idem_key、
      applied_at == expected_payload.applied_at）；
      再验证 target 存在 / version 精确 / canonical payload 精确。
      任一不一致 → `APPLICATION_INTEGRITY_CONFLICT`。不得只检查少数字段。
    - `append_application()` 完整 immutable：application_id 或
      idempotency_key 已存在时，只有 all columns same AND canonical
      payload same 才 idempotent_noop，否则
      `IMMUTABLE_APPLICATION_CONFLICT`；不得仅比较 payload。
35. **approved_with_changes effective Evidence review-time closure**：
    人工 review 发生在 `review.reviewed_at`，因此 effective replacement
    的全部 Evidence 必须证明 `published_at <= reviewed_at` 且
    `retrieved_at <= reviewed_at`，而不是只要求 `<= applied_at`。
    实现：保留 original `validate_review(original, review, ...)` + KGV-019
    stale gate；effective replacement 的 `validate_candidate(effective_gc,
    as_of=review.reviewed_at)` 用于 review-time information cutoff；
    复用 M4 KGV-007 的 review-time Evidence 逻辑（只读 helper
    `evidence_review_time_closure()`，不改 KGV-007 语义、不改现有 M4
    results）。时间攻击（review 后 SQL mutation evidence 时间）→
    `EVIDENCE_RETRIEVED_AFTER_REVIEW` 拒绝。

### 36.8b M6-R2 Final Integrity Closure 补充（2026-08-09）

> M6 尚未验收，继续补充本决定；不另立 Decision #37。

36. **review valid-JSON wrong-type fail-closed**：`--review-id` 显式路径与
    implicit single-review 路径的 payload 必须 `JSON decode → top-level 必须
    object（dict）→ GraphReview Schema-first`。合法 JSON 但顶层非 dict
    （`[]` / `"foo"` / `123`）→ `APPLY_REJECTED` + `REVIEW_PAYLOAD_INVALID`，
    不得 public API exception / traceback。显式路径同时读取
    `review_id, graph_change_id, payload` 三列，用 DB `graph_change_id`
    column 做 association precheck（`REVIEW_CHANGE_MISMATCH`），payload
    最终仍必须 Schema-first。
37. **GraphApplication 双 deterministic identity**：replay lookup 必须同时
    绑定 deterministic `application_id` 与 `idempotency_key`。M6 安全路径
    使用 `get_application_by_identity(application_id, idempotency_key)`：
    0 rows → 无 previous application；1 row → 返回全列 + parsed payload；
    application_id 命中 row A、idempotency_key 命中 row B（>1 rows，正常
    DB 因 application_id PRIMARY KEY + idempotency_key UNIQUE 不可能自然
    出现，只能来自 SQL 篡改）→ `APPLICATION_INTEGRITY_CONFLICT`，不得任选
    其一。tampering either identity 必须可发现并拒绝（idempotency_key
    column 篡改为另一个合法 sha256 → `APPLICATION_INTEGRITY_CONFLICT`，
    不得 idempotent_noop / M4_* / applied）。保留
    `get_application_by_idempotency_key()` 仅供兼容，安全路径一律双 identity。
38. **COMMIT failure rollback cleanup**：COMMIT 失败必须捕获原始异常 →
    若 `conn.in_transaction` 则 attempt ROLLBACK → 传播原始 commit 失败；
    若 rollback 也失败，raise chained RuntimeError 同时保留 commit failure +
    rollback failure context。ApplyEngine 必须 never return applied；且
    rollback 成功后 `conn.in_transaction == False`、pending writes == 0。
    不重新吞异常。
39. **persisted GraphReview JSON top-level 必须 object**：任何字段访问
    （`.get()` 等）之前先验证 payload 顶层是 dict，否则
    `REVIEW_PAYLOAD_INVALID`。
40. **ADD_NODE_NOT_ACTIVE 是 first-class ApplyResult.error_code**：
    add_node 且 node.status != active → `APPLY_REJECTED` +
    `ADD_NODE_NOT_ACTIVE`（内部 `_TargetBuildError` 携带 code，apply 映射
    结构化 error_code）；调用方不得从 errors 字符串反解析。该拒绝零
    graph_nodes / graph_applications delta。

### 36.9 M6 严格不实现

- M7：modify_attribute / retire_node / retire_edge apply、superseded、expired、
  closing previous valid_to、history query
- JSON mirror export、knowledge context builder（M8）
- 自动批准、自动应用
- M7-M10 全部未授权

---

## 37. Phase 5 M7 Version Lifecycle & History Contract（2026-08-09）

> 本决定在 M7 实现启动时冻结，经用户明确授权（M6_ACCEPTED_SHA=`480b209`）。
> M7 不修改 M4 KGV-001—019 含义；可增加独立 deterministic lifecycle/history
> validation，但不得偷偷改变现有 KGV results。

### 37.1 范围与运行时

1. **M7 正式实现**：`modify_attribute` / `retire_node` / `retire_edge` apply、
   version lifecycle、superseded / expired / retired 派生语义、
   identity-scoped history query、deterministic as_of resolution。
2. **运行时 ZERO LLM / ZERO Provider / ZERO network**（apply 与 history 均不得
   调用模型）。LLM 仍只允许存在于 M3 GraphChangeProposal semantic proposal
   阶段。
3. **M7 不新增 Schema、不新增 migration、不修改 006 migration、DB 保持 v6**。
   现有 `version / status / valid_from / valid_to / originating_graph_change_id /
   GraphApplication` 足够表达 M7。
4. **任何 M7 change 都必须经过 M5 Human Review + M6/M7 Apply Engine**；
   candidate 永不直接进入 active graph。

### 37.2 一级红线：旧版本物理不可变

5. **graph_nodes / graph_edges 全部 INSERT ONLY**。M7 严禁为 superseded /
   expired / closing valid_to / retired 去 UPDATE vN payload / status /
   valid_to / 任何 vN column。vN 是否 superseded/expired 由 deterministic
   history semantics 派生，绝不回写。

### 37.3 时间模型：双时间禁止混用

6. **业务有效时间**（valid_from / valid_to）与**审核/系统 audit 时间**
   （created_at / reviewed_at / applied_at）严格区分。严禁：
   reviewed_at → 自动填 valid_from；applied_at → 自动填 valid_from；
   created_at → 自动关闭 valid_to；now() → 自动退休时间；file mtime → 业务时间。
7. **业务 transition time 缺失 → REJECT**，绝不用系统时间兜底。
   - v1 add：valid_from = null 仍允许（history 中 null = unbounded past）。
   - vN+1 modify：valid_from != null（= transition_at），不得隐式生成；
     predecessor.valid_from 非 null 时 successor.valid_from > predecessor.valid_from，
     否则 `TRANSITION_TIME_NOT_MONOTONIC`。
   - retire：valid_from == valid_to == retire_at（tombstone），均非 null，
     否则 `RETIRE_TIME_INVALID`。

### 37.4 history interval 与派生状态

8. **半开区间** `[effective_from, effective_to)`：
   `effective_to = min(vN.valid_to, vN+1.valid_from)`（只有其一 / 均 null 对应
   单边 / +∞）。`effective_from != null and effective_to != null and
   effective_from > effective_to` → fail-closed `HISTORY_INTERVAL_INVALID`。
   as_of < successor.valid_from → predecessor 仍可能有效；
   as_of == successor.valid_from → successor 接管。
9. **superseded / expired / retired 全部 derived**，不 UPDATE 旧对象：
   - superseded：存在 successor 且 as_of >= successor.valid_from
   - expired：无已生效 successor 且 valid_to != null 且 as_of >= valid_to
     （允许 v1.valid_to=T1 < v2.valid_from=T2 的 knowledge gap，不得填平）
   - retired：retire tombstone（node status=retired / edge 通过
     origin GraphChange.change_type == retire_edge 判定）且 as_of >= retire_at；
     禁止仅凭 valid_from == valid_to 猜测 retire
10. **M7 ordinary write 的 persisted status**：add_node → active；
    modify_attribute → active；retire_node → retired。不得把旧 Node payload
    改写为 superseded / expired（这两个只存在于 history-derived 语义）。

### 37.5 modify_attribute 合同

11. **Node**：target 必须是 latest persisted；current_knowledge canonical ==
    latest payload（复用 KGV-019）；effective candidate 必须 same node_id /
    same node_type、version = latest+1、status = active、valid_from = explicit
    transition_at。identity（node_id/node_type）改变 → `IMMUTABLE_IDENTITY_CHANGED`。
    允许业务变化只限 name / aliases / description / valid_to + evidence 追加。
    禁止借 modify 做 active → retired/superseded/expired（retire 必须走
    retire_node）。无真实业务字段变化（仅 version/created_at/review fields/
    evidence_ids/valid_from 变化）→ `NO_EFFECTIVE_CHANGE`。
12. **Edge**：target 必须 resolve 为唯一 edge identity（KGV-015）；edge_id /
    source_node_id / relation / target_node_id / assertion_type 全部 immutable
    （特别禁止 MODEL_INFERENCE ↔ FACT 通过 modify 偷换 epistemic class）；
    允许 attributes / confidence / valid_to + evidence 追加。
13. **active-at-transition**：modify 不能复活失效对象。latest.status == active
    且 predecessor.valid_to >= transition_at，否则 `MODIFY_TARGET_NOT_ACTIVE`。
    不实现 reactivate / restore / unretire。
14. **Evidence history preservation**：old evidence_ids ⊆ new evidence_ids，
    否则 `EVIDENCE_HISTORY_LOSS`。

### 37.6 retire 合同

15. **retire_edge**：新 version 必须 edge_id / source / relation / target /
    assertion_type / attributes / confidence 全部 unchanged，version=N+1，
    valid_from == valid_to == retire_at，evidence_ids = stable union。
    任何业务修改 → `RETIRE_PAYLOAD_MUTATION`；latest 已 expired/retired →
    `RETIRE_TARGET_NOT_ACTIVE`。
16. **retire_node**：新 version 必须 same node_id / node_type / name / aliases /
    description，status=retired，version=N+1，valid_from == valid_to == retire_at，
    evidence_ids = stable union。业务修改 → `RETIRE_PAYLOAD_MUTATION`；
    latest.status != active 或 valid_to < retire_at → `RETIRE_TARGET_NOT_ACTIVE`。
17. **incident-edge guard**：retire_node 在 retire_at 扫描
    source/target == node_id 的全部 edge identity，用 M7 history semantics
    （HistoryService.resolve_edge_as_of）判断是否 active。任一 active →
    `ACTIVE_INCIDENT_EDGES`（0 writes，禁止 cascade；必须先行 retire incident
    edges）。edge 在 retire_at 前已 expired/retired 不阻塞。任何 incident-edge
    DB error / invalid JSON / invalid Schema / broken chain → fail-closed
    （`INCIDENT_EDGE_CHECK_FAILED`），不得当作“没有 active edge”。
18. **重复完全相同 apply 仍由 GraphApplication replay → idempotent_noop**。

### 37.7 apply 流程与事务

19. modify/retire apply 仍必须：preflight → BEGIN IMMEDIATE → 事务内重读 latest →
    rerun M4 gates → rerun M7 lifecycle gates → rerun incident-edge guard →
    append vN+1 → append GraphApplication → COMMIT。任何失败 ROLLBACK ALL
    （不得产生 new version without application / application without version）。
20. **并发**：两个 candidate 同时基于 vN modify，最多一个生成 vN+1；
    另一条 STALE / VERSION conflict / deterministic rejection。
    绝不产生两个不同 payload 的 vN+1。
21. **GraphApplication contract 不变**：M7 modify/retire 使用与 M6 完全相同的
    application_id / original_graph_change_id / effective_graph_change_id /
    review_id / decision / review_candidate_hash / effective_candidate_hash /
    target_kind / target_id / target_version / applied_at / status 以及
    deterministic idempotency_key / application_id 算法。禁止复制或修改
    candidate hash / replacement / review ID / idempotency 算法。

### 37.8 History Service

22. **职责单一** `knowledge/history.py`：get_node_history / get_edge_history /
    resolve_node_as_of / resolve_edge_as_of（single identity，非 M8 graph query）。
23. **strict read**：每行 JSON decode → top-level dict → JSON Schema → Pydantic →
    model_dump → JSON Schema，并核对 DB columns 与 payload 一致
    （node 至少 node_id/version/node_type/name/status/review_status/origin_kind/
    created_at/valid_from/valid_to/last_reviewed_at/originating_graph_change_id）。
    不一致 → `HISTORY_INTEGRITY_CONFLICT`（不得只信一边）。
24. **version-chain integrity**：完整 identity history 必须 version 从 1 开始、
    1..N contiguous；缺号/重复/invalid payload/retrograde → fail-closed。
    错误码至少：HISTORY_READ_FAILED / HISTORY_PAYLOAD_INVALID /
    HISTORY_SCHEMA_INVALID / HISTORY_INTEGRITY_CONFLICT / HISTORY_VERSION_GAP /
    HISTORY_INTERVAL_INVALID。
25. **origin integrity**：origin_kind=graph_change 或
    originating_graph_change_id != null 时严格读取对应 GraphChange（exists /
    Schema valid / identity matches / version matches / change_type compatible）。
    retire derived status 必须通过 origin GraphChange.change_type 判定。
    缺失/损坏/不匹配 → `HISTORY_ORIGIN_INTEGRITY_CONFLICT`。
    Governance seed 继续允许 originating_graph_change_id = null。
26. **as_of resolver**：as_of 必须显式提供、合法 ISO，禁止默认 now()。
    未提供 as_of 的 history 调用只输出完整 history（resolved=null）。
    future successor.valid_from > as_of 不得影响 as_of 时点解析。
27. **输出 deterministic JSON**（kind / identity / as_of / versions[] /
    resolved{version, derived_status, is_active, payload}），version ordered，
    无 wall-clock、无 LLM。不新增 Schema。

### 37.9 M7 严格不实现

- M8：knowledge_context_builder、depth traversal、relation filtering、
  full graph search、multi-hop traversal
- Phase 2/3/4 integration
- M9/M10
- reactivate / restore / unretire
- 自动批准、自动应用
