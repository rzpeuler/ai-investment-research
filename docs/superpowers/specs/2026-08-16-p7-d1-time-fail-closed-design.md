# P7-D1 时间语义 Fail-Closed 修复设计

## 目标

关闭 PR #25 独立复验发现的四处 R3.1 时间语义缺口。所有决定请求截止时间、财务发布可用性、证券生命周期和市场交易日资格的比较，必须先解析再比较；畸形时间不得通过资格判断。

## 范围

允许修改：

- `src/research_os/data_layer/request_context.py`
- `src/research_os/data_layer/checkers.py`
- P7-D1 时间语义相关单元测试

禁止修改：Schema、Registry、数据库迁移、Router、Collector、Runner、公开接口、业务成功语义。不得增加网络、LLM、Acquisition execution 或 Graph write。

## 设计

### 请求截止时间

`_min_iso` 仅接受可由项目标准时间解析器解析的时间。先解析两个非空值，再按时间点选择较早的原始字符串；任一值畸形时传播 `ValueError`，不再使用字符串顺序回退。

### 财务发布时间证明

财务事实的发布可用性是正向证明：只有精确引用的 Evidence 或 Document 的 `published_at` 与请求 `as_of` 都可解析，且发布时间不晚于截止时间时才返回真。不得复用“解析失败即触发淘汰”的布尔比较语义来提供正向证明。

### SecurityProfile 生命周期

将 `as_of` 的日期部分、`listing_date` 和存在时的 `delisting_date` 全部使用 `date.fromisoformat` 解析。`as_of`、上市日或退市日畸形时，该候选立即不合格。正常生命周期规则保持不变：未来上市不合格，已到退市日不合格，`delisted` 状态不合格。

### Market 交易日

将 `trade_date` 和 `as_of` 日期使用 `date.fromisoformat` 解析。任一值缺失或畸形时，该行情候选不合格；交易日晚于截止日期时不合格。其他 scope、provenance、coverage 和 freshness 行为不变。

## 错误处理

- 请求上下文中的畸形时间属于无效请求上下文，显式抛出 `ValueError`。
- Authority payload 中的畸形时间属于不合格候选，不中断整个 readiness 扫描。
- 不用默认值、字符串比较或估算值掩盖错误。

## 测试

新增回归测试覆盖：

1. `_min_iso` 对等价时区时间按实际时间点比较，并对任一畸形值抛错。
2. Evidence/Document 畸形发布时间不能证明 FinancialFact 已发布。
3. SecurityProfile 畸形 `as_of`、`listing_date`、`delisting_date` 均不合格；合法边界保持原行为。
4. Market 畸形或未来 `trade_date` 不合格；合法当日及历史交易日保持原行为。

验收依次运行攻击测试、P7-D1 目标测试、完整 `python -m pytest`、85 Schema 校验、`compileall` 与 `git diff --check`。

## 非目标

不引入全局三态时间比较框架，不统一重构所有 checker，不增加新的 payload 验证层，不改变缺失可选生命周期字段的既有语义。
