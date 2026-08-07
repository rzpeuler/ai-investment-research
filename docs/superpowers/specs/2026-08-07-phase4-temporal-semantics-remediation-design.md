# Phase 4 时间语义与 CNINFO 默认窗口定向修复设计

## 目标与边界

本轮只修复 Phase 4.1 验收暴露的时间语义错误，以及 CNINFO 生产 Adapter 的固定年份默认查询问题。不改变研究方法、模型路由、报告结构或业务场景，也不把当前分支标记为 PASS；修复和重新验收完成后再更新工程状态。

## 时间语义

研究截止时间和人工复核时间属于两个独立时间轴：

- `Evidence.published_at`、`Document.published_at`、`Finding.as_of` 和市场数据时间不得晚于研究任务的 `as_of`。
- `as_of` 不得晚于 `requested_at` 超过 5 秒。5 秒仅用于吸收跨进程或外部请求中的微小时钟误差，不能容纳数小时的未来截止时间。
- `confirmed_at` 表示人工实际核验 locator 的时间，可以晚于历史 `as_of`，但不得晚于任务的 `requested_at`。

`EquityResearchRequest` 在契约层执行 `as_of <= requested_at + 5 seconds` 的跨字段校验，使 CLI、Orchestrator、Pipeline 和直接模型构造共享同一规则。财务证据绑定层以 `requested_at` 作为确认时间上界，取消原有 `confirmed_at <= as_of` 约束。最终 Validator 重复检查确认时间上界，防止中间产物或持久化数据被篡改后绕过绑定阶段。

所有时间比较按带时区的时间点进行，不使用字符串字典序比较。缺少或无效时区继续由现有 ISO 时间契约拒绝。

## Phase 4.1 验收时间

验收配置的研究截止时间固定为真实历史截止点：

`2026-08-07T00:00:00+08:00`

每个验收案例开始准备时捕获一次 `acceptance_started_at = now_iso()`。该案例生成的全部核心财务 locator 共用这一真实确认时间，不再把 `confirmed_at` 伪造为 `as_of`。验收准备发生在研究请求创建之前，因此 `acceptance_started_at <= requested_at`；若该顺序被破坏，绑定层和 Validator 必须失败。

已有发布时点检查保持不变：即使人工确认发生在 `as_of` 之后，晚于 `as_of` 才发布的 Document 或 Evidence 仍不能进入研究材料。

## CNINFO 默认查询窗口

未显式传入 `start/end` 时，`CninfoCollector.discover()` 使用上海时区当天作为结束日，向前覆盖最近 5 个自然日，并生成动态 `se_date`。生产代码不得包含固定年份。

显式传入 `start/end` 时，继续严格使用调用方给出的历史窗口，不被默认窗口覆盖。日期计算由确定性代码完成，不交给模型。

## 失败行为

- `as_of > requested_at + 5 seconds`：请求参数失败，不启动后续采集或模型调用。
- `confirmed_at > requested_at`：财务证据绑定失败；被篡改的最终产物由 Validator 再次判定失败。
- Document、Evidence、Finding 或市场数据时间晚于 `as_of`：沿用现有未来信息校验并失败。
- 合法的历史 `as_of` 加稍后的真实 `confirmed_at`：通过时间校验。

## 测试与验收

定向测试至少覆盖：

1. 历史 `as_of` 与稍后的 `confirmed_at` 可以通过。
2. `confirmed_at > requested_at` 在绑定层和最终 Validator 失败。
3. `as_of` 超出 `requested_at` 5 秒以上失败，边界内通过。
4. Document 或 Evidence 的 `published_at > as_of` 继续失败。
5. CNINFO 默认窗口随上海日期动态变化，不含固定年份。
6. CNINFO 显式历史窗口保持原值。

实现后先运行相关单元和验收测试，再运行 `python -m pytest` 全量测试。若真实端到端验收需要重新生成产物，必须使用修正后的历史 `as_of` 与真实 `acceptance_started_at`，不得沿用此前时间语义不合法的产物作为 PASS 证据。

## 提交边界

1. 本设计文档独立提交。
2. 时间契约、验收生成、CNINFO 默认窗口及攻击性测试作为一个定向实现提交。
3. 重新验收通过后，状态文档作为独立提交更新，并推送至现有 PR #3。
