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
