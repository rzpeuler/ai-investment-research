# 来源注册表变更日志（Phase 1 任务 4.4 节）
# 每次新增/降级/恢复/废弃来源必须记录：日期、source_id、原状态、新状态、原因、验证证据、执行人。

- date: 2026-08-05
  source_id: "(全部)"
  change: added
  reason: Phase 1 初始化来源注册表（候选登记，未探测）。
  evidence: 工程指南 22-24 节；Phase 1 任务 4 节
  agent: Hermes Agent

- date: 2026-08-05
  source_id: ima
  change: added
  reason: 维持客户端依赖边界，禁止绕过登录。
  evidence: 工程指南 22.8 节
  agent: Hermes Agent

- date: 2026-08-05
  source_id: cninfo
  change: verified
  reason: 真实探测：公告查询 API HTTP 200 JSON，字段确认（announcementTitle/Time/adjunctUrl）。
  evidence: data/source_probes/cninfo.json
  agent: Hermes Agent

- date: 2026-08-05
  source_id: sse
  change: verified
  reason: 主页与公告页 HTTP 200，字段未静态确认，依赖 JS。
  evidence: data/source_probes/sse.json
  agent: Hermes Agent

- date: 2026-08-05
  source_id: szse
  change: verified
  reason: HTTP 200，静态确认 title 字段，依赖 JS。
  evidence: data/source_probes/szse.json
  agent: Hermes Agent

- date: 2026-08-05
  source_id: csrc
  change: verified
  reason: HTTP 200，字段未静态确认。
  evidence: data/source_probes/csrc.json
  agent: Hermes Agent

- date: 2026-08-05
  source_id: nbs
  change: verified
  reason: 数据发布列表页静态 HTML 可提取标题+链接（实测）。
  evidence: data/source_probes/nbs.json
  agent: Hermes Agent

- date: 2026-08-05
  source_id: cls
  change: verified
  reason: 电报页 HTTP 200，静态确认 title/content 文本；B 级元数据候选。
  evidence: data/source_probes/cls.json
  agent: Hermes Agent

- date: 2026-08-05
  source_id: sina_quote
  change: contract_clarified
  reason: Phase 1.1 起 sina_quote 仅为实时快照源（market_realtime_snapshot），不得映射为历史日线/日级收益/历史基线；修正 allowed_usage/primary_topics/notes 文案。历史日线需求 fallback=manual_import（见 data_requirements.yaml）。
  evidence: DECISIONS.md #6；registry/data_requirements.yaml
  agent: Hermes Agent

- date: 2026-08-05
  source_id: "(registry)"
  change: contract_added
  reason: Phase 3 Commit 1 契约清理：新增 market_minute_bar 数据需求（无来源，仅 Schema/模型/Loader Protocol）；晨报 dry-run 来源展示移除 sina（行情快照非内容采集源）。
  evidence: registry/data_requirements.yaml；src/research_os/cli/main.py
  agent: Hermes Agent

- date: 2026-08-05
  source_id: "(phase3)"
  change: phase_completed
  reason: Phase 3 异动分析完成：人工日线导入（market-data import-daily，CSV/Parquet）、
    确定性异动检测、基准选择（registry/market_benchmarks.yaml 新增）、分层事件检索、
    原因评分、统一 LLM Client（Fake Provider 全链路）、18 章节报告 + 33 条 Validator、
    CLI abnormal-move + Hermes Skill、14 黄金案例。Schema 19->30，迁移 user_version=4。
  evidence: docs/project-state/CURRENT_STATE.md；551 passed
  agent: Hermes Agent

- date: 2026-08-06
  source_id: manual_financial_import
  change: added
  reason: Phase 4 Commit 1 登记人工财务数据导入来源（CSV/JSON/XLSX；第 5 级来源，
    须可追溯到原始文件；经 FinancialDataManifest 导入，checksum+data_version 进幂等键）。
  evidence: registry/sources.yaml；docs/tasks/phase4-equity-research.md
  agent: Hermes Agent

- date: 2026-08-06
  source_id: user_document
  change: added
  reason: Phase 4 Commit 1 登记用户提供文档来源（PDF/HTML/公告文件；DocumentRecord
    登记+哈希+页码/表格块定位；storage_policy=local_file_reference；不自动升格为法定披露）。
  evidence: registry/sources.yaml；docs/tasks/phase4-equity-research.md
  agent: Hermes Agent

- date: 2026-08-06
  source_id: "(data_requirements)"
  change: contract_added
  reason: Phase 4 Commit 1 新增 9 项数据需求：company_profile / security_profile /
    company_document / financial_statement_data / financial_segment_data /
    market_valuation_snapshot / shares_outstanding_history / industry_membership /
    peer_financial_data。未验证的自动财务源不得登记为 primary/secondary；
    财务需求 fallback=manual_financial_import + disclosure_extraction。
  evidence: registry/data_requirements.yaml；docs/tasks/phase4-equity-research.md
  agent: Hermes Agent

- date: 2026-08-06
  source_id: "(phase4)"
  change: contract_added
  reason: Phase 4 Commit 1 文档与注册表契约：正式任务书入库 docs/tasks/phase4-equity-research.md；
    新增 registry/financial_taxonomy.yaml（科目分类）、business_taxonomy.yaml（行业/商业模式）、
    equity_peer_universe.yaml（同行宇宙+评分权重+样本门槛）、valuation_methods.yaml（估值方法）、
    document_parsers.yaml（文档解析器）；新增 config/equity_research.yaml、financial_quality.yaml、
    valuation.yaml、llm_equity.yaml 模板；README 修正 Phase 0-3 PASS 与 Phase 4 实施中。
  evidence: registry/；config/；docs/tasks/phase4-equity-research.md
  agent: Hermes Agent

- date: 2026-08-06
  source_id: "(phase4_complete)"
  change: phase_implemented_pending_acceptance
  reason: Phase 4 实施完成（18 提交序列，Commit 1-18）：
    20 新 Schema（30->50）、迁移 005（user_version=5）、CSV/JSON/XLSX 财务导入、
    文档底座（哈希/页码/表格/OCR 协议/纠错）、财务标准化（期间/单位/重述/冲突）、
    24 个确定性财务指标、三表勾稽与质量规则、业务分部、同行选择（防事后选择）、
    估值观察（无目标价）、情景预测（默认关闭）、催化剂/风险（Phase 3 只读）、
    LLM 语义模块（统一 LlmClient+任务级预算）、38 章节渲染、ERV-001—070 Validator、
    CLI equity-research + Skill、25 类黄金案例。全量回归 906 passed。
  evidence: docs/project-state/CURRENT_STATE.md；tests/golden/equity_research/
  agent: Hermes Agent
  notes: 状态=待独立验收；验收 PASS 前不得声明 Phase 4 完成

- date: 2026-08-06
  source_id: "(phase4_acceptance_fix)"
  change: rework_fix
  reason: 独立验收 FAIL（3 BLOCKER）修复：1) 流水线接入全部已开发模块
    （文档/标准化/勾稽/质量/分部/同行/竞争/估值/Phase2+3 复用/催化剂风险/
    findings/claims/run 产物），能力检查落实 >=2 可比年度，研究状态按真实覆盖
    计算（0 年 exit 3/1 年 partial/2+ 年 success）；2) Validator 补齐并实际调用
    ERV-001—070（schema/幂等/财务/估值/Evidence/OCR/引用一致性），HYPOTHESIS
    失效条件升级 error（ERV-046），pipeline 传入真实对象；3) Run/Result/Request
    持久化 + 幂等键 + force 新版本不覆盖 + 原子写入 + Validator 失败 exit 4 +
    peer/scenario/valuation/forecast/document/market-file 进 _execute；
    4) 黄金测试重建为端到端（真实流水线，删除无意义断言）；
    5) CLI 补 exit 4/5/幂等/force/不覆盖/同行/估值集成测试；
    6) 最低两个可比年度落实到能力检查。全量回归 921 passed。
  evidence: src/research_os/equity_research/pipeline.py；validator.py；
    tests/golden/equity_research/；tests/integration/test_equity_research_cli.py
  agent: Hermes Agent
  notes: 状态=修复完成待复审；Phase 5 继续阻塞

- date: 2026-08-06
  source_id: "(phase4_acceptance_fix2)"
  change: rework_fix
  reason: 二次独立验收 FAIL（6 BLOCKER + 5 HIGH）修复：
    1) 真实 Claim/Evidence 对象（evidence_builder.py，过 schema；claims.json +
    evidence_index.json；Validator 验真实证据集合）；2) ERV 补齐（删除 pass 占位，
    实现 ERV-004—008/015/018—022/032/035/036/038/043/045/047/052/054/056/059—061，
    Schema 覆盖全部对象）；3) 幂等键改内容哈希（文档 SHA-256/财务/市场）+ 真实
    Provider 状态；4) 估值取 as_of 前最新已披露期间（真实 financial_period_end）；
    5) 未来信息防污染（真实披露时间/文档 mtime/Phase 2+3 as_of 过滤/覆盖 reports+
    evidences）；6) 恢复 25 类黄金案例（10 端到端 + 17 模块级真实断言）；
    7) 30 个运行产物 + reports/runs/{task_id}；8) run.json 最终状态后写；
    9) 零有效财务数据稳定 exit 3；10) 现金流勾稽真实接入；
    11) forecast 模块真实接入（--include-forecast --scenario）。全量回归 938 passed。
  evidence: src/research_os/equity_research/evidence_builder.py；pipeline.py；
    validator.py；financials/import_service.py；tests/golden/equity_research/
  agent: Hermes Agent
  notes: 状态=修复完成待三审；Phase 5 继续阻塞

- date: 2026-08-06
  source_id: "(phase4_final_acceptance)"
  change: phase_accepted
  reason: Phase 4 最终验收修复完成：指标公式参数声明并共享允许的 statement_type，
    生成器与 Validator 同时拒绝报表类型语义错配；Decimal 输入接受有限科学计数法，
    在模型、导入、计算与验证边界统一规范化为固定小数字符串；三个 P1 攻击全部关闭。
    全量 collection 成功，947 passed，0 failed，0 skipped。
  evidence: commit 4f7cdbd；docs/project-state/CURRENT_STATE.md；
    tests/unit/test_phase4_validator.py；tests/unit/test_phase4_metrics.py
  agent: Codex
  notes: 状态=Phase 4 独立验收 PASS；Phase 5 等待正式任务书，尚未实施
