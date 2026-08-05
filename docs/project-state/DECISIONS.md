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
由机械校验器（FORBIDDEN_WORDS）强制拦截，测试锁定，引文正常词语不误伤。

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

## 10. 确定性逻辑必须用代码，不得交给 LLM

时间/哈希/迁移/幂等/Schema 校验/日期计算/窗口/否决/权重/阈值/强制纳入/惩罚
均为确定性代码（工程指南 6.3、任务 14.1）。

## 11. 主备失败必须显式降级

数据需求主源失败后使用备源，再失败使用 fallback（manual_import/manual_inbox）；
全部失败返回 `insufficient_data` + missing_fields + warnings；
备源结果不得伪装成主源；空响应不得解释为"没有事件"（任务 8 节）。
