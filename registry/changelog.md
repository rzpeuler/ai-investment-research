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
