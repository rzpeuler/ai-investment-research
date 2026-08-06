# 已知限制（KNOWN_LIMITATIONS）

> 如实记录当前能力边界。每项限制均不得被绕过式实现伪装。

> 当前统一结论（2026-08-07）：Phase 4 engineering foundation = PASS；
> Phase 4 full research capability = PARTIAL_SUCCESS；Phase 5 = BLOCKED。

## 1. 真实 LLM Provider 尚未接入

- 统一 LLM Client（LlmClient/五步校验/Flash 修复/Pro 升级/故障降级）已实现并
  通过 Fake Provider 全链路测试
- 未配置真实 Provider 时 `model_route: {mode: deterministic_fallback, llm_called: false}`
- **影响**：语义环节（原因机制摘要、叙事语义归纳、语义反证提取、方向验证）仍为
  确定性规则近似；「正面新闻股价下跌」「澄清 vs 利好」等语义方向问题无法由
  确定性评分区分（黄金测试已如实标注该局限）

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

- **真实 LLM Provider 仍未配置**：语义模块（业务描述标准化/管理层摘要/竞争因素候选/
  催化剂风险候选等）为确定性回退或未启用；`llm_called=false` 如实记录；
  Flash/Pro 任务级预算与升级条件已实现待真实 Provider 接入后生效
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
- **无 GitHub Actions**：无远端 CI/commit status；验收依赖本地实测证据
- **预测能力边界**：仅确定性外推与显式用户/公司指引假设；model_generated 须真实调用
- 报告必须章节覆盖：行业位置/竞争格局/管理层治理/重大项目等章节依赖人工或语义
  模块补充，缺数据时如实写覆盖状态，不套话
- 四个最低 `EquityLlmTasks` 已进入正式 Pipeline 并共享任务预算，但真实 Provider 未配置；
  Fake Provider 只证明链路和校验可执行，不代表生产语义覆盖
- 市场主要矛盾、业务分析、竞争格局、反证、研究问题和专业评审已有正式结构化产物；
  输入不足时产物必须是 `missing_data` / `insufficient_evidence`，不能据此声称完整 success
- 人工财务 RawItem 已记录 manifest/checksum/locator/source_kind/imported_at/parser_version/
  is_statutory_original，但当前导入仍为 Tier C，不能等同法定披露原件

## 13. Phase 4 数据输入依赖

- 研报需用户提供 `--financial-file`（CSV/JSON/XLSX）；无自动财务源
- 公司画像（CompanyProfile）/证券画像（SecurityProfile）无自动来源，fallback 人工
- 同行比较与历史分位受限于用户导入的同行财务数据
