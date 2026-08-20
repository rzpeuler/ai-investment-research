# 已知限制（KNOWN_LIMITATIONS）

> 如实记录当前能力边界。每项限制均不得被绕过式实现伪装。

> 当前统一结论（2026-08-16）：Phase 4 engineering foundation = PASS；
> Phase 5 = CLOSED / PASS；Phase 6 research workflows = PASS / centrally enabled；
> Graph→Research = read-only Phase 6A path enabled；
> Phase 6 Research→GraphChange Candidate integration = DEFERRED；
> Phase 4 full research capability = PASS（独立验收 SHA `9506f6a`）；
> P7-UX1 = PASS / INDEPENDENTLY ACCEPTED（governance closeout，
> Decision #46.7；仅覆盖本地 Chat UX / control-plane adapter）；
> P7-D0 = PASS / INDEPENDENTLY ACCEPTED（Decision #47.8/#47.9，
> governance closeout 2026-08-11；统一数据层契约与 Brief A/C 冻结）；
> P7-D1 = PASS / INDEPENDENTLY ACCEPTED（Decision #48.10/#48.11，accepted
> implementation head `bc27781`；数据就绪控制面）；
> P7-D2 = PASS / INDEPENDENTLY ACCEPTED（2026-08-18，Decision #50；accepted head
> `55c4ba5`；最终 implementation head `84f70b5`；真实采集覆盖 NONE）。

Phase 6 PASS 不代表所有外部数据源均已完备，也不保证每次真实运行成功。结果仍受数据与
Evidence 可得性约束，可合法返回 `partial_success`、`degraded` 或
`insufficient_evidence`。KnowledgeContext != Evidence；图谱 FACT 仍须回源权威 Evidence
并通过 eligibility / as_of / source validation。Phase 5 已具备 GraphChange Candidate / Review /
Apply 能力，但 Phase 6 场景输出尚未中央接入该候选链路。

## 1. 真实 LLM Provider 已接入但存在外部稳定性风险

- DeepSeek Chat Completions 已通过真实 probe 与两个成功案例；业务仍统一经过 LlmClient
- 未配置真实 Provider 时 `model_route: {mode: deterministic_fallback, llm_called: false}`
- 在线验收观察到间歇性超时；每次失败均计入 Flash 预算，预算耗尽后合法降级
- **影响**：单次真实运行仍可能因外部超时成为 `degraded`，历史 SUCCESS 不得复用为新结果

## 2. 事件相似聚类（晨报）仍为确定性第一版

- 实现 = 实体+日期预分桶 + 标题相似度（SequenceMatcher）+ 确定性规则
- 无向量相似度、无 LLM 语义判断

## 3. 预期差评分仍是规则近似（晨报）

- 依据关键词与保守默认值，非真实市场共识建模

## 4. 隔夜市场结构化行情缺失

- 无经过验证的全球市场历史数据源；晨报"隔夜外围总结"固定降级文案

## 5. 历史日线只能人工导入（Phase 3 延续）

- `market_daily_ohlcv` 无自动来源（primary/secondary 为空）
- fallback=manual_import；`research market-data import-daily` 支持 CSV（Parquet
  需 pandas+pyarrow）；未验证的自动历史行情接口不得写入 primary/secondary
- **影响**：异动分析前需先导入日线；行业/概念分析需至少 2 只成分股（--peer）

## 6. 深度媒体、社区、机构动向主要依赖人工 Inbox

- deep_financial_media / community_sentiment / institutional_activity
  三个方向状态为 manual_only 或 not_covered
- 社区平台绕登录采集被明确禁止；IMA 为 client_only

## 7. 分钟级行情仅完成 Schema/模型/Loader Protocol

- `market_minute_bar` 无来源（primary/secondary/fallback 全空）
- CLI `--granularity minute` 明确拒绝（无数据源），不创建虚构分钟源

## 8. 行业/概念异动用成分股聚合合成序列

- 板块收益 = 成分股等权均值（aggregate_peer_bars），为合成代理数据
- 成分不足 2 只时返回数据不足（exit 3），不得宣称板块共振（样本门槛 行业10/概念8）

## 9. 原因评分覆盖度为确定性近似

- explanation_coverage_score 基于方向词+量价信息的近似规则（任务书 11.2 语义
  标准留 LLM 层）；模型不改最终分，可提供评分理由草案

## 10. 环境与部署限制

- Windows 中文路径 + GBK locale：必须普通 pip 安装（非 editable），代码变更后需重装
- hatch 打包遵循 .gitignore：忽略规则须根锚定（如 `/reports/`）
- pytest 9 不再应用 pyproject 的 `pythonpath` ini：tests/conftest.py 显式注入 src/
  （否则测试会静默跑 site-packages 安装版）
- 默认测试完全离线（FakeLlmProvider / fixture）；在线验证需显式 --live /
  probe-sources，不进入普通 CI

## 11. 异动分析自动化程度

- 无全市场自动扫描、无分钟级实盘扫描（明确非目标）
- 事件检索依赖 DB/晨报产物中已有的结构化数据；外部事件源实时采集不在 Phase 3

## 12. 个股研报自动化程度（Phase 4 延续，任务书 5.3）

- **真实 LLM Provider 已配置**：七项必需语义任务在两个真实案例中全部通过；未显式
  `--live`、凭证缺失或 Provider 故障时仍如实回退，不生成伪造 `MODEL_INFERENCE`
- **自动财务源未验证**：financial_statement_data 无 primary/secondary，
  仅 `manual_financial_import` + `disclosure_extraction`；未验证接口不得登记
- **历史行情仍仅人工导入**：日线 fallback=manual_import；市值/股本历史序列无自动来源
- **PDF 表格解析覆盖有限**：原生文本/CSV 表格可解析；通用 PDF 表格识别为协议层
  （native_text/table_parser 部分支持）；完整年报表格依赖人工校正
- **OCR 状态**：仅协议层（返回空列表，不虚构块）；低置信 OCR 不进入有效 FACT；
  无通用 OCR 平台
- **金融企业专用指标覆盖**：仅通用适用性降级（EV/EBITDA、流动比率等 N/A）；
  银行资本充足率、NIM 等专用指标未实现
- **深度媒体和机构信息覆盖**：仍 manual_only / not_covered（同 Phase 2/3）
- **同行注册表覆盖**：registry/equity_peer_universe.yaml 为骨架（scoring 权重与
  门槛已定义）；具体公司关系数据按公司登记时填充
- **Offline CI 已上线**（`.github/workflows/offline-ci.yml`）：GitHub-hosted Ubuntu、Python 3.12；
  trigger: PR / push to master / workflow_dispatch；permissions: contents: read；
  不配置 DeepSeek API Key / 项目 secrets；5 个 online tests 默认 skip；
  1133 passed / 5 skipped / 51/51 schemas / compileall PASS
  （baseline run 31154022296，SHA `ea026f1`）；
  在线能力仍依赖显式 live acceptance，不得由 Offline CI PASS 替代
- **预测能力边界**：仅确定性外推与显式用户/公司指引假设；model_generated 须真实调用
- 报告必须章节覆盖：行业位置/竞争格局/管理层治理/重大项目等章节依赖人工或语义
  模块补充，缺数据时如实写覆盖状态，不套话
- 七个必需 `EquityLlmTasks` 已进入正式 Pipeline 并共享任务预算；Fake Provider 仍只用于
  默认离线回归，不代表生产语义覆盖
- 市场主要矛盾、业务分析、竞争格局、反证、研究问题和专业评审已有正式结构化产物；
  输入不足时产物必须是 `missing_data` / `insufficient_evidence`，不能据此声称完整 success
- 普通人工财务仍为 Tier C；另有已验证的巨潮官方原件辅助导入和人工复核 locator 路径，
  只有通过 Document/checksum/数值/时间/实体校验的事实才能取得官方 Evidence
- 来源质量已按核心财务、业务竞争、事件和整体质量分域；因此当前 Tier C 财务输入会明确
  阻止完整 `success`，即使任务同时存在无关的 S/A 事件 Evidence

## 13. Phase 4 数据输入依赖

- 研报需用户提供 `--financial-file`（CSV/JSON/XLSX）；无自动财务源
- 公司画像（CompanyProfile）/证券画像（SecurityProfile）无自动来源，fallback 人工
- 同行比较与历史分位受限于用户导入的同行财务数据

## 14. Git 与远端 CI

- 旧的跨阶段大提交已在 PR #1 通过 Squash merge 治理；当前 Phase 4.1 使用独立、单一职责
  提交序列，不改写既有历史。
- **Offline CI 已上线**：`github.com/rzpeuler/ai-investment-research/actions`；
  workflow 位于 `.github/workflows/offline-ci.yml`；trigger: PR / push to master / workflow_dispatch；
  permissions: contents: read；secrets: 不配置 DeepSeek API Key / 项目 secrets；
  5 个 online tests 默认 skip；baseline run 31154022296（SHA `ea026f1`）：
  1133 passed / 5 skipped / 51/51 schemas / compileall PASS。
- Offline CI 限制：不验证 DeepSeek live provider / 真实 CNINFO / 外部服务；
  branch 普通 push 不触发，PR 会触发；GHA Node.js 20 deprecation warning 为 non-blocking
  （runner 强制使用 Node 24）；在线能力仍靠显式 live acceptance，不得由 Offline CI PASS 替代。

## 15. P7-UX1 会话网关首版限制（terminal 状态，不覆盖历史快照）

- 网关是 local / loopback-only 的个人入口，只监听 `127.0.0.1`；不是远程服务或多租户
  SaaS。浏览器不得直接访问 DeepSeek。
- session 仅在进程内存保存，最多 20 轮、最多 128 sessions；服务退出后会话消失，
  不持久化到 SQLite，也没有 conversation/chat 数据表。
- 实体解析只允许安全归一化后的唯一精确匹配；不做 fuzzy matching、编辑距离选择、
  LLM ticker 记忆、联网补全或根据六位代码首位猜交易所。未知或歧义输入会要求澄清。
- 行业解析只使用 accepted ontology / 权威图谱状态或首次覆盖允许的唯一 profile industry；
  多命中、零命中或冲突会澄清。
- DeepSeek 未配置或 LLM gate 关闭时，只支持完整 symbol、唯一精确名称，以及 AUTO 下
  “今天晨报/今天晚报”等有限确定性回退；复杂自然语言不会伪装为已调用 LLM。
- Chat 只帮助构造请求，不执行 report 完成后的第二轮 LLM QA、事实核查或报告改写；
  报告质量仍由既有 Runner / Pipeline / Validator 与 Evidence availability 决定。
- 两个开关相互独立：LLM gate 仅控制自然语言理解，Research Live gate 仅控制正式研究
  live 能力。关闭其中一个不会隐式改变另一个。
- P7-UX1 没有扩展数据源、Collector、Source Registry、研究 Pipeline 或 Graph write。
  当前 Schema registry 为 80；DB 仍为 v6；migrations 为 NONE。
- P7 DATA ACQUISITION = NOT_STARTED / AWAITING_ARCHITECTURE_DISCUSSION；Phase 6.1 =
  NOT_AUTHORIZED；Phase 6 Research→GraphChange Candidate integration 继续 DEFERRED。
- P7-UX1 已完成独立验收（PASS / INDEPENDENTLY ACCEPTED，2026-08-10 governance
  closeout）。该 terminal 状态只覆盖本地 Chat UX / control-plane adapter，不代表
  Phase 7 数据采集或 Phase 6.1 授权。

## 16. P7-D0 统一数据层契约限制（PASS / INDEPENDENTLY ACCEPTED）

- P7-D0 只冻结契约与 Registry，不实现任何采集：无新 Collector、无 Source expansion、
  无 Router v2、无 DataReadinessService DB 查询、无 GapClassifier、无 AcquisitionExecutor、
  无 Heat Ranking 算法。当前 Schema registry 为 85；DB 仍 v6；migrations 为 NONE。
- `registry/scenario_data_requirements.yaml` 中登记的数据需求只表达业务需要，不代表
  自动覆盖已经存在。`brief_event_content` 与 `brief_attention_content` 的
  primary/secondary 为空，仅声明需求存在；`market_daily_ohlcv`、`company_profile`、
  `financial_statement_data`、`peer_financial_data` 等仍无自动来源，如实体现
  MISSING / MANUAL_REQUIRED / NOT_ACQUIRABLE。
- Brief C（`brief_attention_content`）是单次报告窗口快照，不是持续监控；没有采集成功
  不得解释成“没有市场关注”。watchlist 名单只迁移需求文档 / 工程指南 / 现有 registry
  已明确的名称，不按模型记忆补充；所有条目显式 `content_scope`（财联社 =
  non_fast_news_only，7×24 快讯由 A 处理）；未真实验证的条目
  `last_verified_at: null`，不伪造联网验证时间。
- heat_score 仅表示本次窗口本次样本内相对关注程度，不是历史变化、不是事实可信度、
  不是投资价值、不是机构交易行为；Heat 算法未实现，留给后续 Brief Acquisition milestone。
- P7-D0 为纯离线契约任务，未进行任何联网验收；其 terminal boundary 当时未授权
  P7-D1，后续 P7-D1 已经独立授权、实施并验收。

## 17. P7-D1 数据就绪控制面限制（PASS / INDEPENDENTLY ACCEPTED）

- P7-D1 只实现控制面（readiness / gap / planning），不执行 Acquisition：
  无 AcquisitionExecutor、无 acquisition 后 Readiness Recheck、Router 仍只返回
  DataRoute（无 unified routed items result）。
- 无新 Collector、无 Source expansion、无自动历史日线源、无自动财务源；
  brief_event_content / brief_attention_content 自动覆盖不完整；无 Heat Ranking；
  无持续 attention monitoring；无 Graph write。
- `registry/data_acquisition_capabilities.yaml` 中没有任何 data_type 达到
  BUSINESS_SUFFICIENT（保守规则），因此 GapClassifier 不会输出 AUTO_ACQUIRABLE /
  STALE_REFRESHABLE；真实采集执行属于 P7-D2。
- coverage_ratio 对 open-world requirement 为 null（COVERAGE_NOT_MEASURABLE），
  不得发明百分比。
- dry-run 零副作用（不创建 DB / 不写 artifacts）；Preflight 只读、零 LLM、
  零网络。
- P7-D1 收口时只授权 P7-D2 taskbook drafting + architecture design；后续 Foundation
  implementation 已获单独授权并实现，但任何具体外部数据源、real-source execution 与
  Collector 仍未授权；Phase6.1 未授权。
- R3.1（Final Runtime Closure）进一步收口但仍有边界：industry/global
  entity_mapping 与 open-world requirement 的 coverage 恒为 null（无完整权威
  denominator）；run_artifacts coverage 仅对 requested run set 计算；market
  bar 的 tier 依赖 accepted manifest（无 manifest → SOURCE_TIER_UNPROVEN）；
  无自动历史日线/财务源；projection 仅支持已登记的 9 个策略（新增需先登记）。

## 18. P7-D2 Acquisition Execution Foundation 限制（PASS / INDEPENDENTLY ACCEPTED 2026-08-18）

- `P7-D2: PASS / INDEPENDENTLY ACCEPTED`（Decision #50，accepted head `55c4ba5`）；
  `REAL DATA ACQUISITION COVERAGE: NONE`。独立验收只证明 Fake-proven Foundation 正确，
  不证明任何真实来源可用。
- 当前实现只由 Fake 证明。Production policy 仍 `enabled: false`；Production collector IDs: []；
  Real source execution: 0；Capability BUSINESS_SUFFICIENT promotions: 0；New collectors: 0；
  Source expansion: 0。
- 未调用生产 LLM/provider：LLM/provider calls: 0；无 Graph 写入：Graph writes: 0。
- DB: v6；Migrations: 6 / NONE added；Schemas: 86。未新增迁移。
- 没有任何真实 capability 达到 BUSINESS_SUFFICIENT，因此 production acquisition 继续 fail closed；
  不得把 Fake 成功、已有 Collector 代码或 foundation wiring 解释为真实数据覆盖。
- 独立验收 PASS 不提升任何具体来源状态；之后任何具体来源仍须独立 source governance、
  真实验证和显式授权（P7-D3）。
- Offline CI run `31945487755` 已在 Ubuntu / Python 3.12.13 成功（3567 passed /
  6 skipped / 0 failed / 1 warning，417.14s；86/86 schemas；compile success），但离线
  Fake 证明不能替代真实来源验证。前一 run `31943822195` 仅暴露 fresh-process
  source-path portability，已由 `831afe4` 修复。

## 19. P7-D3 Free-Source Production MVP 限制（PASS / INDEPENDENTLY ACCEPTED 2026-08-18，Decision #52）

- `P7-D3: PASS / INDEPENDENTLY ACCEPTED`（accepted head `e8a4a9f`，已合并进 master）。
  nbs/cninfo 真实在线验收通过（NBS inserted=7/幂等 reuse=7；CNINFO 沪市 inserted=6/幂等
  reuse=6、深市验收窗口 6 条真实公告）；验收 PASS 不自动授权 capability 晋级或来源扩展。
- 默认真实采集关闭（enabled: false）；production allowlist 恰好 [nbs, cninfo]（未批准 ID
  fail closed）；只有显式 `--live-data` 才注入真实采集，与 `--live`/LLM 分离。
- capability：macro_data / company_announcement = WORKFLOW_WIRED；BUSINESS_SUFFICIENT
  仅在独立在线验收通过后由治理 closeout 单独晋级（NBS 与 CNINFO 分开，不得打包）。
- CNINFO subject scope（earnings_expectation）readiness 关联需要 RawItem 携带 subject
  entity，当前 RawItem 未携带（不修改 RawItem Schema），readiness 保持 MISSING/PARTIAL
  为合法状态；subject 关联属后续阶段。
- CNINFO 深市近 5 日窗口真实无公告时 execution 链 EMPTY（合法，禁止解释为“无公告”）；
  真实数据证明使用验收窗口。
- 仍不具备：自动完整财务报表、自动历史日线、分钟/完整实时行情、行业成分完整覆盖、
  同行财务自动覆盖、机构研报自动采集、深度新闻/社区数据、通用 PDF 表格解析、OCR、
  付费数据接入治理、Graph write、Phase 6.1。

## 20. Agent Runtime / Frontend 顶层架构治理冻结限制（2026-08-18，DESIGN FROZEN / NOT IMPLEMENTED）

GOV-ARUX1 治理冻结（Decision #54 / #55）如实记录当前能力边界，不得声称未来能力已实现：

1. 当前会话仍是 P7-UX1 IN_MEMORY_ONLY（最多 20 轮 / 128 sessions，服务退出即消失）。
2. DeepSeek Harness P8-A0 技术集成与 P8-B 设计均已独立验收；P8-B 设计已独立验收，P8-B1 foundation implementation 已授权，生产采用仍未授权。
   上游为 Developer Preview，runtime 固定为 `@deepseek-ai/dsh@0.1.0-rc.7`，升级需重新验收。

## P8-B 当前限制

- P8-B 设计与 P8-B1 foundation 均已独立验收；P8-B2 internal trial 已实现但为 PARTIAL / NOT ACCEPTED，生产采用仍未授权。
  P8-B2-R2 已完成 acceptance evidence-integrity 修复（失败单次计数、进程残留 fail-closed、secret 证据单调、
  证据来源标注），但官方 post-fix live trial 因隔离 worktree 无 Harness 二进制、approved 环境机制未暴露
  provider credential 而保持 PARTIAL（`HARNESS_BOOT_FAILED`，未执行 provider-backed turn）。
- P8-B2-ENV-01 环境就绪探针（2026-08-20）已关闭上述环境阻断：隔离 worktree 内 `npm ci`（committed
  package-lock.json）可确定性安装 pinned `@deepseek-ai/dsh@0.1.0-rc.7` 并可真实启动；approved 凭证存在且
  一次 bounded provider-backed connectivity probe 成功（flash，191 tokens，`ENVIRONMENT_READINESS_PROBE_ONLY`）。
  MCP（`research-os-mcp/v1`，恰好 2 个授权工具）、runtime/profile、secret hygiene 均 VERIFIED。
- **当前宿主（Windows）正式 trial 就绪性 = FAIL（fail-closed）**：accepted R2 清理证据模型在 Windows 无法枚举
  owned process tree（`cleanup_status` = root TERMINATED / tree NOT_VERIFIED），因此 formal trial 的
  `process residue = NO` gate 无法在本宿主机械证明；`FORMAL_TRIAL_READY = NO`。同一机制在 POSIX 由 accepted
  Linux process-group 回归测试（GitHub Offline CI on Ubuntu）证明 VERIFIED。P8-B2-ENV-01 的 READY 判定需
  Sol 独立验收；正式 10-session / 20-turn corpus 未执行。
- **Formal provider-backed trial boundary under preparation**：正式 trial 的执行边界
  （execution environment / credential boundary / evidence model / failure / cost / acceptance workflow）
  由 `docs/tasks/p8-b2-live-00-trial-boundary-design.md` 定义，待 Sol 独立验收；在边界获批前
  （P8-B2-LIVE-01 之前）不执行任何 formal corpus（`FORMAL_CORPUS_EXECUTED = NO`）。
- **P8-B2-LIVE-01 正式 trial 执行 = PARTIAL（2026-08-20，RESUME-02）**：approved credential
  boundary（GitHub Actions `DEEPSEEK_API_KEY` secret）已配置；trial 在 GitHub Actions
  ubuntu-latest 上执行，readiness probe 全 gate READY（含 provider connectivity）。
  首次 provider-backed turn 失败（`PROVIDER_TIMEOUT`，typed、单次计数、无重试）；
  随后 Harness 进程不再 READY（`HARNESS_BOOT_FAILED`）→ latch 触发 → fail-closed 停止。
  结果：completed sessions 0/10、turns 0/20（1 次 attempted）；process cleanup VERIFIED
  （residue NO）；secret_scan PASS；drills PASS；evidence snapshot 已生成。
- **REPAIR-01 根因（已定位并修复，2026-08-20）**：PARTIAL 的根因不是 provider 延迟 —
  我方 stdio MCP server 回复 `protocolVersion "1"`，被 pinned Harness 的 MCP SDK
  （`@deepseek-ai/dsh-mcp-client`）拒绝（"Server's protocol version is not supported:
  1"）→ `failOnStartupError` → dsh 进程崩溃（exit 1）→ turn 失败（被映射为
  `PROVIDER_TIMEOUT`）→ supervisor FAILED → `HARNESS_BOOT_FAILED`。最小修复已实施：
  `negotiate_mcp_protocol_version`（contracts.py）+ stdio server 使用；namespace /
  tools / failure semantics / budgets 不变。修复后有界单 turn 诊断（真实 provider，
  非 corpus）：`TURN_COMPLETED 22.7s`、进程存活、supervisor READY。正式
  10-session / 20-turn corpus 尚未重新执行，P8-B2 仍需 Sol 独立验收。
- 默认 runtime 仍为 P7-UX1 legacy/fallback；Harness 未被设为生产默认。
- Frontend contract 仅为设计，未实现任何 Harness UI/API。
- Persistent production topology、正式 credential store、load/cost evidence 与 rollout
  acceptance 尚未形成；这些属于 P8-B1 或后续独立 taskbook。
3. Persistent Agent Conversation 尚不可用。
4. Skill Registry 尚未进入本项目 production。
5. Research OS MCP Server 尚未实现。
6. Capability Guide 尚未实现。
7. 数据中心目前没有完整前端 product surface。
8. Source editing API 尚未实现。
9. Source registration / capability lifecycle 不能由前端修改。
10. Test connection 尚不构成 business sufficiency。
11. Agent model profile / 套餐 UI 尚未实现。
12. Harness 为 developer-preview upstream，正式采用前有 compatibility risk。
13. Frontend 不得宣称 D4/D5/realtime 等尚未验收能力已自动可用。
- **P8-B2-LIVE-01-RESUME-03（2026-08-21）**：REPAIR-01 修复后正式 corpus **已完整执行**
  （10/10 sessions、20/20 provider-backed turns、0 failures、secret scan PASS、
  process cleanup VERIFIED、drills PASS、latency p50 6.2s），但 STATUS 仍为 PARTIAL —
  唯一未过的 PASS gate 是 `provider_tokens > 0`：accepted runtime 以 dsh 特有键名
  （`projections.values.tokenUsage`：uncachedInputTokens / outputTokens /
  cacheReadTokens / cacheWriteTokens）报告 usage，`_extract_usage` 未映射 →
  `total_tokens = NOT_REPORTED`（LIVE-00 禁止推断，如实记录）。该 usage 提取映射缺口
  与 REPAIR-01 同类，需 REPAIR-02 taskbook 最小修复（映射 provider-reported 字段 +
  离线测试）后重新执行正式 trial；P8-B2 仍需 Sol 独立验收。
- **P8-B2-LIVE-01-REPAIR-02（2026-08-21）**：usage evidence 提取映射已修复 —
  `_extract_usage` 现可识别 dsh rc.7 tokenUsage 字段（uncachedInputTokens /
  outputTokens / cacheReadTokens / cacheWriteTokens）并确定性映射为
  input/output/cached/cache_read/cache_write/total_tokens（仅 provider-reported
  值，无推断）；9 个离线回归测试；真实运行时验证 total_tokens=23788 > 0。
  治理发现：实测每 turn 用量 ~24-44k tokens，20 turns ≈ 480-880k，**超过冻结的
  max_provider_tokens=200,000** — 该 budget 属冻结 cost control（未修改），
  需 Sol 在正式 corpus 重新执行前作出治理决定；否则下一次 trial 将如实报告
  budget exhaustion（约第 5-9 turn）。P8-B2 仍需 Sol 独立验收。
