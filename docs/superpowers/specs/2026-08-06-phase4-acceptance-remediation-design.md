# Phase 4 验收修复设计

## 目标与范围

在 `65404ca` 基线上修复 Phase 4 验收任务书列出的 4 个 BLOCKER、6 个 HIGH
及其明确关联检查项。修复仅限个股研报（Phase 4）；不实施 Phase 5，不调整研究
输出边界，也不放宽 Schema、Validator 或测试断言。

## 架构与数据流

### Commit A：执行链路与时间语义

1. Forecast 流水线构造与 `forecast.py` 数据类完全一致的输入；确定性预测的结果写入
   `ForecastScenario.outputs`。对象在持久化、渲染和验证前依次通过 Pydantic dump 与
   `forecast_scenario` JSON Schema。
2. 文档披露时间只按以下顺序获取：显式可信输入、解析器验证后的字段、已登记来源对象、
   unknown。文件 mtime 不得作为 `published_at` 或 as-of 判断的依据。
3. 可比年度仅统计 as-of 前已披露的完整 FY/annual 报告；年度不同，且 scope、币种与
   会计口径相同或被显式标记为可比。
4. 导入层将零 accepted facts（包括仅表头、全行拒绝和多文件全拒绝）显式传递为核心数据
   不足，命令返回 exit 3。运行对象在所有终态字段和产物列表齐备后原子写入，磁盘 JSON
   与数据库 payload 使用同一完整 dump。
5. 同行评分和资格判断抽取为一个共享确定性函数；用户 peer 只补充候选，仍经全部资格
   规则和截止日检查。

### Commit B：确定性验证与渲染一致性

1. 新建指标重算注册表，逐项声明 metric code、公式函数、命名参数、所需 taxonomy、
   参数顺序、单位/精度、零分母与 N/A 规则、formula ID/version。验证器从血缘事实按
   命名参数重建输入，绝不以 UUID 顺序猜测参数。
2. Renderer 为每个展示指标生成稳定的对象标记，并集中定义格式化规则。Validator 解析
   相同标记并以同一格式规则检测篡改、精度、单位、章节错配和重复展示冲突。
3. Validator 主入口接收并验证所有正式 Phase 4 对象；Forecast 假设必须非 FACT，须有
   来源与失效条件，输出须带公式版本。
4. 先添加可失败的端到端、单元、CLI 和 25 类黄金案例测试，再实施修复。每个关键路径
   覆盖正常、缺失、零分母/不适用、顺序扰动及篡改负例。

## 错误处理

- 合法数据不足保持 `insufficient_data` / exit 3，而不是内部错误 exit 5。
- 验证失败保持 exit 4；未知披露时间及不可比年度只能降级，不能伪造事实或历史截面。
- 非法或不可重算的 `valid` 指标为明确 Validator error/warning，不能静默跳过。

## 验证

按任务书执行 Forecast 端到端、财务重算、CLI、黄金案例和完整回归，并额外覆盖 Markdown
篡改、文档 mtime 伪造、未来披露污染、全拒绝导入、Run JSON/数据库等价与同行资格篡改。

## 提交边界

- Commit A：执行链路与时间语义。
- Commit B：确定性验证与报告一致性。

