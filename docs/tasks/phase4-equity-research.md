# Phase 4：A 股个股深度研报 —— 正式工程任务书

> 文档类型：正式实现授权边界
> 下达日期：2026-08-06
> 授权基线：`2b7827c`（Phase 3 收尾后，docs-only）
> Phase 3 代码基线：`c398e58`
> 状态：**工程基础 PASS；完整研究能力 PARTIAL_SUCCESS；Phase 5 BLOCKED（2026-08-07 复验）**
> 权威边界：本文档仅细化阶段实施授权；与 `docs/engineering-guide.md` 或经正式评审的
> `docs/project-state/DECISIONS.md` 冲突时，以前两者为准，不得静默覆盖。

---

## 1. 任务性质

本任务书是 Phase 4 的正式实现授权边界。

工程 Agent 必须：

1. 先读取 `AGENTS.md`、工程指南、状态文档和本任务书；
2. 按提交序列逐步实现；
3. 不增加投资决策能力；
4. 不接入未经验证的数据源；
5. 不修改 Phase 0—3 研究规则；
6. 不提前实现 Phase 5；
7. 每个里程碑完成后运行对应测试；
8. 最终独立验收通过前不得声明 Phase 4 PASS。

## 2. In scope

* 公司与证券对象；
* 财务文件和数据导入；
* 文档登记、哈希、页码和表格块；
* 财务事实标准化；
* 财务公式；
* 财务质量和异常检测；
* 业务分部；
* 行业位置和竞争因素；
* 同行候选、评分、选择；
* 估值观察；
* 可选情景预测；
* Phase 2/3 复用；
* 催化剂、风险、争议、反证；
* Claim/Evidence；
* 研报合成；
* Markdown；
* Validator；
* CLI；
* Hermes Skill；
* 离线测试；
* 黄金案例；
* 状态文档收尾。

## 3. Out of scope

* 目标价；
* 评级；
* 交易建议；
* 仓位建议；
* 自动荐股；
* DCF/DDM；
* 组合与回测；
* 自动全市场扫描；
* 付费数据源；
* 通用 OCR 平台；
* 浏览器登录绕过；
* 自动抓取所有公司全文；
* 知识图谱批准和核心入库；
* Phase 5 产业图谱；
* Phase 6 行业研究、首次覆盖等独立场景。

## 4. 非目标

* 不以"写得像券商研报"为首要目标；
* 不追求无数据时仍生成完整篇幅；
* 不用固定阈值代替证据；
* 不把管理层自述直接认定为竞争优势；
* 不把估值低写成低估；
* 不把预测写成公司事实；
* 不用模型补财务数字。

## 5. 依赖与验收前置条件

必须存在：

* Python 3.11+；
* 当前 30 Schema 和模型契约测试通过；
* 迁移 001—004 可在临时数据库执行；
* Phase 3 代码基线未被破坏；
* 本任务书新增的注册表和配置文件；
* 离线财务 fixture；
* 离线文档 fixture；
* Fake Provider；
* 至少一个完整个股黄金案例。

真实 Provider、在线财务源、自动历史日线源不属于 **engineering foundation PASS**
前置条件；但缺失时必须降低单次报告和完整研究能力状态。Phase 5 解锁前，核心语义模块
仍须通过真实 Provider 或经批准的结构化人工输入达到最低覆盖。

## 6. 允许的研究状态

```text
SUCCESS
PARTIAL_SUCCESS
DATA_DEGRADED
INSUFFICIENT_DATA
SOURCE_CONFLICT
VALIDATION_FAILED
FAILED
```

### 最低数据状态

| 状态                | 最低条件                                                    |
| ----------------- | ------------------------------------------------------- |
| SUCCESS           | 公司/证券已解析；至少 3 个可比年度；核心三表可用；关键事实有证据；同行和估值满足完整样本或被明确标为非适用 |
| PARTIAL_SUCCESS   | 至少 2 个可比年度，部分三表或分部缺失，但可形成有限研究                           |
| DATA_DEGRADED     | 核心数据可用，但在线来源、同行、分部、估值或 LLM 模块降级                         |
| INSUFFICIENT_DATA | 少于 2 个可比年度，或收入/利润/资产负债/现金流中关键模块无法建立                     |
| SOURCE_CONFLICT   | 对核心事实存在未解决的高等级来源冲突                                      |
| VALIDATION_FAILED | 已生成产物但机械校验失败                                            |
| FAILED            | 内部异常或不可恢复错误                                             |

不得把 `PARTIAL_SUCCESS` 或 `DATA_DEGRADED` 写成完整覆盖。

## 7. 建议目录树

```text
src/research_os/
├── documents/
│   ├── __init__.py
│   ├── registry.py
│   ├── parser.py
│   ├── native_text.py
│   ├── tables.py
│   ├── ocr.py
│   ├── corrections.py
│   └── evidence_locator.py
├── financials/
│   ├── __init__.py
│   ├── taxonomy.py
│   ├── import_service.py
│   ├── periods.py
│   ├── normalizer.py
│   ├── reconciler.py
│   ├── formulas.py
│   ├── metrics.py
│   ├── quality.py
│   └── applicability.py
├── valuation/
│   ├── __init__.py
│   ├── market_inputs.py
│   ├── formulas.py
│   ├── applicability.py
│   ├── percentiles.py
│   └── sensitivity.py
├── equity_research/
│   ├── __init__.py
│   ├── config.py
│   ├── request_parser.py
│   ├── capability_checker.py
│   ├── phase3_linker.py
│   ├── morning_linker.py
│   ├── business_segments.py
│   ├── peer_selector.py
│   ├── competition.py
│   ├── catalysts.py
│   ├── risks.py
│   ├── findings.py
│   ├── assembler.py
│   ├── renderer.py
│   ├── validator.py
│   ├── pipeline.py
│   └── status.py
├── llm/
│   └── equity_tasks.py
└── models/
    ├── documents.py
    ├── financials.py
    ├── valuation.py
    └── equity_research.py

schemas/
├── company_profile.schema.json
├── security_profile.schema.json
├── document_record.schema.json
├── document_block.schema.json
├── financial_data_manifest.schema.json
├── financial_report.schema.json
├── financial_fact.schema.json
├── financial_metric.schema.json
├── business_segment.schema.json
├── peer_candidate.schema.json
├── peer_selection.schema.json
├── valuation_snapshot.schema.json
├── forecast_scenario.schema.json
├── competitive_factor.schema.json
├── catalyst.schema.json
├── risk_factor.schema.json
├── research_finding.schema.json
├── equity_research_request.schema.json
├── equity_research_run.schema.json
└── equity_research_result.schema.json

registry/
├── financial_taxonomy.yaml
├── business_taxonomy.yaml
├── equity_peer_universe.yaml
├── valuation_methods.yaml
└── document_parsers.yaml

config/
├── equity_research.yaml
├── financial_quality.yaml
├── valuation.yaml
└── llm_equity.yaml

tests/
├── contracts/
├── unit/
├── integration/
├── golden/equity_research/
└── online/

skills/finance/equity-research/SKILL.md
```

## 8. Schema 设计总则

所有新增 Schema：

* Draft 与现有项目一致（draft-07）；
* `additionalProperties:false`；
* 全部字段进入 `required`；
* nullable 用 `anyOf`；
* 每个对象含 `version`；
* 时间戳使用 ISO-8601；
* 日期使用 `YYYY-MM-DD`；
* 币种使用 ISO 4217；
* 财务数值使用十进制定点字符串，不使用二进制浮点保存原始财务值；
* Pydantic 模型继承 `StrictModel`（extra="forbid"）；
* 构造后 `model_dump()` 必须通过 Schema；
* 外部裸字典缺字段直接拒绝。

现有 `entity.schema.json` 和 `EntityType` 增加 `security`（兼容性枚举扩展，不改变 Schema 数量）。

**新增顶层 Schema：20 个。Phase 4 完成后：30 + 20 = 50 个 Schema。**

### 20 个 Phase 4 Schema 清单

company_profile / security_profile / document_record / document_block /
financial_data_manifest / financial_report / financial_fact / financial_metric /
business_segment / peer_candidate / peer_selection / valuation_snapshot /
forecast_scenario / competitive_factor / catalyst / risk_factor /
research_finding / equity_research_request / equity_research_run /
equity_research_result

（详细字段定义见本任务书附档/实施时按各对象语义确定，字段全部 required、nullable 显式 anyOf、decimal-string 存财务值。）

### 不做顶层 Schema 的对象

| 候选对象                  | 决策                                                     |
| ---------------------- | ------------------------------------------------------ |
| `financial_statement`  | 不做；由 FinancialReport + FinancialFact.statement_type 表示 |
| `segment_metric`       | 不做；嵌入 BusinessSegment 或引用 FinancialFact                |
| `management_statement` | 不做；使用 Opinion、Claim、Evidence                           |
| `corporate_action`     | 不做；复用 Event                                            |
| `industry_membership`  | 不做；嵌入 CompanyProfile 和同行注册表                            |
| `valuation_metric`     | 不做；嵌入 ValuationSnapshot                                |
| `forecast_assumption`  | 不做；嵌入 ForecastScenario                                 |
| `research_question`    | 不做；使用 ResearchFinding.finding_type                     |
| `report_period`        | 不做；作为标准字段组合                                            |
| `equity_research_result` | 做顶层 Schema                                             |
| `financial_data_manifest` | 做顶层 Schema，保证导入批次可审计                                   |

## 9. 数据库迁移

新增 `src/research_os/storage/migrations/005_equity_research.sql`，目标 `PRAGMA user_version = 5`。

新表（20 张）：company_profiles / security_profiles / document_records /
document_blocks / financial_data_manifests / financial_reports /
financial_facts / financial_metrics / business_segments / peer_candidates /
peer_selections / valuation_snapshots / forecast_scenarios /
competitive_factors / catalysts / risk_factors / research_findings /
equity_research_requests / equity_research_runs / equity_research_results。

存储策略：

* 所有表保留 `payload TEXT NOT NULL` 并拆出检索列；
* 财务值检索列使用 `TEXT decimal`，不得仅以 SQLite `REAL` 持久化关键财务值。

主要约束：

* `UNIQUE(financial_data_manifest.file_checksum, data_version)`
* `UNIQUE(financial_report: company_entity_id, period_end, report_type, statement_scope, filing_version)`
* `UNIQUE(financial_fact: fact_key, source_document_id, restatement_version, version)`
* `UNIQUE(peer_candidate: subject_company_id, candidate_company_id, information_cutoff, universe_version)`
* `UNIQUE(peer_selection: request_id, scoring_version, version)`
* `UNIQUE(equity_research_runs: idempotency_key, run_version)`

外键策略：

* 不给 Phase 0—3 旧表增加新外键；
* 新表之间可使用无级联删除的外键；
* 对旧 `entities`、`claims`、`evidence`、`events` 使用应用层引用校验；
* 禁止 `ON DELETE CASCADE` 删除研究历史；
* 引用失效时 Validator 报错，不静默清除。

迁移失败：整个迁移在事务中执行；任一语句失败则回滚；`user_version` 不得增加；
旧表和旧数据不得变化；测试必须覆盖从空库和从 user_version 4 升级两条路径。

## 10. 财务数据标准化规则（要点）

* 内部计算使用 `Decimal`；持久化用十进制字符串。
* 区分 `null`（缺失）/ `"0"`（报告为零）/ 负数（合法原始事实）/ `not_applicable` / `conflict`。
* 单季拆分：Q2=H1−Q1、Q3=Q3_YTD−H1、Q4=FY−Q3_YTD，仅当公司/口径/币种/单位/科目/财年/准则/重述版本全同；拆分值 `value_status=derived_from_report`。
* YoY=(Current−Comparable)/abs(Comparable)；Comparable 为零 → `zero_denominator`；负基数允许但加 `negative_base` 警告。
* QoQ 用单季值，不得用累计值。
* CAGR 仅在 Start>0、End>0、Years>0 时计算。
* TTM：`LatestFY + CurrentYTD − PriorComparableYTD` 或最近四个单季之和；两种方法不得混用，方法写入 `formula_id`；时点项目不计算 TTM。
* 默认合并口径；母公司口径只做补充；不得混用。
* 标准财务金额统一到 `CNY yuan`（仅当原币种为 CNY 直接转换单位）；外币转换必须有汇率来源/日期/类型/公式/Evidence。
* 审计和重述：original / restated / superseded 全保留；当前版本选择按优先级；历史版本不得覆盖或删除。
* 来源优先级 1-6：法定披露原始表格 > 审计报告 > 公司正式公告/IR > 经验证的标准财务接口 > 用户导入且可追溯原始文件 > 媒体或第三方摘要；第 6 级不能单独生成财务 FACT。
* 资产负债恒等容差 `max(config.absolute_tolerance, abs(Assets)*config.relative_tolerance)`，默认相对容差 0.0001。
* 现金流勾稽：EndingCash = BeginningCash + NetIncrease + FXEffect + Other；缺披露项只能输出 `partial_reconciliation`。
* 冲突事实：生成 `conflict_group_id`，保留全部，不选择更符合市场走势的一项。

## 11. 财务指标公式（Commit 6 实现，清单）

收入增长 / 归母净利润增长 / 扣非净利润增长 / 毛利率 / 营业利润率 / 净利率 /
ROE / ROA / ROIC（银行证券保险 N/A，缺核心输入不得伪造）/ 资产负债率 /
有息负债 / 净负债 / 流动比率 / 速动比率 / 应收周转 / 存货周转 / CFO/净利润 /
自由现金流 / 资本开支 / 研发/销售/管理费用率 / 每股收益 / 每股净资产 /
每股经营现金流 / 股本变化。

输出精度：比率内部至少 8 位小数；Schema 持久化保留完整 Decimal；Markdown 默认
2 位百分比或 2—4 位倍数；渲染四舍五入不得回写结构化对象。

## 12. 财务质量与异常检测（Commit 7 实现）

四层阈值：A 会计硬规则 / B 公司历史 robust 统计 / C 同行分位 / D 版本化固定后备阈值（优先级依次下降）。

规则清单（20 条，均只产生事实/告警/研究问题/风险候选，不得自动认定造假或必然风险）：
利润增长但现金流恶化 / 应收快于收入 / 存货快于收入 / 毛利率异常 / 非经常性损益高 /
资产减值 / 商誉集中 / 研发资本化异常 / 关联交易 / 审计意见变化 / 会计政策变化 /
报表重述 / 高分红与高负债 / 融资与分红矛盾 / 在建工程风险 / 产能兑现风险 /
客户集中 / 供应商集中 / 商业承兑应收票据 / 现金受限。

## 13. 业务分部与竞争（Commit 8/10 实现）

分部来源优先级：定期报告分部表 > 产品/地区收入表 > 经营数据公告 > 公司正式说明 > 用户校正。
每期保留 raw_name / canonical_name / mapping_method / reclassification_group_id / valid_from / valid_to。
不得把跨期不同分类直接相加。LLM 可生成标准化候选但不得自动批准低置信映射。

竞争优势证据门槛（10 项之一）；仅管理层自述 → `management_only=true, status=weakly_supported`；
不得写"已形成护城河"。

## 14. 同行选择规则（Commit 9 实现）

候选仅来自：截止日前有效的稳定行业分类 / 版本化同行注册表 / 可验证主营业务关系 /
产业链可比 / 用户显式提供候选（`--peer` 只增加候选，不自动合格）。

评分权重（合计 100）：稳定行业关系 20 / 主营业务相似 20 / 收入结构相似 20 /
产业链关系 10 / 规模 10 / 上市时间 5 / 会计口径可比 7 / 地区 3 / 数据完整度 5。
`dimension_score = raw_score / 5 * weight`。

资格：`total_score>=65`、`core_subtotal>=35`、`relationship_valid_from<=information_cutoff`、
`accounting_comparability_score>=3`、`data_completeness_score>=3`。

样本门槛：`>=5` 完整统计；`3—4` 有限描述不输出正式分位；`<3` `insufficient_peer_sample`。
新上市（不足 2 个完整财年）默认不进入长期同行统计。

防事后选择：候选宇宙版本和权重进入幂等键；估值前冻结；不得按结果删同行；
异常值处理仅用预配置 winsorization；被排除候选和原因必须保留。

## 15. 估值模块（Commit 11 实现）

市值：优先 direct_market_cap，否则 market_cap = price × shares_outstanding（时点一致）。
EV = MarketCap + InterestBearingDebt + PreferredEquity + MinorityInterest
      − EligibleCash − EligibleNonOperatingInvestments（受限现金不得扣除）。

指标：PE_TTM / PB / PS_TTM / EV_EBITDA / FCF_Yield / Dividend_Yield。

不适用情形表（净利润<=0、净资产<=0、EBITDA<=0、FCF<0、银行证券保险、周期企业、
高负债、净现金、非经常性损益高、历史数据不足、同行不足）——均按任务书规则降级。

历史分位：同一公式/同一财务口径/时点对齐；>=36 有效月度样本，>=60 完整，36—59 有限，<36 不足。
同行分位：>=5 完整，3—4 只展示样本值和中位数，<3 不计算。

敏感性允许展示：收入增速/利润率/EBITDA/FCF/估值倍数/市场隐含假设。
禁止输出：每股合理价值/目标股价/上涨空间/买卖区间。DCF/DDM 不实现。

## 16. 催化剂和风险（Commit 13 实现）

每项必须区分：已发生事实 / 已宣布未完成 / 公司指引 / 外部观点 / 模型推断 / 假设 / 未知 / 冲突。
必须字段：类型/描述/时间窗口/影响机制/关联业务/前置条件/失效条件/Evidence/Claim/
置信度/状态/市场是否广泛知晓/Phase 2/3 来源/更新日期。
"市场广泛知晓"缺证据时 `unknown`，不得由模型自信判断。

## 17. LLM 模块（Commit 14 实现）

允许任务：业务描述标准化 / 管理层摘要 / 产品映射候选 / 竞争因素候选 / 催化剂候选 /
风险候选 / 反证整理 / 研究问题 / 章节草稿（均 Flash；复杂跨业务冲突 Pro 条件触发）。

输入要求：仅最小必要摘录 + Evidence ID + 对象 ID + 截止时间 + 输出 Schema +
禁止项 + Prompt 版本；不得传入 API Key/Cookie/Authorization/全文数据库/思维过程要求。

输出路径：raw → JSON 解析 → JSON Schema → Pydantic → model_dump → JSON Schema →
模块业务规则 → 候选对象 → Validator。

失败：未调用 `llm_called=false`；调用失败 `llm_called=true`+`failure_stage`；
确定性回退不得产生 MODEL_INFERENCE；Pro 失败输出人工审核，不循环调用。

Flash/Pro 预算按任务统一管理：

| 深度       | Flash 最大调用 | Pro 最大调用 |
| -------- | ---------: | -------: |
| fast     |          2 |        0 |
| standard |          5 |        1 |
| deep     |          8 |        1 |

Pro 升级条件（至少包含）：独立 S/A 来源对核心事实冲突 / 未解决重大反证>=3 /
跨 3+ 业务分部或 >3 跳产业链 / Flash 连续两次结构校验失败 / 管理层表述与外部原始证据
关键矛盾 / 多个竞争机制候选相互排斥 / 跨财务业务行业复杂冲突说明。
Provider 超时、限流和故障不构成 Pro 业务升级理由。

## 18. 标准流水线（25 阶段）

请求解析 → 对象解析 → 能力检查 → 文档登记 → 文档解析 → 财务导入 → 标准化 →
勾稽验证 → 指标计算 → 财务质量 → 业务分部 → 同行候选 → 同行选择 → 行业竞争 →
估值 → Phase 3 关联 → 晨报事件 → 催化剂/风险 → 冲突与反证 → Findings →
Claim/Evidence → 结果合成 → Markdown → Validator → 持久化。

dry-run：在阶段 3 后完成能力/路径/计划/幂等键/数据缺口预览；不得建库、建 run 目录、
写 manifest、写报告、调用 Provider、修改文档状态。

## 19. 运行产物

`reports/runs/{task_id}/` 下 30 个产物文件（task.json / equity_research_request.json /
entity_resolution.json / capability.json / document_index.json / document_blocks.jsonl /
financial_manifests.json / financial_reports.json / financial_facts.jsonl /
financial_validation.json / financial_metrics.json / financial_quality.json /
business_segments.json / peer_candidates.json / peer_selection.json /
competitive_factors.json / valuation_snapshot.json / forecast_scenarios.json /
phase3_links.json / event_links.json / catalysts.json / risks.json /
contradictions.json / research_findings.json / claims.json / evidence_index.json /
model_route.json / equity_research_result.json / validation.json / final.md / errors.log）。

不存在的可选模块仍需写入明确状态对象，不用空文件或套话掩盖。

## 20. Markdown 研报模板（38 章节）

1 Front Matter / 2 研究对象 / 3 研究范围截止时间与版本 / 4 执行摘要 /
5 核心已知事实 / 6 公司主体信息 / 7 证券信息与股本变化 / 8 业务结构与收入来源 /
9 财务报告覆盖和审计状态 / 10 收入趋势 / 11 利润与利润率 / 12 现金流质量 /
13 资产负债质量 / 14 营运资本与周转 / 15 资本开支在建工程与投资 /
16 研发销售与管理投入 / 17 业务分部 / 18 行业位置与产业链 / 19 竞争格局 /
20 竞争优势劣势与反证 / 21 同行候选和选择说明 / 22 同行财务比较 /
23 估值方法适用性 / 24 历史估值观察 / 25 同行估值观察 / 26 情景与敏感性（可选）/
27 管理层治理和资本配置 / 28 重大项目扩产并购和资产变化 / 29 Phase 3 历史事件和异动关联 /
30 催化剂 / 31 风险 / 32 争议与来源冲突 / 33 数据缺口 / 34 待验证问题 /
35 Claim 与 Evidence 摘要 / 36 模型路由和降级 / 37 方法和公式说明 / 38 免责声明。

必须存在的章节：1—9、12—13、18—25、27—38（无论有无数据）。
缺数据时必须写：覆盖状态/缺失字段/不能得出的结论/降级原因。
禁止空章节套话（"公司未来可期"等）。

## 21. Validator（Commit 16 实现）

输出 pass / pass_with_warnings / fail。规则编号 ERV-001—ERV-079，分组：

* Schema 与引用：ERV-001—008
* 财务数据：ERV-009—027
* 同行与估值：ERV-028—040
* Claim、Evidence 与 LLM：ERV-041—052
* 时间、复用和报告：ERV-053—070
* 统一证据血缘、语义资格与状态契约：ERV-071—079

error 阻止 PASS；warning 可 pass_with_warnings；合法降级须明确状态且无依赖该模块的结论；
数据不足本身不是 error；数据不足却输出确定性结论是 error；SOURCE_CONFLICT 可是合法
研究状态但报告仍需通过结构校验。

## 22. CLI（Commit 17 实现）

正式命令：`research run equity-research`。

参数：--entity（必填，如 600519.SH）/ --date / --as-of / --depth（默认 standard）/
--periods（默认 5，范围 2—10）/ --peer（可重复）/ --scenario（可重复）/
--include-valuation（默认开）/ --include-forecast（默认关）/ --financial-file（可重复）/
--document（可重复）/ --market-file / --force / --dry-run / --live。

参数规则：不允许公司名模糊猜代码；无法唯一映射退出 2；--as-of 不得晚于运行时间；
--date 不自动平移；--periods 不足时降级不静默缩短；--include-forecast 无 Scenario 时
参数错误或明确 disabled；--live 只允许已批准来源；--peer 不能绕过资格规则。

退出码：0 成功/部分成功/合法降级/幂等跳过；2 参数或实体解析错误；3 核心数据不足；
4 Validator 失败；5 内部错误。

幂等键至少包含：scenario / company_entity_id / security_entity_id / as_of / depth /
periods / document hashes / financial manifest versions / market data versions /
peer universe version / peer scoring version / financial taxonomy version /
metric formula version / quality rules version / valuation rules version /
report template version / LLM configured state。

force：生成新 run_version，不覆盖旧报告/旧结构化对象，可复用相同输入 Manifest。

输出目录：`reports/stocks/{ticker}/{YYYY-MM-DD}_equity_research.md`；
强制重跑：`..._equity_research_v{run_version}.md`。

## 23. Hermes Skill（Commit 17 实现）

`skills/finance/equity-research/SKILL.md`。只允许：识别需求/解析代码/识别深度截止时间
是否估值是否情景/构造 CLI/调用流水线/返回报告路径、research_status、财务覆盖、同行状态、
估值状态、模型路由、Validator 状态、数据缺口。禁止自行搜索写研报、自行读 PDF 绕过对象、
复制公式权重阈值、修改 Validator 结果、把 DATA_DEGRADED 改成基本面判断、输出目标价或建议。

## 24. 测试计划（Commit 2—18 分布）

合约（20 Schema 全字段 required/additionalProperties:false/枚举/decimal/nullable/
dump 往返/Schema 总数==50）、迁移（空库 001—005、v4→v5、旧表不变、回滚、幂等）、
财务导入（CSV/JSON/XLSX/缺列/非法数字/空串与零/重复行/混币种/混单位/混口径/dry-run/
rejected 行不写正式事实/checksum）、PDF 文档（哈希/去重/页面/文本块/表格块/扫描页/
OCR unavailable/人工纠错/低置信块）、财务公式手算（每指标正常/零分母/负数/缺失/口径冲突/
金融 N/A/周期警告）、期间（FY/H1/Q1/Q3/单季/TTM/同比/环比/CAGR/重述/闰年）、
同行（完整/5/3—4/<3/截止日后关系/用户 peer 不合格/会计口径不一致/新上市/事后剔除/
registry 版本变化）、估值（PE 亏损/PB 负净资产/PS/EV/EBITDA/净现金/高负债/受限现金/
少数股权缺失/FCF 负/股息率/样本不足/时点不匹配/禁止目标价）、Evidence/Claim（无 Evidence/
无页码/无说话者/无调用/失败/无失效条件/丢一方/UNKNOWN 否定/转载独立性）、
LLM（Fake Provider 全覆盖：无 Provider/成功/修复/Pro 升级/最大一次/故障/预算/篡改拒绝/
目标价拒绝/无思维过程存储）、CLI 集成（参数/实体/完整离线/exit 3/4/5/dry-run 零副作用/
幂等/force/报告产物/无 traceback）、在线测试 `@pytest.mark.online` 默认排除。

## 25. Phase 4 黄金案例（25 类）

高质量成长公司 / 周期性公司 / 亏损成长公司 / 高负债公司 / 净现金公司 / 财务报表重述 /
利润增长现金流恶化 / 应收和存货异常 / 大额商誉 / 重大资产重组 / 高非经常性损益 /
行业同行不足 / 同行事后污染（Validator fail）/ 无真实 Provider / 来源冲突 /
只有管理层自述 / 数据不足 / 估值指标不适用 / Phase 3 异动有解释（原样引用）/
Phase 3 异动无法归因（保持 UNEXPLAINED）/ 禁止目标价和建议（Validator 拒绝）/
扫描 PDF OCR 低置信 / 财务口径混用（fail）/ 金融企业 / 未来信息污染（fail）。

每案例定义：输入 fixture/预期 research_status/预期 warnings/必须出现的 Claim 类型/
禁止结论/数据降级/模型路由/Validator 结果/关键结构化对象；不逐字匹配 Markdown。

## 26. 建议提交序列（18 个 Commit，禁止压缩）

| Commit | 内容 | 依赖 |
| --- | --- | --- |
| 1 | 文档与注册表契约（本 spec/README/sources+data_requirements/taxonomy+peer+valuation+document_parsers registry/config 模板） | 无 |
| 2 | Schema 与 Pydantic（20 Schema/Entity security/模型/Schema 总数 50/合约测试） | 1 |
| 3 | 迁移 005 与财务导入清单（DB 映射/Manifest/CSV+JSON+XLSX/dry-run） | 2 |
| 4 | 文档解析底座（DocumentRecord/Block/原生文本/表格/OCR protocol/纠错/页码引用） | 2 |
| 5 | 财务标准化（taxonomy/期间/单位币种口径/重述冲突） | 3, 4 |
| 6 | 财务指标（formulas/metrics/手算测试） | 5 |
| 7 | 财务质量（勾稽/动态阈值/告警） | 6 |
| 8 | 业务分部（segment/重分类/产品标准化候选） | 4, 5 |
| 9 | 同行选择（peer registry/评分/防事后选择/样本降级） | 8 |
| 10 | 行业与竞争（competitive factors/管理层自述边界/反证） | 8, 9 |
| 11 | 估值（市值/EV/倍数/分位/适用性/禁止目标价测试） | 6, 9 |
| 12 | 情景预测（ForecastScenario/显式假设/默认关闭/无 Provider 降级） | 6, 11 |
| 13 | 催化剂、风险和反证（Phase 2/3 关联） | 10 |
| 14 | LLM 语义模块（复用 LlmClient/任务级预算/Flash/Pro/Fake 测试） | 10, 13 |
| 15 | 研报合成和渲染（Findings/Result/38 章节模板/Front Matter） | 7—14 |
| 16 | Validator（ERV-001—070/error/warning/degradation/禁止项） | 15 |
| 17 | CLI 和 Skill（run equity-research/exit codes/dry-run/force） | 16 |
| 18 | 黄金测试与状态收尾（黄金集/全量回归/README/project-state/changelog） | 17 |

每个提交必须单一职责。

## 27. 验收标准要点

engineering foundation PASS 硬条件：不存在任何工程 BLOCKER、未处置 HIGH；
MEDIUM/LOW 必须列入 KNOWN_LIMITATIONS.md。full research capability 另需满足集中状态规则的
全部最低覆盖，不得以工程测试通过替代。

BLOCKER 级验收项：远端基线未破坏 / Schema 50 且合法 / 模型契约 / 迁移 user_version 5 /
财务导入 / 财务标准化 / 财务指标 / 同行选择 / 估值 / 无目标价 / Phase 3 复用只读 /
Claim/Evidence 可追溯 / LLM 统一 Client / Validator / CLI / 普通测试离线 / 黄金案例。

真实 Provider 可未配置（LOW）、自动财务源可未验证（LOW）、通用 OCR 可仅协议（LOW）、
GitHub Actions 可暂缺（MEDIUM，须保留"本地实测"和"远端 CI"两种证据列）。

## 28. 状态文档更新要求（Commit 18）

CURRENT_STATE.md 拆分记录：

```yaml
remote_head:
code_baseline:
phase4_start_baseline:
phase4_end_code_commit:
documentation_head:
```

并记录 Phase 4 状态 / 50 Schema / user_version 5 / 新 CLI / 数据输入能力 / 报告状态枚举 /
Provider 状态 / 来源状态 / 黄金案例数量 / 实际测试命令 / 实际 passed/failed/skipped /
独立验收结论 / 当前已知限制。测试数量只能来自实际运行，不得沿用 551。

DECISIONS.md 追加 12 条不可违反决策（离线优先混合路径 / 四层分离 / Decimal /
Company 与 Security 分离 / 同行冻结防事后选择 / 估值仅观察无目标价 / 预测默认关闭非 FACT /
Phase 3 只读 / 图谱属 Phase 5 / LLM 不得修改数字或资格 / 金融企业适用性 / 报告由结构化对象生成）。

KNOWN_LIMITATIONS.md / NEXT_PHASE.md / registry/sources.yaml / data_requirements.yaml /
changelog.md / README 按任务书 5.1—5.12 节同步。当前统一状态为 engineering foundation
PASS、full research capability PARTIAL_SUCCESS、Phase 5 BLOCKED；只有全部 Phase 5 准入
条件满足并经正式复验后，才能修改该边界。

## 29. 硬边界（不可违反）

* 无目标价、评级、交易/仓位建议、收益承诺；
* LLM 不得修改财务事实/公式/质量告警/同行资格/估值数值；
* 确定性任务（公式、日期、校验、幂等、哈希）必须用代码，不得交给 LLM；
* 财务公式不可复算 = FAIL；
* FACT 必须有合格 Evidence；
* 未来信息污染 = FAIL；
* 同行事后选择 = FAIL；
* 估值时点不一致 = FAIL；
* dry-run 有副作用 = FAIL；
* Phase 3 结果被改写 = FAIL；
* 普通测试访问网络 = FAIL；
* 旁路模型调用 = FAIL；
* 提前实现 Phase 5 = FAIL（改变阶段边界或自动核心图谱写入 = BLOCKER）。
