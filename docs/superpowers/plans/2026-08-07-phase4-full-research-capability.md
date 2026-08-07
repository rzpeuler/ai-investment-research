# Phase 4.1 实施计划

> 依据：`docs/tasks/phase4-full-research-capability.md`
> 设计：`docs/superpowers/specs/2026-08-07-phase4-full-research-capability-design.md`
> 原则：逐里程碑实现、测试、提交；默认离线；真实调用显式 `--live`。

## Milestone 0：授权与计划

修改：

- 新增正式任务书和本实施计划；
- 在 `DECISIONS.md` 记录 Provider、官方证据、七任务与真实验收边界；
- 校验基线测试、Schema 和 Git 状态。

验收：文档无占位符或冲突，`git diff --check` 通过，独立提交。

## Milestone 1：DeepSeek Provider

新增或修改：

- `config/llm_providers.yaml`；
- `src/research_os/llm/provider_config.py`；
- `src/research_os/llm/provider_factory.py`；
- `src/research_os/llm/providers/deepseek.py`；
- `src/research_os/llm/redaction.py`；
- `src/research_os/llm/client.py`、模型和 CLI；
- Provider 配置、HTTP、错误、预算、脱敏、probe 单元测试；
- `tests/online/test_deepseek_provider.py`。

顺序：先写失败测试，再实现配置和脱敏；随后实现标准库 HTTP 适配器、错误映射和工厂；
最后接入 CLI 和在线 marker。验证未配置、dry-run、认证、限流、超时、5xx、无效 JSON、
Schema 修复、Pro 上限、共享预算和秘密不落盘。

## Milestone 2：官方披露原件链

新增或修改：

- 文档导入服务、内容寻址存储和 CLI；
- DocumentRecord/Block 所需模型、Schema、迁移和序列化；
- 巨潮适配器的 live gating、公告查询、附件定位和下载；
- RawItem/Evidence 构建和来源资格校验；
- 本地文件 fixture、正常/去重/同名异内容/缺元数据/非官方来源测试；
- `tests/online/test_cninfo_disclosure.py`。

所有外部数据先通过统一对象 Schema。下载只进入 Git 忽略数据目录，并保留 checksum、
原文件名、实际存储名和 retrieval metadata。

## Milestone 3：官方核心财务 Evidence

新增或修改：

- FinancialDataManifest/FinancialFact 的文档和 locator 绑定；
- 官方抽取映射输入及人工校正审计；
- Evidence builder 和来源质量判定；
- ERV-080 起的文档、checksum、locator、as_of 和 Tier C 攻击性规则；
- 数值与原件不一致、缺文档/块/locator、事件抬级和人工升级拒绝测试。

实现必须能从 FinancialFact 逐级反查原始官方 URL 和 checksum，且 Validator 可重新核验。

## Milestone 4：完整语义覆盖

新增或修改：

- 七任务实际输出 Schema/业务校验和 Evidence 策略；
- Pipeline 正式调用、管理层陈述/风险/催化剂/反证/研究问题产物；
- 集中状态计算和 ERV 语义/Provider 规则；
- Renderer 只消费已通过结构化校验的对象；
- Fake Provider 全路径、错误类型、实体污染、Evidence 污染和禁止内容测试。

两个完整验收案例使用 `deep` 预算；`standard` 不因 5 次 Flash 上限伪装七任务覆盖。

## Milestone 5：真实在线验收

新增 `config/equity_research_acceptance.yaml` 和默认跳过的 `tests/online/`。按顺序执行：

1. DeepSeek probe 和一次 Flash 结构化调用；
2. 巨潮 probe、公告元数据、附件定位/下载和 checksum；
3. 为贵州茅台与宁德时代导入至少两个完整年度官方原件及 locator；
4. 运行两个 `deep --live` 案例并要求 `SUCCESS`；
5. 运行中芯国际受控缺失案例并要求合法降级；
6. 生成每案机器可读 acceptance summary 和总体验收索引。

在线调用限次数、限输出，不保存密钥、完整请求头、完整 Prompt 或原始响应全文。

## Milestone 6：回归与状态收尾

执行：

```text
python -m pytest --collect-only -q
python -m pytest -q
python -m research_os.cli.main validate
python -m compileall -q src tests
git diff --check
```

记录实际数字、在线脱敏摘要、验收 SHA、提交列表和剩余限制。只有独立验收条件全部满足时
更新 Phase 4 full capability；无论结果如何，本任务不实施 Phase 5。
