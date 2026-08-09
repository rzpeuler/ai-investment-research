# AI＋投研 Skill 工程执行说明与指南

**版本：V1.3**
**变更日期：2026-08-09**
**状态：当前唯一有效工程基线**
**适用市场：A 股为主，港股、美股、商品与海外宏观仅作为背景或对照**  
**主要执行环境：Hermes＋DeepSeek V4 Flash，复杂任务路由至 V4 Pro；Codex 作为可选工程审查与复杂重构工具**  
**默认输出：Markdown；估值模型等确定性计算可额外输出 Excel**  
**时间口径：Asia/Shanghai**

---

## 0. 文档目的

本文件是交给工程执行 Agent 的项目规范，而不是讨论稿。工程执行模型必须按照本文件搭建项目，不得自行重构业务定位、增加未经定义的需求场景，或自行决定研究规则。

本项目保留用户定义的四层框架：

1. 需求场景层
2. 功能模块层
3. 数据采集层
4. 知识库层

在四层之外，增加一个横向的“工程控制面”，但它不是新的业务层。控制面负责：

- 任务编排
- 模型路由
- 数据契约
- 证据追踪
- 来源治理
- 质量校验
- 失败降级
- 日志与审计
- 版本控制
- 用户反馈闭环

任何场景、模块、采集器和知识更新都必须受控制面约束。

### 0.1 文档权威顺序（V1.2）

发生冲突时按以下顺序执行：

1. `docs/engineering-guide.md`：长期业务定位、架构基线和不可违反原则；
2. `docs/project-state/DECISIONS.md`：经正式评审批准的具体设计决策；
3. `docs/tasks/*.md`：阶段实施授权，只能细化指南和正式决策，不得静默覆盖；
4. `docs/project-state/CURRENT_STATE.md`：当前实际完成状态；
5. `docs/project-state/NEXT_PHASE.md`：下一阶段准入条件和边界；
6. `docs/project-state/KNOWN_LIMITATIONS.md`：当前已知限制；
7. `README.md`：导航和摘要，不作为权威设计依据。

阶段任务若需改变本指南，必须先在 `DECISIONS.md` 记录经批准的设计变更，再更新本指南
版本和变更日期，最后同步阶段任务书。任何任务书不得自行声明无条件覆盖本指南。

### 0.2 V1.1 控制面、证据链与状态补充

- 首批三个核心场景必须通过显式场景注册表和统一 Orchestrator 执行；Plan 不得为空，
  且必须记录步骤、数据需求、运行预算、模型策略、降级路径和输出位置。
- 报告中的关键事实链必须为 `RawItem → Evidence → Claim → ResearchFinding/Event → Markdown`；
  Claim ID、Candidate ID 或聚合事件 ID 不得冒充 Evidence ID。
- 确定性回退不得产生 `MODEL_INFERENCE`；模型实际调用、Provider、模型、预算、耗时、
  输出校验和降级原因必须如实记录。
- Phase 4 完整成功不得仅由可比年度数量决定；财务、证据、业务、竞争、风险、催化剂、
  反证、市场主要矛盾、估值适用性、语义能力、来源质量、截止时间和 Validator 均属于
  集中、版本化状态判定条件。
- 在上述完整研究能力未达到最低覆盖前，Phase 4 可保持工程基础 PASS，但完整研究能力
  必须标为 `PARTIAL_SUCCESS` 或 `DATA_DEGRADED`，Phase 5 保持 `BLOCKED`。

### 0.3 V1.3 Phase 6 顶层设计冻结（2026-08-09）

- 正式消除“剩余场景 = 7 但旧 Phase6 路线只列部分场景”的设计歧义：Phase 6 完整
  七场景一次性冻结为 6A / 6B / 6C 三个业务 Track。
- 六阶段结构为 `6A（industry_research / theme_discovery）`、
  `6B（evening_brief / daily_review / stock_review）`、
  `6C（first_coverage / earnings_expectation）`。
- Phase 6 串行拓扑冻结（V1.3）：并行开发已取消，替换为串行里程碑门控：
  P6-S0 治理重置 → P6-S1 6B 终验合入 → P6-S2 6A 终验合入 →
  P6-S3 earnings_expectation → P6-S4 first_coverage →
  P6-S5 中央 enablement → P6-S6 治理收尾。
  任意时刻 MAX_ACTIVE_PHASE6_BUSINESS_BRANCHES = 1。
- 首次正式允许 Graph→Research，但严格只读：`Versioned Graph → GraphQueryService →
  KnowledgeContextBuilder → read-only Research Context`；`as_of` 必填；
  SQLite 是唯一 graph authority；JSON mirror 只是 deterministic read-only export。
- `KnowledgeContext != Evidence`：Graph 只用于研究导航、实体发现、产业坐标、关系发现、
  检索方向与上下文组织；Graph 内容进入报告事实链必须经
  `Graph object → evidence_ids → Evidence reload → Evidence validation → Claim/ResearchFinding → Markdown`。
- Graph 写入永久禁止 Scenario 直接写 active GraphNode / GraphEdge，继续走
  `RawItem → Evidence → Claim/Event/ResearchFinding → GraphChange Proposal → GraphChange
  Candidate → Human Review → Validator → Deterministic Apply → Versioned Graph`；
  `LLM can propose / LLM cannot approve；human can approve / human cannot bypass validator`。
- 每个 Phase 6 新场景必须先 `Research Capability Acceptance`，再 `Candidate Integration
  Authorization`，最后才允许 `Research → GraphChange Candidate`；active graph 永不被直接写。
- Phase 6 时间治理：Graph→Research 强制 `as_of`，禁止 future knowledge leakage；
  6C forecast 受 `as_of` / `historical cutoff` / `forecast period` 治理。
- 输出永久边界不变：全部七场景继续禁止目标价、评级、仓位建议、交易建议与自动荐股；
  `theme_discovery ≠ stock picking`、`first_coverage ≠ brokerage rating`、
  `earnings_expectation ≠ trading signal`、`daily_review ≠ next-day trading plan`。
- 本体与来源扩张冻结：新增 node_type / relation / relation semantic change /
  automatic ontology expansion 均 `NOT_AUTHORIZED / PROHIBITED`；
  Phase 6 不顺手扩张 source whitelist，新来源必须独立走
  discovery → probe → source governance → verification → registry update。

---

# 第一部分：需求确认稿

## 1. 项目目标

建设一套个人使用的 AI＋A 股投研 Skill 系统，用于覆盖用户日常研究工作流，并将研究过程中的有效信息持续沉淀到可迭代的产业知识库中。

项目第一优先级不是生成一份看起来完整的报告，而是建立以下能力：

- 多来源信息的稳定采集和可替换接入
- 事实、来源观点、模型推断与假设的严格分离
- 信息筛选、去重、聚类和价值判断
- 场景 Skill 对标准功能模块的组合调用
- 报告中每个关键结论的证据可追溯
- 数据不足时允许降级和拒绝归因
- 用户修改能够形成可审查的规则反馈
- 每日信息能够进入事件库，并经过严格审核后更新产业图谱

## 2. 首要真实场景

首批需要解决的三个真实工作场景：

1. 个股研报
2. 每日晨报
3. 异动分析

项目架构仍须覆盖需求文档中已经定义的其他场景（**Phase 6 完整七场景，剩余场景 = 7**，
与 `6A / 6B / 6C` 结构一一对应，见第 69 节）：

- 6A：行业研究（industry_research）
- 6A：主题挖掘（theme_discovery）
- 6B：每日晚报（evening_brief）
- 6B：每日复盘（daily_review）
- 6B：个股复盘（stock_review）
- 6C：首次覆盖（first_coverage）
- 6C：财报预期（earnings_expectation）

不增加用户未提出的业务场景。

## 3. 明确非目标

第一版不建设：

- 自动交易
- 下单接口
- 组合调仓
- 仓位建议
- 买入、卖出、增持、减持等操作建议
- 目标价
- 自动化荐股
- 面向多租户的商业 SaaS
- 一开始即使用复杂图数据库
- 绕过登录、验证码、付费墙或平台限制的采集方案
- 无证据的实时行情推断
- 把机构热度代理指标表述为机构真实买卖行为

## 4. 输出边界

研究报告可以输出：

- 事实归纳
- 产业影响
- 财务和业务分析
- 估值方法及其适用性
- 同行估值比较
- 历史估值分位
- 市场隐含假设
- 催化剂
- 风险
- 多空主要矛盾
- 待验证问题
- 不同情景下的敏感性分析

不得输出：

- 目标价
- 买入或卖出评级
- 明日交易建议
- 建议仓位
- “可以买”“可以跟”“上车”等引导性语言

## 5. 运行预算

默认任务档位：

| 档位 | 目标耗时 | 适用范围 |
|---|---:|---|
| fast | 3—8 分钟 | 快速扫描、单模块查询、初步异动原因 |
| standard | 10—20 分钟 | 晨报、标准异动分析、普通个股研报 |
| deep | 不超过 30 分钟 | 复杂个股研报、产业链推导、历史回溯 |

达到预算上限后，任务必须结束并输出：

- 已完成内容
- 未完成内容
- 缺失数据
- 使用的降级来源
- 当前结论置信度
- 后续研究建议

不得无限检索或为了完整性编造内容。

---

# 第二部分：总体架构

## 6. 设计原则

### 6.1 场景负责“编排”，模块负责“分析”

场景 Skill 不重复实现财务、估值、行业、舆情等能力。它只负责：

- 理解用户意图
- 补齐默认参数
- 生成执行计划
- 选择功能模块
- 定义模块顺序
- 合并结果
- 调用报告模板
- 触发质量校验

功能模块必须职责单一，可被多个场景复用。

### 6.2 平台采集器不是功能模块

例如“雪球采集器”“财联社采集器”“巨潮公告采集器”属于数据采集层；“舆情分析”“事件抽取”“异动归因”属于功能模块层。

禁止在功能模块 Prompt 中写死网页结构、CSS 选择器、Cookie 或平台登录流程。

### 6.3 确定性任务优先使用代码

以下任务原则上不得由 LLM 自由生成结果：

- 日期计算
- 交易日判断
- 证券代码映射
- 数值计算
- 财务比率
- 估值公式
- 收益率和 Alpha 计算
- 去重哈希
- Schema 校验
- 报告章节校验
- 数据日期校验
- 文件路径与命名
- 数据库写入
- 任务幂等判断

LLM 主要处理：

- 分类
- 事件和观点提取
- 语义去重辅助
- 产业链推理
- 信息价值判断
- 原因候选排序
- 研究结论组织
- 待验证问题生成

### 6.4 证据优先于表达完整

当证据不足时，输出“证据不足”优于补齐一篇流畅文章。

### 6.5 允许未知和无法归因

系统必须支持：

- `UNKNOWN`
- `INSUFFICIENT_EVIDENCE`
- `UNEXPLAINED_MOVE`
- `SOURCE_CONFLICT`
- `DATA_DEGRADED`

不得强行给出单一原因。

---

## 7. 逻辑架构

```text
用户 / Cron
    │
    ▼
场景路由器
    │
    ├── 参数标准化
    ├── 实体解析
    ├── 时间窗口
    └── 执行档位
    │
    ▼
研究计划器
    │
    ├── 数据需求
    ├── 模块调用图
    ├── 检索预算
    └── 模型路由
    │
    ▼
数据采集层
    │
    ├── 来源注册表
    ├── 主源/备源
    ├── 健康检查
    ├── 原始元数据
    └── 结构化标准化
    │
    ▼
功能模块层
    │
    ├── 信息筛选
    ├── 事件抽取
    ├── 观点抽取
    ├── 财务分析
    ├── 估值分析
    ├── 行业分析
    ├── 舆情与多空
    ├── 异动归因
    └── 主题价值判断
    │
    ▼
证据与质量控制
    │
    ├── Claim 校验
    ├── 来源冲突
    ├── 引用覆盖
    ├── 数据新鲜度
    └── 禁止项检查
    │
    ├──────────────┐
    ▼              ▼
报告生成       知识库候选更新
                   │
                   ▼
               人工审核
                   │
                   ▼
               产业图谱
```

---

## 8. 物理架构

第一版采用本地优先、可迁移设计：

```text
Hermes Skill
  ├── 调用 Python CLI
  ├── 调用本地 HTTP 服务（可选）
  ├── 调用浏览器或网页工具
  └── 读取/写入 Markdown

Python 核心服务
  ├── Orchestrator
  ├── Collector Adapters
  ├── Normalizers
  ├── Analysis Modules
  ├── Knowledge Service
  ├── Report Renderer
  └── Validators

存储
  ├── SQLite：元数据、任务、实体、事件、观点、证据、来源备案
  ├── DuckDB/Parquet：行情、财务、板块等时序和宽表
  ├── JSON：模块产物、图谱节点与关系
  └── Markdown：晨报、晚报、复盘、用户报告、Wiki 页面
```

第一版不要求服务器。个人电脑关机期间定时任务可能漏跑，因此必须设计补跑机制。未来迁移到云服务器或 NAS 时，不改变业务代码，只替换运行和调度环境。

---

# 第三部分：项目目录

## 9. 建议目录

```text
ai-investment-research/
├── README.md
├── AGENTS.md
├── pyproject.toml
├── .env.example
├── config/
│   ├── app.yaml
│   ├── model_routing.yaml
│   ├── schedules.yaml
│   ├── source_policy.yaml
│   ├── report_policy.yaml
│   └── knowledge_policy.yaml
├── skills/
│   └── finance/
│       ├── a-share-research-orchestrator/
│       │   └── SKILL.md
│       ├── morning-brief/
│       │   └── SKILL.md
│       ├── abnormal-move-analysis/
│       │   └── SKILL.md
│       ├── stock-research-report/
│       │   └── SKILL.md
│       ├── industry-research/
│       │   └── SKILL.md
│       ├── theme-discovery/
│       │   └── SKILL.md
│       ├── daily-review/
│       │   └── SKILL.md
│       ├── earnings-analysis/
│       │   └── SKILL.md
│       └── knowledge-ingest/
│           └── SKILL.md
├── src/
│   └── research_os/
│       ├── cli/
│       ├── orchestrator/
│       ├── routing/
│       ├── collectors/
│       │   ├── base.py
│       │   ├── official/
│       │   ├── market/
│       │   ├── media/
│       │   ├── community/
│       │   ├── institution/
│       │   └── manual/
│       ├── normalizers/
│       ├── modules/
│       ├── evidence/
│       ├── knowledge/
│       ├── reports/
│       ├── storage/
│       ├── validators/
│       └── utils/
├── schemas/
│   ├── task.schema.json
│   ├── entity.schema.json
│   ├── raw_item.schema.json
│   ├── event.schema.json
│   ├── opinion.schema.json
│   ├── claim.schema.json
│   ├── evidence.schema.json
│   ├── module_result.schema.json
│   └── graph_change.schema.json
├── registry/
│   ├── sources.yaml
│   ├── source_groups.yaml
│   ├── entity_aliases.csv
│   ├── industry_media.csv
│   ├── finance_creators.csv
│   ├── ima_knowledge_bases.csv
│   ├── institutions.csv
│   ├── lhb_seats.csv
│   └── changelog.md
├── knowledge/
│   ├── ontology/
│   ├── graph/
│   ├── inbox/
│   ├── candidates/
│   ├── wiki/
│   └── history/
├── reports/
│   ├── morning/
│   ├── evening/
│   ├── daily_review/
│   ├── stocks/
│   ├── industries/
│   ├── themes/
│   ├── earnings/
│   └── runs/
├── data/
│   ├── sqlite/
│   ├── parquet/
│   ├── cache/
│   ├── exports/
│   └── quarantine/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contracts/
│   ├── golden/
│   ├── source_health/
│   └── fixtures/
└── scripts/
    ├── bootstrap.py
    ├── probe_sources.py
    ├── run_scenario.py
    ├── validate_report.py
    ├── rebuild_graph.py
    └── migrate.py
```

## 10. Skill 数量控制

不要把每个功能模块都注册为 Hermes 的独立可发现 Skill。否则会造成：

- Skill 列表膨胀
- 上下文污染
- 路由冲突
- 模块间重复
- Agent 随机选择错误 Skill

建议：

- 场景作为 Hermes Skill
- 功能模块作为 Python 模块＋模块规范文件
- 只有用户可能直接调用的公共功能才单独暴露为 Skill
- 所有场景都可以通过总控 `a-share-research-orchestrator` 进入

---

# 第四部分：统一数据契约

## 11. 核心对象

### 11.1 Task

```json
{
  "task_id": "uuid",
  "scenario": "morning_brief",
  "status": "planned",
  "requested_at": "ISO-8601",
  "as_of": "ISO-8601",
  "timezone": "Asia/Shanghai",
  "entities": [],
  "time_window": {
    "start": "ISO-8601",
    "end": "ISO-8601"
  },
  "depth": "standard",
  "max_runtime_seconds": 1200,
  "source_policy": "public_first",
  "output_formats": ["markdown"],
  "model_policy": "flash_default",
  "warnings": []
}
```

### 11.2 Entity

```json
{
  "entity_id": "company:600519.SH",
  "entity_type": "company",
  "canonical_name": "贵州茅台",
  "aliases": ["600519", "茅台"],
  "market": "A-share",
  "industry_ids": [],
  "concept_ids": [],
  "valid_from": null,
  "valid_to": null,
  "source_ids": []
}
```

必须支持：

- 股票代码变化
- 公司更名
- ST 名称变化
- 同名公司消歧
- 行业和概念多重归属
- 历史有效期

### 11.3 RawItem

RawItem 不是网页全文存档，而是采集记录。

```json
{
  "raw_item_id": "uuid",
  "source_id": "sse",
  "external_id": "source-native-id",
  "url": "source-url",
  "title": "标题",
  "publisher": "发布者",
  "author": null,
  "published_at": "ISO-8601",
  "retrieved_at": "ISO-8601",
  "content_hash": "sha256",
  "content_excerpt": "最小必要证据摘录",
  "content_storage": "metadata_and_excerpt_only",
  "language": "zh-CN",
  "access_status": "ok",
  "entities": [],
  "raw_category": null
}
```

系统可以在处理期间临时读取正文，但默认不得永久保存全文。处理完成后仅保留：

- 元数据
- URL
- 内容哈希
- 最小必要证据摘录
- 结构化事件和观点
- 访问时间
- 解析状态

### 11.4 Event

```json
{
  "event_id": "uuid",
  "event_type": "capacity_expansion",
  "subject_entities": [],
  "object_entities": [],
  "event_time": "ISO-8601",
  "announced_at": "ISO-8601",
  "effective_at": null,
  "status": "announced",
  "summary": "结构化事件摘要",
  "quantitative_fields": {},
  "industry_coordinates": [],
  "novelty": 0.0,
  "impact_direction": "positive|negative|mixed|neutral|unknown",
  "impact_horizon": "intraday|short|medium|long",
  "evidence_ids": [],
  "confidence": 0.0,
  "conflicts": []
}
```

必须区分：

- 事件发生时间
- 信息发布时间
- 计划生效时间
- 报告检索时间

### 11.5 Opinion

```json
{
  "opinion_id": "uuid",
  "speaker_entity_id": "creator:xxx",
  "source_id": "xueqiu",
  "published_at": "ISO-8601",
  "target_entities": [],
  "stance": "bullish|bearish|mixed|neutral",
  "thesis": "观点",
  "arguments": [],
  "predictions": [],
  "conditions": [],
  "time_horizon": null,
  "evidence_ids": [],
  "influence_score": null
}
```

观点不得自动转化为事实。

### 11.6 Claim

所有报告中的关键句必须能映射到 Claim。

```json
{
  "claim_id": "uuid",
  "claim_type": "FACT|SOURCE_OPINION|MODEL_INFERENCE|HYPOTHESIS|UNKNOWN|CONFLICT",
  "statement": "结论文本",
  "subject_entities": [],
  "predicate": "has_event",
  "object": {},
  "as_of": "ISO-8601",
  "evidence_ids": [],
  "support_level": "direct|indirect|inferred",
  "confidence": 0.0,
  "valid_until": null,
  "review_status": "unreviewed"
}
```

### 11.7 Evidence

```json
{
  "evidence_id": "uuid",
  "source_id": "cninfo",
  "raw_item_id": "uuid",
  "title": "来源标题",
  "publisher": "发布者",
  "published_at": "ISO-8601",
  "retrieved_at": "ISO-8601",
  "url": "source-url",
  "excerpt": "支持该 Claim 的最小摘录",
  "evidence_type": "official_disclosure",
  "independence_group": "original-event-001",
  "source_tier": "S",
  "access_status": "ok"
}
```

`independence_group` 用于识别多个媒体转载同一个原始消息，防止把十篇转载误判为十个独立证据。

### 11.8 ModuleResult

```json
{
  "module": "abnormal_move_attribution",
  "version": "1.0.0",
  "status": "success|partial_success|degraded|insufficient_evidence|failed",
  "as_of": "ISO-8601",
  "inputs": {},
  "facts": [],
  "source_opinions": [],
  "analyses": [],
  "hypotheses": [],
  "open_questions": [],
  "evidence_ids": [],
  "confidence": 0.0,
  "warnings": [],
  "missing_data": [],
  "metrics": {},
  "artifacts": []
}
```

---

# 第五部分：功能模块设计

## 12. 模块清单

### P0：基础必建

1. `task_parser`
2. `entity_resolver`
3. `research_planner`
4. `retrieval_planner`
5. `source_router`
6. `evidence_manager`
7. `data_quality_checker`
8. `information_filter`
9. `dedup_clusterer`
10. `event_extractor`
11. `opinion_extractor`
12. `sentiment_attention_analyzer`
13. `abnormal_move_attribution`
14. `report_assembler`
15. `report_validator`
16. `knowledge_ingest_decider`
17. `feedback_recorder`

### P1：研究核心

18. `product_business_analysis`
19. `financial_analysis`
20. `valuation_analysis`
21. `industry_competition_analysis`
22. `catalyst_tracker`
23. `bull_bear_debate`
24. `theme_investment_value`
25. `lhb_analysis`
26. `knowledge_context_builder`

### P2：高级能力

27. `stock_alpha_review`
28. `industry_alpha_review`
29. `earnings_expectation_analysis`
30. `professional_review_panel`
31. `financial_forecast_model`
32. `historical_thesis_tracker`

## 13. 模块通用接口

每个模块必须实现：

```python
class ResearchModule:
    name: str
    version: str

    def validate_input(self, payload) -> ValidationResult:
        ...

    def plan(self, payload, context) -> ModulePlan:
        ...

    def run(self, payload, context) -> ModuleResult:
        ...

    def validate_output(self, result) -> ValidationResult:
        ...
```

每个模块目录必须包含：

```text
module_name/
├── spec.md
├── prompt.md
├── module.py
├── rules.yaml
├── examples/
└── tests/
```

`spec.md` 定义业务规则；`prompt.md` 只负责 LLM 推理说明；`rules.yaml` 保存可调整阈值。禁止把全部规则塞进一个 Prompt。

---

## 14. 产品与业务分析模块

输出：

- 产品矩阵
- 收入来源
- 业务分部
- 客户与渠道
- 商业模式
- 收费方式
- 订单或交付模式
- 成本结构
- 资本开支要求
- 周期性
- 业务质量
- 核心技术
- 护城河
- 关键依赖
- 待验证问题

商业模式不得仅使用通用标签。需根据业务特点加载分析 Overlay，例如：

- 项目制/订单制
- 重资产爬坡
- 周期价格驱动
- 消费品牌渠道
- 平台或订阅软件
- 监管医疗
- 出口制造
- 半导体设计
- 半导体设备
- 数据中心基础设施

输出必须区分：

- 已披露事实
- 对商业模式的解释
- 仍需验证的业务质量问题

---

## 15. 财务分析模块

第一版要求：

- 3—5 年三张表
- 收入、利润和现金流趋势
- 毛利率、净利率、ROE、ROIC
- 经营现金流与净利润匹配
- 应收、存货、合同负债
- 资本开支
- 有息负债
- 营运资本
- 非经常性损益
- 分部财务
- 财务异常和口径变化
- 同行业比较

不得仅输出指标涨跌。每个异常必须给出：

1. 数据事实
2. 可能解释
3. 支持证据
4. 反证
5. 待验证问题

预测模型属于后续高级能力，首次覆盖场景再启用。

---

## 16. 估值分析模块

### 16.1 估值方法选择器

根据以下因素选择方法：

- 是否盈利
- 盈利是否稳定
- 现金流是否稳定
- 是否周期行业
- 是否重资产
- 是否高速成长
- 是否处于商业化早期
- 是否存在分部业务
- 是否有合理可比公司
- 市场当前常用估值锚
- 一致预期是否可取得

候选方法：

- PE
- PB
- PS
- EV/EBITDA
- EV/Sales
- PEG
- DCF
- 分部估值
- 周期中枢估值
- 单位产能或单位资源估值
- 隐含预期反推

### 16.2 输出

- 选择的方法及理由
- 不采用其他方法的原因
- 当前指标
- 同行分布
- 历史分位
- 一致预期可得性
- 情景敏感性
- 市场当前隐含假设
- 估值失效条件

禁止输出目标价和买卖评级。

---

## 17. 行业与竞争分析模块

输出结构：

1. 行业定义
2. 产业链范围
3. 市场规模和增长驱动
4. 供需关系
5. 价格和成本传导
6. 竞争格局
7. 市占率及其证据
8. 进入壁垒
9. 替代风险
10. 技术路线
11. 政策影响
12. 周期位置
13. 关键指标
14. 相关上市公司
15. 核心争议
16. 待验证问题

行业研究必须映射到产业图谱坐标，而不是只生成孤立文章。

---

## 18. 催化剂模块

每个催化剂记录：

```yaml
catalyst_id:
entity_ids:
description:
expected_date:
date_precision:
status:
probability:
impact_path:
evidence_ids:
verification_questions:
last_checked_at:
```

分类：

- 公司公告
- 产品发布
- 产能投放
- 订单交付
- 价格变化
- 政策节点
- 财报节点
- 解禁与再融资
- 技术验证
- 行业数据
- 诉讼监管
- 客户认证

催化剂必须有后续验证问题，不得只列日期。

---

## 19. 多空观点模块

不采用简单“基本面优点＝多方、风险＝空方”的写法。

必须识别当前市场主要矛盾：

- 市场在交易什么
- 多方最核心的增量证据
- 空方最核心的反证
- 哪些信息已被广泛认知
- 哪个变量最可能改变预期
- 分歧来自事实、时间、幅度还是估值
- 双方分别需要什么证据才能被证伪

输出：

```text
当前主要矛盾
多方主张
多方证据
空方主张
空方证据
共识部分
真正分歧
待验证变量
可能改变叙事的事件
```

---

## 20. 专业评审模块

不复刻投资大师人格。使用专业审查框架：

- 基本面质量
- 成长持续性
- 周期位置
- 财务质量
- 竞争优势
- 估值约束
- 交易拥挤度
- 事件驱动可靠性
- 产业趋势
- 空头反证
- 信息完整度
- 证据质量

每项 0—5 分，但总分不能转化为买卖动作。

评审输出必须解释：

- 扣分原因
- 证据缺口
- 关键反例
- 最值得继续核查的三项问题

---

# 第六部分：数据采集层

## 21. 采集器统一接口

```python
class CollectorAdapter:
    source_id: str
    version: str

    def healthcheck(self) -> HealthStatus:
        ...

    def discover(self, query, time_window) -> list[ItemRef]:
        ...

    def fetch(self, item_ref) -> RawPayload:
        ...

    def normalize(self, raw_payload) -> list[RawItem]:
        ...

    def rate_limit_policy(self) -> RateLimitPolicy:
        ...
```

每个适配器必须支持：

- 健康检查
- 超时
- 重试
- 限速
- 缓存
- 分页
- 日期范围
- 来源字段
- 失败原因
- 解析版本
- 测试样例

## 22. 来源分组

### 22.1 法定披露与监管

候选：

- 巨潮资讯
- 上交所
- 深交所
- 证监会
- 国家企业信用信息
- 公司定期报告和公告

用途：

- 公司基本事实
- 财务数据
- 合同
- 融资
- 股权
- 治理
- 风险事件

### 22.2 政府、部委、统计与行业机构

候选：

- 国务院及部委
- 国家统计局
- 地方政府
- 行业协会
- 公共采购和招投标平台

用途：

- 政策
- 行业数据
- 项目审批
- 采购
- 产业背景

### 22.3 公司官方渠道

候选：

- 公司官网
- IR 页面
- 官方微信公众号
- 新闻稿
- 互动平台
- 投资者关系活动记录

### 22.4 市场和行情

候选：

- 本地行情数据引擎
- 可公开访问的数据接口
- 公开行情网页
- 交易所公开交易信息
- 龙虎榜

任何具体源都不能写死为唯一依赖。第一阶段必须先运行 `probe_sources.py`，测试：

- 可访问性
- 是否需要账号
- 历史深度
- 字段完整性
- 更新延迟
- 稳定性
- 限频
- 使用条款
- 是否可结构化

### 22.5 新闻与快讯

初始候选：

- 财联社
- 三大报
- 央视财经
- 新闻联播
- 华尔街见闻等财经媒体

### 22.6 行业资深自媒体

初始种子名单沿用需求文档：

- 半导体行业观察
- 智东西
- 芯东西
- 机器之心
- 量子位
- 新智元
- 甲子光年
- 高工锂电
- 医药魔法

这些仅作为候选，不自动进入正式来源名单。

### 22.7 社区与博主

候选平台：

- 雪球
- 淘股吧
- 微博
- 微信公众号
- 小红书
- 韭研公社

社区来源只用于：

- 关注点
- 叙事传播
- 市场分歧
- 线索发现

不得单独支持核心事实。

### 22.8 机构动向

可采信息类型：

- 机构调研
- 公开电话会议资料
- 机构晨报方向
- 研报数量和主题集中度
- 研报平台热度
- IMA 知识库汇总

必须区分：

- 真实机构行为
- 卖方覆盖行为
- 平台用户热度
- 二次汇总内容
- 未验证纪要

IMA 第一版标记为 `manual_or_client_only`。流程为用户分享链接或摘要进入 inbox，再由系统结构化，不把它作为稳定自动采集依赖。

---

## 23. 来源注册表

`registry/sources.yaml` 字段：

```yaml
source_id:
name:
platform:
source_type:
source_tier:
authority_score:
accuracy_score:
timeliness_score:
coverage_score:
stability_score:
originality_score:
opinion_influence_score:
access_level:
automation_level:
login_required:
paid:
storage_policy:
rate_limit:
update_frequency:
allowed_usage:
primary_topics:
status:
last_verified_at:
notes:
```

### 23.1 来源状态

- `candidate`
- `approved`
- `watchlist`
- `deprecated`
- `blocked`

### 23.2 访问状态

- `public`
- `public_but_unstable`
- `login_required`
- `client_only`
- `paid`
- `manual_only`
- `unavailable`

### 23.3 自动化等级

- `api`
- `html`
- `browser`
- `export_import`
- `manual`

### 23.4 存储权限

- `metadata_only`
- `metadata_and_excerpt`
- `full_text_allowed`
- `unknown`

本项目默认使用 `metadata_and_excerpt`，不保存全文。

---

## 24. 来源等级

来源等级与观点影响力必须分开。

### S 级

法定披露、监管、交易所、官方统计。

### A 级

公司官方、政府机构、正式采购、行业协会、可验证原始文件。

### B 级

高质量财经媒体、行业专业媒体、机构公开材料。

### C 级

有明确身份和历史记录的博主、自媒体、社区高影响用户。

### D 级

匿名消息、转述、截图、无法访问原文的二手内容。

规则：

- 核心事实优先 S/A。
- B 可补充背景。
- C 用于舆情和线索。
- D 只能进入待验证线索，不得进入核心结论。
- 多个转载同一原始消息只算一个独立证据。
- 来源等级不能自动决定观点正确性。

---

## 25. 主源与后备机制

后备机制按“数据字段或任务”定义，不按整个网站定义。

示例：

```yaml
company_announcement:
  primary: cninfo
  secondary:
    - sse
    - szse
  fallback:
    - company_ir
  minimum_acceptable: official_metadata

macro_data:
  primary: nbs
  secondary:
    - ministry_site
  minimum_acceptable: official_release

market_price:
  primary: local_market_engine
  secondary:
    - public_market_adapter_1
    - public_market_adapter_2
  minimum_acceptable: daily_ohlcv
```

当主源失败时：

- 记录失败
- 切换备源
- 标明数据降级
- 禁止估数
- 在报告中披露实际数据日

---

# 第七部分：信息筛选系统

## 26. 总体流程

```text
候选采集
→ 格式标准化
→ 精确去重
→ 语义聚类
→ 分类
→ 硬性否决
→ 信息价值评分
→ 事件合并
→ 报告筛选
→ 知识入库判断
```

采集、报告和知识入库使用不同阈值。

## 27. 硬性否决规则

以下内容不得进入晨报正文或产业图谱核心：

- 无法确认来源
- 无法确认主体
- 无法确认时间
- 纯标题党
- 广告或营销软文
- 无新增变量的重复内容
- 旧闻重新传播且无新变化
- 只有情绪没有事实或论据
- 匿名单一爆料
- 截图无原文
- 与投资研究无实质关联
- 同一来源自我重复
- 模型无法解释其影响路径

可保留在低优先级线索池，但必须有过期时间。

---

## 28. 信息价值评分

总分 100：

| 维度 | 权重 |
|---|---:|
| 新颖性 | 20 |
| 影响强度 | 20 |
| 权威与证据质量 | 15 |
| 确定性 | 15 |
| 影响范围 | 10 |
| 预期差/信息差 | 10 |
| 可验证性 | 5 |
| 市场相关性 | 5 |

### 28.1 新颖性

- 0：纯重复
- 1：表达变化，无事实变化
- 2：旧趋势的新评论
- 3：新数据或局部新进展
- 4：明确的新变量
- 5：改变原有框架的重大新变量

### 28.2 阈值

- 75—100：核心必读
- 65—74：晨报正文
- 55—64：附录或候选
- 40—54：结构化事件候选
- 低于 40：仅原始索引或丢弃

重大官方风险事件、重大政策或明确公司公告可触发强制纳入，不受总分阈值限制，但仍需说明影响尚不确定。

---

## 29. 去重与事件聚类

### 29.1 精确去重

使用：

- URL 规范化
- 外部 ID
- 标题标准化
- 内容哈希
- 发布者＋时间＋核心实体

### 29.2 语义聚类

聚类键：

- 主体
- 事件类型
- 时间
- 关键数值
- 产品/项目
- 原始来源

事件簇输出：

```json
{
  "canonical_event_id": "uuid",
  "first_seen": {},
  "official_confirmation": {},
  "related_items": [],
  "related_opinions": [],
  "spread_metrics": {},
  "conflicts": []
}
```

禁止简单选择“最早的一篇”而丢弃后续官方确认或不同观点。

---

# 第八部分：场景 Skill

## 30. 每日晨报

### 30.1 时间窗口

默认：

- 数据窗口：前一日 20:00 至当日 08:00
- 时区：Asia/Shanghai
- 建议触发时间：08:10
- 延迟执行时仍使用原始窗口
- 报告标明实际生成时间

### 30.2 信息分类

沿用需求文档四类：

- 宏观 Macro
- 产业 Industry
- 市场 Market
- 公司 Company

保留用户定义的子分类，不擅自改变分类树。

### 30.3 特殊过滤规则

市场动态只保留一条隔夜外围总结，内容包括：

- 美股主要指数
- 中概股
- 关键大宗商品
- 汇率和利率重大变化
- 对 A 股可能相关的极端事件

不逐条罗列普通市场波动。

产业类重点判断“是否有新变量”：

- 有新品、投产、中试、价格、产能、合同、收购等新事件，归入行业事件。
- 没有新事件，只是重复分析和吹风，归入行业趋势。
- 理论或实验室验证归入技术突破。
- 已进入产业化验证，归入行业事件。

### 30.4 输出结构

```markdown
# A股每日晨报 YYYY-MM-DD

## 执行说明
- 信息窗口
- 实际生成时间
- 数据覆盖
- 降级来源

## 一、重大必读
每条包含：事件、为什么重要、影响路径、相关方向、证据、待验证问题

## 二、宏观
按分类输出

## 三、产业
按行业事件、趋势、数据、政策、技术突破输出

## 四、公司
公告、经营动态、互动调研、融资、风险事件

## 五、市场关注
博主热帖、机构动向、媒体吹风
必须注明其为关注度或观点，不是事实

## 六、隔夜外围一句话总结

## 七、今日待验证事项

## 八、数据与来源说明
```

### 30.5 数量控制

软上限：

- 重大必读 3—8 条
- 产业和公司重要信息 8—18 条
- 舆情和机构关注 5—10 条
- 低优先级进入附录

不得为了凑数量降低质量。

---

## 31. 每日晚报

流程与晨报一致，默认窗口：

- 当日 08:00 至 20:00
- 建议触发 20:10

晚报重点增加：

- 当日信息与市场表现是否形成反馈
- 早间预期是否被证实
- 晚间新增公告
- 次日待验证事项

---

## 32. 异动分析

### 32.1 输入

- 股票、行业或概念
- 可选时间区间
- 可选日级或分钟级
- 用户可直接指出“今日异动”

第一版优先日级；分钟级作为扩展能力，但 Schema 和接口须预留。

### 32.2 检索策略

异动分析不能只检索晨报中已经筛选出的内容。

分四层扩展：

1. 正式披露和高价值事件
2. 公司、行业和概念相关候选事件
3. 媒体、机构和社区观点
4. 全源关键词、实体和语义回溯

### 32.3 候选原因评分

总分 100：

| 维度 | 权重 |
|---|---:|
| 时间匹配 | 25 |
| 实体/产业关联 | 20 |
| 新颖性 | 15 |
| 同板块或同主题联动 | 15 |
| 来源可靠性 | 10 |
| 解释覆盖度 | 10 |
| 可验证性 | 5 |

冲突、旧闻、时间不符和纯情绪分别扣分。

### 32.4 原因类型

- 直接触发
- 次级催化
- 行业或主题共振
- 市场风格背景
- 资金和交易结构
- 事后解释
- 无法验证的传闻
- 无法归因

### 32.5 输出结构

```markdown
# 异动分析：对象与日期

## 异动事实
行情、成交、行业相对表现、数据日期

## 结论摘要
主要原因、次要原因、背景因素、置信度

## 候选原因证据表
事件时间、发布时间、来源、关联方式、得分、反证

## 板块联动
是否为个股独立异动或行业共振

## 舆情与市场叙事
明确标记观点来源

## 排除项
看似相关但时间或证据不支持的消息

## 待验证问题

## 数据限制
```

### 32.6 强制规则

- 不得仅根据涨跌方向倒推利好利空。
- 不得把异动分析网站的结论直接当作事实。
- 不得把旧闻重新传播自动判定为新原因。
- 多原因并存时不得强行选一个。
- 找不到可信原因时必须输出“当前无法形成可信归因”。

---

## 33. 个股研报

### 33.1 模块调用顺序

```text
实体与基本信息
→ 产品业务
→ 行业竞争
→ 财务分析
→ 估值方法选择与比较
→ 催化剂
→ 情报监测
→ 舆情与多空主要矛盾
→ 近期异动（如有）
→ 龙虎榜（如有）
→ 专业评审
→ 核心观点
→ 质量校验
```

### 33.2 默认情报窗口

近一周。

对重大公告和长期逻辑可以回溯更长时间，但必须注明回溯范围。

### 33.3 报告结构

```markdown
# 公司名称（代码）个股研究报告

## 研究范围与数据截止

## 核心观点
事实、判断、关键假设、证据强弱

## 基本信息

## 产品、服务与商业模式

## 核心技术与护城河

## 行业概览与竞争格局

## 财务分析

## 估值分析
不输出目标价和评级

## 催化剂与验证日历

## 近一周情报监测

## 当前市场主要矛盾
多方、空方、共识、分歧、待验证变量

## 近期异动分析
仅在存在异动时

## 龙虎榜分析
仅在有数据时

## 专业评审

## 风险与未知

## 数据来源、缺失和降级说明
```

### 33.4 核心观点要求

核心观点不得只是全文摘要，必须回答：

- 公司当前最重要的研究变量是什么
- 市场可能在交易什么
- 哪个事实最支持当前逻辑
- 哪个反证最值得警惕
- 哪个变量最可能改变判断
- 当前证据质量如何

---

## 34. 首次覆盖

采用阶段化产物，但不照搬“一次只能做一个任务”的交互限制。

阶段：

1. 公司和行业研究
2. 历史财务与预测框架
3. 估值分析
4. 图表
5. 报告合成

每阶段必须有前置条件和中间产物。用户可以选择一键执行，但系统内部仍逐阶段校验。

不输出目标价和买卖评级；用估值区间、隐含假设和敏感性分析替代。

---

## 35. 个股复盘

### 35.1 行业 Alpha

```text
行业或概念收益－市场基准收益
```

识别显著异常区间，并匹配行业关键事件。

### 35.2 个股 Alpha

```text
个股收益－最相关且逻辑合理的行业/概念收益
```

基准选择同时考虑：

- 主营业务
- 行业归属
- 概念归属
- 历史相关性
- 异动期联动性

不得只选择统计相关性最高的随机概念。

### 35.3 输出

- 突出涨跌区间
- Alpha
- 成交与波动
- 事件
- 公司节点
- 行业节点
- 当时市场叙事
- 事后验证
- “股票基因”总结

---

## 36. 主题挖掘

### 36.1 第一关：信息是否有投资研究价值

必须回答：

- 是否有新变量
- 是否改变业内预期
- 是否改变供需
- 是否改变价值量
- 是否改变成本或价格
- 是否形成瓶颈
- 影响持续时间
- 影响是否已被广泛认知
- 是否能够映射到 A 股公司

### 36.2 传导链

```text
信息
→ 产业变量
→ 供需变化
→ 价格/成本/销量变化
→ 产业链环节利润变化
→ 受益或受损方向
→ A股公司映射
→ 证据和验证条件
```

### 36.3 输出分层

- 直接受益
- 间接受益
- 仅概念相关
- 可能受损
- 证据不足

禁止因为公司拥有概念标签就判定为受益。

---

# 第九部分：龙虎榜

## 37. 席位库

UZI 的“席位识别＋机构与游资比较＋同板块辨识度”可以作为结构参考，但席位库必须重新备案。

`registry/lhb_seats.csv` 字段：

```text
seat_id
broker_branch
investor_alias
style
typical_capital_range
first_confirmed_at
last_confirmed_at
confidence
evidence_urls
disputed
status
notes
```

### 37.1 更新规则

- 现有开源名单只能作为 candidate。
- 必须记录证据和时间。
- 席位迁移、共用和争议必须保留。
- 过期映射不能永久有效。
- 无法确认具体游资时只写营业部，不猜身份。

### 37.2 输出语言

禁止“可以跟”“格局票”等操作性表述。改为：

- 资金结构特征
- 机构与活跃席位净买卖
- 买卖集中度
- 同板块上榜情况
- 身份识别置信度
- 数据限制

---

# 第十部分：产业图谱与知识库

## 38. 三套并存分类

### 38.1 稳定行业骨架

优先使用稳定行业分类作为主树，例如申万一级、二级、三级。

### 38.2 产业链骨架

按真实产业环节拆分：

- 上游材料和设备
- 中游制造和组件
- 下游产品与应用
- 支撑基础设施
- 服务与软件

### 38.3 动态主题标签

通达信概念和市场临时主题作为标签，不承担稳定树结构。

---

## 39. 第一批行业骨架

### 39.1 AI 硬件

```text
AI硬件
├── 算力芯片
├── AI服务器
├── 存储与HBM
├── 先进封装
├── PCB
├── 光模块与光通信
├── 网络交换
├── 电源
├── 液冷
├── 数据中心建设
└── 边缘AI设备
```

### 39.2 半导体

```text
半导体
├── EDA与IP
├── 芯片设计
├── 晶圆制造
├── 封装测试
├── 半导体设备
├── 半导体材料
├── 功率半导体
├── 模拟芯片
├── 存储芯片
├── 传感器
└── 分销与服务
```

### 39.3 AI 软件

```text
AI软件
├── 基础模型
├── 推理与训练平台
├── Agent平台
├── 数据与知识库
├── 开发工具
├── 企业软件
├── 行业应用
├── 安全与治理
└── 算力调度与运维
```

以上是首版骨架，后续通过用户审核迭代。

---

## 40. 节点类型

- `Industry`
- `IndustrySegment`
- `Company`
- `Product`
- `Technology`
- `Material`
- `Equipment`
- `Application`
- `Policy`
- `Event`
- `Metric`
- `PersonOrInstitution`
- `Report`
- `InvestmentTheme`

## 41. 关系类型

- `BELONGS_TO`
- `UPSTREAM_OF`
- `DOWNSTREAM_OF`
- `SUPPLIES`
- `PURCHASES_FROM`
- `PRODUCES`
- `USES_TECHNOLOGY`
- `APPLIED_IN`
- `COMPETES_WITH`
- `SUBSTITUTES`
- `BENEFITS_FROM`
- `HARMED_BY`
- `AFFECTS`
- `MENTIONED_IN`
- `SUPPORTED_BY`
- `CONTRADICTED_BY`
- `HAS_METRIC`
- `HAS_CATALYST`

---

## 42. 图谱节点结构

```json
{
  "node_id": "industry_segment:advanced_packaging",
  "node_type": "IndustrySegment",
  "name": "先进封装",
  "aliases": [],
  "description": "当前有效描述",
  "status": "active",
  "valid_from": null,
  "valid_to": null,
  "evidence_ids": [],
  "version": 1,
  "last_reviewed_at": null,
  "review_status": "approved"
}
```

## 43. 关系结构

```json
{
  "edge_id": "uuid",
  "source_node_id": "company:xxx",
  "relation": "PRODUCES",
  "target_node_id": "product:xxx",
  "attributes": {},
  "valid_from": null,
  "valid_to": null,
  "confidence": 0.0,
  "evidence_ids": [],
  "review_status": "candidate",
  "version": 1
}
```

---

## 44. 三层存储

### 44.1 原始索引层

保存元数据、链接、哈希、摘录。

### 44.2 事件与观点层

达到基本结构化标准的信息进入事件库或观点库。

基本要求：

- 主体明确
- 时间明确
- 来源明确
- 可映射实体
- 不属于纯垃圾信息

### 44.3 核心产业知识层

必须满足：

- 对产业结构、供需、技术、成本、价格、产能或竞争格局有实质影响
- 能映射明确节点
- 证据等级足够
- 与已有知识关系明确
- 有有效期或验证节点
- 已通过人工审核

晨报和晚报不自动把全部内容写入核心图谱。

---

## 45. 入库状态

```text
inbox
→ parsed
→ event_accepted
→ graph_candidate
→ approved
→ active
→ superseded / expired / rejected
```

## 46. 图谱变更候选

每次候选更新生成 Markdown：

```markdown
# 图谱变更候选

## 变更类型
新增节点 / 新增关系 / 修改属性 / 废止关系

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
```

第一版通过 Markdown 审核，不开发复杂管理后台。

---

## 47. 版本和失效

不得覆盖历史。

例如产能计划：

```text
2025-08：计划2026-Q2投产
2026-04：延期至2026-Q4
当前状态：预计2026-Q4
历史版本：保留
```

不同知识设置复核周期：

- 公司基础信息：低频
- 产能和项目：到期强制核查
- 产品价格：短期
- 行业格局：季度或重大事件
- 博主观点：仅历史观点，不进入长期事实
- 政策预期：落地或失效后转历史

---

# 第十一部分：报告与文件管理

## 48. 命名规则

```text
reports/morning/YYYY/YYYY-MM/YYYY-MM-DD_morning.md
reports/evening/YYYY/YYYY-MM/YYYY-MM-DD_evening.md
reports/daily_review/YYYY/YYYY-MM/YYYY-MM-DD_review.md
reports/stocks/{ticker}/{YYYY-MM-DD}_{scenario}.md
reports/industries/{industry_id}/{YYYY-MM-DD}_{scenario}.md
reports/themes/{theme_id}/{YYYY-MM-DD}_{scenario}.md
reports/runs/{task_id}/
```

## 49. 报告 Front Matter

```yaml
---
report_id:
scenario:
title:
created_at:
as_of:
timezone: Asia/Shanghai
entities:
time_window:
data_status:
source_coverage:
model_route:
runtime_seconds:
validator_status:
knowledge_coordinates:
---
```

## 50. 运行目录

每次任务保存：

```text
reports/runs/{task_id}/
├── task.json
├── plan.json
├── retrieval_log.jsonl
├── module_results/
├── evidence_index.json
├── validation.json
├── final.md
└── errors.log
```

这使任务可复盘，并降低大型工程中的幻觉和不可追踪修改。

---

# 第十二部分：模型路由

## 51. 路由原则

### 51.1 不使用模型的任务

- 数值计算
- 文件处理
- Schema
- 规则阈值
- 数据库
- 哈希去重
- 报告机械校验

### 51.2 V4 Flash

默认承担：

- 分类
- 摘要
- 实体和事件抽取
- 观点抽取
- 简单信息价值评分
- 模板填充
- 普通代码实现
- 单元测试生成

### 51.3 V4 Pro

升级条件：

- 多来源重大冲突
- 复杂产业链传导
- 主题价值量变化
- 异动原因候选接近
- 超过规定数量的反证
- 需要跨多个行业节点推理
- Flash 输出连续两次未通过逻辑校验
- 图谱本体变更候选
- 核心规则修改

### 51.4 Codex

可选使用：

- 跨目录复杂重构
- 大型代码库理解
- CI 或测试根因
- 安全审查
- 发布前代码审查
- Flash/Pro 连续修复失败

## 52. 业务升级与基础设施失败分离

必须区分：

1. **业务复杂度升级**：应用层主动从 Flash 路由到 Pro。
2. **服务故障回退**：Hermes provider fallback 处理限流、服务错误等。

不得把 provider fallback 当作业务推理路由。

## 53. 路由记录

```json
{
  "module": "theme_investment_value",
  "initial_model": "deepseek-v4-flash",
  "final_model": "deepseek-v4-pro",
  "escalation_reason": "conflicting_supply_chain_evidence",
  "attempts": 2
}
```

---

# 第十三部分：Hermes 集成

## 54. Skill 结构

每个场景 Skill 使用标准 `SKILL.md`：

```yaml
---
name: morning-brief
description: 生成A股每日晨报
version: 1.0.0
platforms: [windows, linux]
metadata:
  hermes:
    tags: [finance, a-share, research]
    requires_tools: [terminal]
    config:
      - key: research.project_path
        description: 项目绝对路径
        default: ""
---
```

Skill 中只保留：

- 触发条件
- 输入参数
- CLI 调用方式
- 结果文件路径
- 失败处理
- 验证命令

复杂研究规则必须存在于项目 `spec.md` 和配置文件中。

## 55. Cron 设计

建议任务：

```yaml
morning_brief:
  schedule: "10 8 * * *"
  timezone: Asia/Shanghai
  skill: morning-brief

evening_brief:
  schedule: "10 20 * * *"
  timezone: Asia/Shanghai
  skill: evening-brief

daily_review:
  schedule: "30 18 * * 1-5"
  timezone: Asia/Shanghai
  skill: daily-review
```

创建 Cron 时必须设置：

- 绝对 `workdir`
- 明确模型
- 明确 provider
- 输出目录
- 任务名称
- 失败告警

模型固定应由用户通过 Hermes CLI、Dashboard 或配置完成，而不是依赖 Cron 运行中的 Agent 自己修改模型。

## 56. 补跑机制

每个定时场景启动前执行：

```text
检查目标时间窗口
→ 检查对应报告是否存在且通过校验
→ 不存在则补跑
→ 已存在则幂等退出
```

报告 Front Matter 标记：

```yaml
scheduled_for:
actual_started_at:
delayed: true
delay_seconds:
```

---

# 第十四部分：质量与幻觉控制

## 57. 核心规则

1. 无来源，不写事实。
2. 无原始证据，不把媒体总结升级为确定事实。
3. 数字必须记录来源、口径和数据日。
4. 观点必须标明说话者。
5. 推断必须标明为模型推断。
6. 事件时间与文章时间必须分开。
7. 多篇转载不得当作独立证据。
8. 数据过期必须显式标记。
9. 证券代码和公司名必须通过实体映射。
10. 无法归因允许结束任务。
11. 不得将缺失数据解释为“没有变化”。
12. 不得将舆情热度解释为机构买入。
13. 不得生成目标价和交易建议。

## 58. 置信度

置信度由规则计算，不允许只依赖 LLM 自评。

建议因素：

| 因素 | 方向 |
|---|---|
| 原始官方证据 | 加分 |
| 独立来源数量 | 加分 |
| 时间一致 | 加分 |
| 数据完整 | 加分 |
| 直接证据 | 加分 |
| 来源冲突 | 扣分 |
| 关键字段缺失 | 扣分 |
| 长推理链 | 扣分 |
| 匿名消息 | 大幅扣分 |
| 旧闻重传 | 大幅扣分 |

最终同时输出分数和原因。

## 59. 机械校验器

`validate_report.py` 至少检查：

- Front Matter
- 必须章节
- 绝对日期
- 数据截止时间
- 引用覆盖率
- 无来源数字
- 数据日期
- 来源观点标签
- 推断标签
- 降级说明
- 禁止词
- 目标价或买卖建议
- 缺失模块说明
- 相互冲突结论
- 文件命名
- JSON Schema

校验不通过时：

- 自动修复格式类问题
- 逻辑和证据问题返回模块重跑
- 最多重跑两次
- 仍失败则输出 partial，不得无限循环

---

# 第十五部分：用户反馈闭环

## 60. 反馈记录

用户对报告的人工修改必须记录：

```yaml
feedback_id:
report_id:
module:
original_output:
user_revision:
error_type:
severity:
rule_implication:
accepted_change:
created_at:
```

错误类型：

- 事实错误
- 来源错误
- 分类错误
- 重要性误判
- 重复信息
- 遗漏
- 推理错误
- 表达偏好
- 产业图谱坐标错误
- 估值方法错误

## 61. 规则更新流程

```text
用户反馈
→ 生成变更候选
→ 判断个案或通用问题
→ 修改规则
→ 运行回归测试
→ 审核
→ 发布新规则版本
```

单次反馈不得直接自动改写核心规则。

---

# 第十六部分：测试体系

## 62. 测试分层

### 62.1 单元测试

- 日期
- 去重
- 哈希
- 实体映射
- 财务指标
- 估值公式
- Schema
- 文件命名

### 62.2 合约测试

每个采集器对统一接口进行测试。

### 62.3 来源健康测试

每日或手动检查：

- 可访问
- 字段是否变化
- 延迟
- 空结果
- 登录要求变化
- 解析失败率

### 62.4 黄金测试

由设计方生成，用户反馈修订。

第一批：

- 5 个个股异动案例
- 3 个行业异动案例
- 5 条高价值主题信息
- 5 条应拒绝信息
- 3 期晨报
- 3 个图谱入库案例
- 3 个不应入库案例
- 2 个来源冲突案例
- 2 个主源失败案例

### 62.5 评测指标

晨报：

- 重大信息召回率
- 正文有效信息比例
- 重复率
- 来源覆盖
- 过期信息率

异动：

- 原因时间匹配
- 证据支持
- 错误归因率
- 无法归因识别能力

个股研报：

- 引用覆盖率
- 事实错误率
- 模块完整度
- 主要矛盾质量
- 待验证问题质量

图谱：

- 错误节点率
- 错误关系率
- 重复节点率
- 证据覆盖
- 历史版本完整度

---

# 第十七部分：工程实施阶段

## 63. Phase 0：项目骨架与契约

交付：

- 目录
- 配置
- Schema
- SQLite
- 日志
- CLI
- 模块接口
- 采集器接口
- 报告 Front Matter
- 基础校验器

验收：

- 可以运行空任务
- 可以生成 task、plan 和 run 目录
- 所有 Schema 测试通过
- 相同任务 ID 幂等

## 64. Phase 1：来源探测与数据底座

交付：

- `probe_sources.py`
- 来源注册表
- 官方公告适配器
- 政策适配器
- 公司官方适配器
- 至少一个行情适配器
- 手动 inbox
- 主备路由

验收：

- 能输出每个源的访问状态
- 账号要求明确
- 不保存全文
- 主源失败可降级
- 数据日清晰

## 65. Phase 2：信息筛选与晨报

交付：

- 分类
- 去重
- 事件聚类
- 信息评分
- 晨报模板
- Cron Skill
- 补跑
- 校验器

验收：

- 给定测试候选池生成晨报
- 旧闻不进入正文
- 隔夜市场只有一条总结
- 重大信息有证据
- 报告可重复生成且不重复写入

## 66. Phase 3：异动分析

交付：

- 行情异常接口
- 分层检索
- 候选原因评分
- 板块联动
- 排除项
- 无法归因状态

验收：

- 至少通过 5 个案例
- 不把异动网站结论直接当事实
- 可以输出多个原因
- 可以输出无法归因

## 67. Phase 4：个股研报

交付：

- 产品业务
- 行业
- 财务
- 估值
- 催化剂
- 情报监测
- 多空
- 评审
- 报告合成

验收：

- 无目标价和买卖建议
- 每个关键数字有来源
- 估值方法有选择理由
- 能指出主要矛盾
- 缺数据时部分成功

## 68. Phase 5：产业图谱

交付：

- 本体
- 节点关系 Schema
- AI 硬件、半导体、AI 软件初始骨架
- 入库候选
- Markdown 审核
- 版本历史
- Wiki 页面生成

验收：

- 晨报事件可产生候选
- 未审核不进入核心图谱
- 修改不覆盖历史
- 报告可关联图谱坐标

## 69. Phase 6：研究型工作流（6A / 6B / 6C 并行治理）

### 69.1 结构与七场景分配（正式冻结）

Phase 6 完整七场景，`剩余场景 = 7`，全部一次性冻结为三个业务 Track：

```text
6A：industry_research（行业研究）、theme_discovery（主题挖掘）
6B：evening_brief（每日晚报）、daily_review（每日复盘）、stock_review（个股复盘）
6C：first_coverage（首次覆盖）、earnings_expectation（财报预期）
```

不增加任何用户未定义的新业务场景。

### 69.2 串行治理拓扑（V1.3 正式冻结）

并行开发已正式取消。Phase 6 唯一允许的工程模式为串行里程碑门控：

```text
P6-S0  Serial Governance Reset (governance-only)
  ↓
P6-S1  6B Final Closure + Acceptance + Merge
  ↓
P6-S2  6A Final Closure + Acceptance + Merge
  ↓
P6-S3  Earnings Expectation
  ↓
P6-S4  First Coverage
  ↓
P6-S5  Central Enablement + Cross-Scenario Acceptance
  ↓
P6-S6  Governance Closeout
```

依赖规则：

1. P6-S0 串行（治理重置，仅文档）；
2. P6-S1 依赖 S0 PASS + merged；
3. P6-S2 依赖 S1 PASS + merged（此时顺序解决 6B + 6A schema registry）；
4. P6-S3 依赖 S2 PASS + merged；
5. P6-S4 依赖 S3 PASS + merged；
6. P6-S5 依赖 S1-S4 全部 PASS + merged；
7. P6-S6 依赖 S5 PASS + merged。

任意时刻仅一个 active Phase 6 业务分支/工作树。
上一 milestone 未 PASS+MERGED 则下一 milestone NOT_AUTHORIZED。
共享控制面 enablement 留到 P6-S5，不得提前。

### 69.3 Graph→Research 设计边界（正式冻结，READ ONLY）

Phase 6A 第一次正式允许 Graph→Research，但只能：

```text
Versioned Graph
→ GraphQueryService
→ KnowledgeContextBuilder
→ read-only Research Context
```

必须明确：

- `Graph→Research: READ ONLY`
- `as_of: REQUIRED`（禁止 future knowledge leakage；历史研究只能看到该 `as_of`
  时刻合法有效的知识状态）
- `SQLite: 唯一 graph authority`
- `JSON mirror: 非权威，只是 deterministic read-only export`

禁止设计成：

```text
Scenario → raw SQL graph tables
Scenario → JSON mirror → authoritative knowledge
```

### 69.4 KnowledgeContext / Evidence 边界（正式冻结）

`KnowledgeContext != Evidence`。

Graph 只能帮助：

- 研究导航
- 实体发现
- 产业坐标
- 关系发现
- 检索方向
- 上下文组织

如果 Graph FACT 要进入报告事实链：

```text
Graph object
→ evidence_ids
→ authoritative Evidence reload
→ Evidence validation
→ Claim / ResearchFinding
→ Markdown
```

不得：

```text
Graph FACT → 直接写成报告事实
```

Graph 中 `MODEL_INFERENCE` 即使已进入 active graph，也不得自动渲染成 FACT。

### 69.5 时间治理（正式冻结）

- Phase 6 Graph→Research 必须支持并强制 `as_of`。
- 禁止 future knowledge leakage：历史研究只能看到该 `as_of` 时刻合法有效的知识状态。
- Phase 6C forecast 同样受 `as_of` / `historical cutoff` / `forecast period` 治理。

### 69.6 Graph Write Boundary（正式冻结）

Phase 6 不允许：

```text
Scenario → active GraphNode / GraphEdge
```

永久链路继续为：

```text
RawItem
→ Evidence
→ Claim / Event / ResearchFinding
→ GraphChange Proposal
→ GraphChange Candidate
→ Human Review
→ Validator
→ Deterministic Apply
→ Versioned Graph
```

必须写明：

```text
LLM can propose
LLM cannot approve

human can approve
human cannot bypass validator
```

### 69.7 Candidate Integration 顺序（正式冻结）

每个 Phase 6 新场景必须：

```text
Research Capability Acceptance
        ↓
Candidate Integration Authorization
        ↓
Research → GraphChange Candidate
```

不得在场景第一次上线时同时开放长期图谱写入候选入口。原则：

```text
research first
candidate integration second
active graph never direct
```

### 69.8 6A / 6B / 6C 方法论

#### 6A

**industry_research** 至少覆盖：行业边界、稳定行业分类、产业链结构、关键环节、供需、
竞争格局、技术路径、材料 / 设备、应用、政策、关键指标、关键公司产业坐标、催化剂、
风险、核心争议、反证、待验证问题、证据质量。

**theme_discovery** 正式定义为：

```text
Event / Policy / Technology Change
→ Theme Hypothesis
→ Evidence
→ Industry Mapping
→ Related Entities
→ Support / Counter Evidence
→ Lifecycle / Invalidating Conditions
→ Research Questions
```

主题挖掘不是自动荐股。

#### 6B

**evening_brief** = morning_brief 同构复用（同一 BriefPipeline）。
唯一业务差异为时间窗口：
- morning_brief: [D-1 20:00, D 08:00)
- evening_brief: [D 08:00, D 20:00)

旧的 evening incremental methodology（material_update / new_since_morning /
already_known_in_morning / morning/evening cross-report dedup / 早间预期验证 /
市场反馈验证）正式废止。

**daily_review** 必须区分：`observed_fact` / `previous_research_view` /
`new_evidence` / `updated_interpretation` / `remaining_unknown`。

**stock_review** 必须是增量复盘，不得每次重跑完整 Phase4 研报。

6B 不 hard-depend on 6A。

#### 6C

**earnings_expectation** 属于 `HYPOTHESIS / FORECAST`，不是 FACT。预测必须记录：
`as_of`、`forecast_period`、`historical_input_periods`、`evidence`、`assumptions`、
`method`、`scenario`、`uncertainty`、`calculation_version`。确定性算术必须由代码完成。

**first_coverage** 是编排层：

```text
Company Profile
→ Phase4 Equity Research
→ Phase6A Industry Research
→ Peer Context
→ Earnings Expectation
→ Valuation Applicability
→ Catalysts / Risks
→ Counter Evidence
→ Open Questions
→ First Coverage Report
```

不得复制第二套 financial / valuation / evidence / LLM engine。

### 69.9 输出永久边界（正式冻结）

Phase 6 不改变项目输出政策。全部七场景继续禁止：目标价、买入评级、卖出评级、
增持 / 减持建议、仓位建议、明日交易建议、自动荐股。明确写入：

```text
theme_discovery ≠ stock picking
first_coverage ≠ brokerage rating
earnings_expectation ≠ trading signal
daily_review ≠ next-day trading plan
```

### 69.10 Ontology 与 Source Expansion（正式冻结）

```text
new node_type: NOT_AUTHORIZED
new relation: NOT_AUTHORIZED
relation semantic change: NOT_AUTHORIZED
automatic ontology expansion: PROHIBITED
```

Phase 6 也不得顺手扩张 source whitelist。新来源必须独立：

```text
discovery → probe → source governance → verification → registry update
```

### 69.11 实施门禁

```text
TASKBOOK_STATUS: APPROVED
IMPLEMENTATION_STATUS: NOT_STARTED
CURRENT_MILESTONE: P6-G0
NEXT_MILESTONE: P6-F0
P6-F0: NOT_AUTHORIZED_UNTIL_G0_ACCEPTANCE
P6-A: NOT_AUTHORIZED
P6-B: NOT_AUTHORIZED
P6-C: NOT_AUTHORIZED
```

“任务书 approved”不得被解释成整个 Phase 6 已授权开发。正式任务书见
`docs/tasks/phase6-research-workflows.md`，正式设计决策见 `DECISIONS.md` #41。

---

# 第十八部分：给 DeepSeek/Hermes 的执行规则

## 70. 总指令

工程 Agent 必须遵守：

1. 先读取本文件、AGENTS.md 和当前阶段任务。
2. 每次只实现一个明确里程碑。
3. 不增加业务场景。
4. 不自行修改研究规则。
5. 不把采集逻辑写进 Prompt。
6. 所有外部数据先经过统一 Schema。
7. 所有关键行为要有测试。
8. 不伪造 API、字段、网页选择器或数据。
9. 未验证数据源时建立 stub，并明确 TODO。
10. 修改完成后运行测试和校验。
11. 输出变更文件、测试结果和剩余问题。
12. 每个阶段单独 Git commit。

## 71. 单任务执行模板

```text
你正在实现 AI＋投研项目的一个工程任务。

必须先阅读：
1. AGENTS.md
2. docs/engineering-guide.md
3. 当前模块 spec.md
4. 相关 schemas
5. 现有测试

任务范围：
[明确列出]

允许修改：
[文件或目录]

禁止修改：
[文件或目录]

验收条件：
[明确测试]

约束：
- 不猜测外部接口
- 不自行改变业务规则
- 不输出目标价和交易建议
- 所有数据必须经过 Schema
- 所有失败必须显式返回状态
- 完成后运行测试

最终仅报告：
- 修改了什么
- 测试结果
- 未解决问题
```

## 72. Flash 升级 Pro 的工程规则

应用层满足任一条件时升级：

```text
reasoning_conflict_count >= 3
independent_high_tier_sources_conflict == true
supply_chain_hops > 3
candidate_causes_top2_score_gap < 8
flash_validation_failures >= 2
ontology_change == true
core_rule_change == true
```

调用 Pro 后仍不能解决时，输出待人工审核，不继续升级或循环。

## 73. Codex 使用模板

```text
请只审查以下范围：
[目录或提交]

目标：
[具体问题]

必须读取：
[文件]

不要：
- 重写整个项目
- 修改研究规则
- 增加依赖
- 改变公开接口

请输出：
1. 根因
2. 最小修复
3. 风险
4. 测试
```

---

# 第十九部分：完成定义

## 74. 模块完成定义

一个模块只有同时满足以下条件才算完成：

- 有 spec
- 有输入输出 Schema
- 有实现
- 有失败状态
- 有至少一个正常测试
- 有至少一个边界测试
- 有至少一个失败测试
- 有日志
- 有版本号
- 有示例
- 能被场景调用
- 输出通过验证器

## 75. 场景完成定义

- 能从自然语言触发
- 参数可默认
- 生成执行计划
- 调用模块
- 数据不足可降级
- 报告有数据截止时间
- 关键结论有证据
- 禁止项检查通过
- 可重复执行
- 生成运行记录
- 用户反馈可关联

## 76. 数据源完成定义

- 已真实访问验证
- 账号要求明确
- 使用方式明确
- 字段映射明确
- 更新频率明确
- 限速明确
- 存储政策明确
- 健康检查存在
- 有主备定位
- 失败不会伪造数据

---

# 第二十部分：风险与应对

## 77. 最大风险

### 77.1 免费来源不稳定

应对：

- 来源抽象
- 主备
- 健康检查
- 人工 inbox
- 不锁死平台

### 77.2 舆情平台登录和反爬

应对：

- 降级为人工分享
- 浏览器自动化只在合规范围
- 不作为关键事实唯一来源
- 保持适配器可插拔

### 77.3 LLM 产生流畅但错误的研究

应对：

- Claim 和 Evidence
- 硬性校验
- 事实/观点/推断分离
- 未知状态
- 回归测试

### 77.4 项目规模过大

应对：

- 架构完整、实施分阶段
- 场景纵向打通
- 不同时开发全部模块
- 每阶段验收后再进入下一阶段

### 77.5 电脑不长期开机

应对：

- 幂等补跑
- 延迟标记
- 未来迁移常开设备
- 调度与业务代码分离

### 77.6 Codex Plus 额度不确定

应对：

- Codex 只承担高价值工程任务
- Flash 批量实现
- 任务拆小
- 仓库规则文件化
- 限制 Codex 修改范围

---

# 第二十一部分：立即执行清单

工程执行从以下顺序开始：

1. 创建仓库和目录。
2. 写入本文件为 `docs/engineering-guide.md`。
3. 创建 `AGENTS.md`，摘要写入不可违反规则。
4. 创建所有核心 Schema。
5. 创建 SQLite 初始迁移。
6. 创建 Task、ModuleResult、Evidence、Claim 数据类。
7. 创建 CLI：`research run`、`research validate`、`research probe-sources`。
8. 创建空 Orchestrator。
9. 创建来源注册表模板。
10. 创建采集器抽象类和假适配器。
11. 创建运行目录和日志。
12. 创建基础报告验证器。
13. 完成 Phase 0 测试。
14. 在 Phase 0 通过前，不开始网页采集器。

---

# 参考项目的使用边界

- Anthropic Financial Services：借鉴场景编排、阶段前置条件、模块化研究方法和文件式 Skill 组织；不照搬美股数据源、目标价、评级及一次只能执行一个任务的交互限制。
- China Stock Research Skills：借鉴来源优先、事实/解读/待验证问题分层、模块组合和公开信息研究规范。
- UZI-Skill：借鉴龙虎榜席位库、分析流水线、报告校验和评审思想；不照搬投资大师人格、交易语言和未经重新验证的席位映射。
- Market Daily Review：借鉴固定模板、数据日标记、优雅降级、幂等定时任务和机械校验器；不绑定其特定数据服务。
- free-stockdb：作为本地行情、板块映射和技术指标候选底座；不将其视为公告、研报、舆情和机构数据的替代品。

---

# 最终决策摘要

```yaml
project:
  architecture: complete
  implementation: phased
  market: A-share
  user_mode: personal

priority_scenarios:
  - morning_brief
  - abnormal_move_analysis
  - stock_research_report

runtime:
  agent: Hermes
  default_model: deepseek-v4-flash
  escalation_model: deepseek-v4-pro
  optional_code_reviewer: Codex
  max_runtime_minutes: 30

data:
  strategy: public_first
  paid_sources: none
  full_text_storage: false
  fallback_required: true
  unknown_is_allowed: true

outputs:
  default: markdown
  excel_when_deterministic_model_needed: true
  target_price: forbidden
  investment_recommendation: forbidden
  buy_sell_language: forbidden

knowledge:
  initial_domains:
    - AI_hardware
    - semiconductor
    - AI_software
  core_change_requires_review: true
  history_must_be_preserved: true

quality:
  claim_evidence_required: true
  deterministic_validator_required: true
  user_feedback_recorded: true
  regression_before_rule_update: true
```
