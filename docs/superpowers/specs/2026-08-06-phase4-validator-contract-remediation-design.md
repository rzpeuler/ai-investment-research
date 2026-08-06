# Phase 4 Validator 契约修复设计

## 目标与边界

修复候选提交 `4db2935` 独立验收发现的两个剩余问题：财务指标输入的
`statement_type` 可同步篡改，以及科学计数法与普通十进制表示未按 Decimal 语义等价
处理。修复限于 Phase 4 财务指标契约、验证器、测试和状态文档；不改变研究规则，
不增加业务场景，不实施 Phase 5。

## 共享指标参数契约

`MetricParameterSpec` 是指标生成器与 Validator 共用的唯一参数契约。每个参数除名称、
taxonomy、期间角色和必需性外，还声明允许的 `statement_type` 集合。声明允许多个报表
类型，以兼容确实可能来自附注或权益表的科目，但不能使用任意类型。

生成端 `_select_fact` 只选择公司、taxonomy、期间和 `statement_type` 全部符合契约的事实。
验证端 `recompute_from_lineage` 使用同一参数声明验证绑定事实。即使攻击者同时修改
FinancialFact 和 input binding，收入事实被改成现金流量表类型仍会产生 ERV-019 error。
现有公司、报告、scope、期间、币种、单位和重述优先级检查保持不变。

## Decimal 输入与持久化契约

外部输入可使用普通十进制或有限科学计数法；NaN、Infinity 和空值仍拒绝。共享规范化
函数使用 `Decimal` 解析，并转换为无指数的固定小数字符串：去除无意义尾随零，统一
正零和负零。例如 `4E-1`、`0.40` 均规范化为 `0.4`，`-0E+4` 规范化为 `0`。

Pydantic 财务模型、财务导入层、指标计算器和 Validator 共用该规范化语义。JSON Schema
接受有限科学计数法作为输入表示；正式对象经模型构造后以 canonical fixed-point 字符串
流转和持久化。`precision` 仅是展示/显式量化规则的元数据，不作为误差容差。当前公式未
声明量化规则，继续执行精确 Decimal 等值比较；未来若声明量化，rounding mode 必须在
同一公式注册表中由生成端与验证端共用。

## 错误处理与兼容性

- 不符合参数 `statement_type` 契约的 valid 指标返回 ERV-019 error，最终状态 fail。
- 无法解析或非有限 Decimal 返回 Schema/模型错误，不进入计算或持久化。
- 普通小数、科学计数法、尾随零和负零的等价值不报篡改。
- 任意最小有效位变化仍返回 ERV-019 error。
- 不改变 missing、not_applicable、zero_denominator 等既有降级语义。

## 测试与验收

新增测试覆盖：

1. FinancialFact 与 binding 同步把收入从 `income_statement` 改为 `cash_flow`，即使同步
   指标值也必须 fail。
2. 每类公式参数的合法报表类型能正常生成并复算；不合法类型不会被生成器选择。
3. `4E-1`、`0.40`、`-0E+4` 的模型 dump 与持久化值 canonical；NaN/Infinity 拒绝。
4. 毛利率 `+1E-9`、`-1E-9` 和最后有效位篡改均触发 ERV-019。
5. 原 P1-C 六个无标记 Markdown 注入继续全部失败。

完成后从仓库根运行任务书规定的定向测试、collection 和 `python -m pytest -q`。只有三个
P1 全部 CLOSED、0 BLOCKER、0 未处置 HIGH、全量测试通过且工作区 clean，才能把 Phase 4
状态更新为独立验收 PASS。`NEXT_PHASE.md` 只可登记 Phase 5 等待正式任务书，不得开始
Phase 5 实现。

## 提交边界

1. 设计文档提交。
2. 指标参数与 Decimal 契约、实现和测试提交。
3. 独立复验通过后的状态文档提交。
