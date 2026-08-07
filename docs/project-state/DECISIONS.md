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
采用集中、版本化多维覆盖判定，不再仅看可比年度数量。当前结论为：工程基础 PASS、
完整研究能力 PARTIAL_SUCCESS、Phase 5 BLOCKED；真实语义最低覆盖和其余准入条件未
同时满足前不得改变该边界。
