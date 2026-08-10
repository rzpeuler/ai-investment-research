# 已知限制（KNOWN_LIMITATIONS）

> 如实记录当前能力边界。每项限制均不得被绕过式实现伪装。

> 当前统一结论（2026-08-10）：Phase 4 engineering foundation = PASS；
> Phase 5 = CLOSED / PASS；Phase 6 research workflows = PASS / centrally enabled；
> Graph→Research = read-only Phase 6A path enabled；
> Phase 6 Research→GraphChange Candidate integration = DEFERRED；
> Phase 4 full research capability = PASS（独立验收 SHA `9506f6a`）；
> Phase 5 = CLOSED / PASS。

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
