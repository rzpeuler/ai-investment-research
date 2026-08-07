# Phase 4.1：完整研究能力补齐与真实端到端验收

> 文档类型：正式实现授权边界
> 下达日期：2026-08-07
> 授权分支基线：`master@e505762cf8fae341ecd06a0c6092f0a88dbb2c7c`
> 工程代码基线：`ce656b1866e0d65b1def292d26bed9c41474983b`
> 开发分支：`codex/phase4-full-research-capability`
> 起始状态：Phase 4 engineering foundation = `PASS`；full capability =
> `PARTIAL_SUCCESS`；Phase 5 = `BLOCKED`

## 1. 授权目标

本任务只补齐 Phase 4 已有个股研报场景的真实外部能力：

1. 接入并验证 DeepSeek Provider；
2. 建立官方披露原件到核心财务事实的高质量 Evidence 链；
3. 接入七个必需语义任务并形成正式产物；
4. 完成两个真实成功案例和一个预期降级案例；
5. 提供可复核的脱敏在线验收材料。

不得新增场景、开始 Phase 5、输出目标价/评级/仓位/交易动作、绕过访问控制、使用
未授权付费来源、伪造 Provider/来源验证或降低 Validator 标准。

详细设计以
`docs/superpowers/specs/2026-08-07-phase4-full-research-capability-design.md` 为准；该设计
只能细化工程指南和正式决策。

## 2. 已批准 Provider

```yaml
provider_id: deepseek
display_name: DeepSeek
api_key_env: DEEPSEEK_API_KEY
base_url: https://api.deepseek.com
api_mode: chat_completions
flash_model: deepseek-v4-flash
pro_model: deepseek-v4-pro
```

密钥只从环境变量读取。真实网络调用必须显式启用 `--live`；默认测试和 dry-run 不得
访问网络。业务代码继续通过 `EquityLlmTasks → LlmClient → LlmProvider`，不得旁路。

## 3. 必需交付

### 3.1 Provider

- 配置、加载校验、工厂和 DeepSeek Chat Completions 适配器；
- JSON Object 输出及完整本地 Schema/Pydantic/业务规则校验；
- 认证、授权、限流、超时、网络、5xx、无效响应、Schema、预算和未配置错误分类；
- 有限重试、共享调用预算、Provider 故障与业务 Pro 升级分离；
- 统一脱敏和 `research llm probe`；
- 离线单元测试与默认跳过的在线测试。

### 3.2 官方披露

- 复用经验证的巨潮适配器查询公告元数据和定位官方附件；
- 支持受控在线下载及用户提供官方文件的辅助导入；
- 文件以 SHA-256 内容寻址存储在 Git 忽略的数据目录；
- 生成 DocumentRecord、DocumentBlock/locator、RawItem、Evidence；
- 缺官方 URL、披露时间、实体、来源资格或文件时明确失败。

### 3.3 核心财务 Evidence

适用的 revenue、cost_of_sales、operating_profit、net_profit、net_profit_attr、
total_assets、total_liabilities、equity_attr、operating_cash_flow 必须能反查官方文档、
block/locator、checksum 和 URL。普通 CSV 或手工金额不得升级为官方 Evidence；无关
S/A 事件不得掩盖 Tier C 核心财务。

### 3.4 七个语义任务

```text
business_description_normalization
management_statement_summary
competitive_factor_candidates
catalyst_candidates
risk_candidates
counter_evidence_organizing
research_questions
```

任务分别校验 Evidence 资格、实体和 as_of。管理层陈述必须有 speaker；竞争因素类型必须
匹配；风险与催化剂必须有 Evidence；反证不得只是原主张改写；模型不得创建 FACT 或引用
未输入 Evidence。

### 3.5 状态和 Validator

完整 `SUCCESS` 还必须满足真实 Provider 调用、七任务覆盖、官方核心财务 Evidence、
分域来源质量、已知 as_of、无核心冲突和 Validator pass。新增规则从 ERV-080 连续编号，
Fake Provider、Tier C 核心财务、缺必需任务或严重 Evidence 缺陷必须阻止 success。

## 4. 验收组合

| 案例 | 股票 | 角色 | 预期 |
|---|---|---|---|
| A | `600519.SH` 贵州茅台 | 稳定消费 | `SUCCESS` |
| B | `300750.SZ` 宁德时代 | 技术/复杂制造 | `SUCCESS` |
| C | `688981.SH` 中芯国际 | 受控缺失 | 合法降级 |

案例仅用于工程覆盖，不构成投资推荐。配置中记录预期状态和缺失条件，不在代码中写死。

## 5. 里程碑和提交

1. `docs: authorize phase4 full research capability completion`
2. `feat: add verified llm provider integration`
3. `feat: add verified disclosure evidence ingestion`
4. `feat: bind core financial facts to official evidence`
5. `feat: complete phase4 semantic research coverage`
6. `test: add phase4 live end-to-end acceptance`
7. `docs: record phase4 full capability acceptance`

每个里程碑单一职责并运行相关测试。状态收尾只有在真实独立验收通过后执行。

## 6. 最终验收

默认离线测试、Schema、compileall 和 diff-check 必须通过；在线测试必须显式运行并保存
脱敏摘要。完整能力申请前必须取得两个真实 `SUCCESS` 和一个预期降级案例。最终结论只可
为 `READY_FOR_INDEPENDENT_ACCEPTANCE`、`NOT_READY_PROVIDER`、`NOT_READY_EVIDENCE`、
`NOT_READY_SEMANTIC_COVERAGE` 或 `NOT_READY_VALIDATION`。

本任务完成不自动授权 Phase 5。未满足真实条件时维持 Phase 4 full capability
`PARTIAL_SUCCESS` 和 Phase 5 `BLOCKED`。
