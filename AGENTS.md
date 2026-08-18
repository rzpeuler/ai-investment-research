# AGENTS.md — AI＋A股投研 Skill 项目工程与执行规则

本文件为工程执行 Agent（Hermes/DeepSeek/Codex）的**不可违反规则**。
完整规范见 `docs/engineering-guide.md`。两者冲突时以 `docs/engineering-guide.md` 为准。

文档权威顺序为：`docs/engineering-guide.md` → `docs/project-state/DECISIONS.md` →
`docs/tasks/*.md` → `CURRENT_STATE.md` → `NEXT_PHASE.md` → `KNOWN_LIMITATIONS.md` →
`README.md`。阶段任务只能细化指南和正式决策，不能静默覆盖。

## 0. 项目定位（不得自行修改）

- 个人使用的 AI＋A 股投研系统；A 股为主，港股/美股/商品/海外宏观仅作背景或对照。
- 四层框架：需求场景层 / 功能模块层 / 数据采集层 / 知识库层 + 横向工程控制面。
- 首批场景：个股研报、每日晨报、异动分析。不增加用户未提出的业务场景。

## 1. 输出边界（禁止项，机械校验器强制检查）

禁止输出：目标价、买入/卖出评级、增持/减持建议、仓位建议、明日交易建议、
"可以买/可以跟/上车"等引导性语言、自动化荐股。
允许输出：事实归纳、产业影响、财务与业务分析、估值方法及其适用性、同行与历史
估值比较、市场隐含假设、催化剂、风险、多空主要矛盾、待验证问题、敏感性分析。

## 2. 质量控制核心规则（指南 57 节，13 条）

1. 无来源，不写事实。
2. 无原始证据，不把媒体总结升级为确定事实。
3. 数字必须记录来源、口径和数据日。
4. 观点必须标明说话者。
5. 推断必须标明为模型推断。
6. 事件时间与文章时间必须分开。
7. 多篇转载不得当作独立证据（independence_group）。
8. 数据过期必须显式标记。
9. 证券代码和公司名必须通过实体映射。
10. 无法归因允许结束任务。
11. 不得将缺失数据解释为"没有变化"。
12. 不得将舆情热度解释为机构买入。
13. 不得生成目标价和交易建议。

允许的未知状态：`UNKNOWN` / `INSUFFICIENT_EVIDENCE` / `UNEXPLAINED_MOVE` /
`SOURCE_CONFLICT` / `DATA_DEGRADED`。不得强行给出单一原因。

## 3. 确定性任务必须使用代码（指南 6.3）

日期计算、交易日判断、证券代码映射、数值计算、财务比率、估值公式、收益率与
Alpha、去重哈希、Schema 校验、报告章节校验、数据日期校验、文件路径与命名、
数据库写入、任务幂等判断 —— 全部用确定性代码实现，不得交给 LLM。

LLM 只处理：分类、事件和观点提取、语义去重辅助、产业链推理、信息价值判断、
原因候选排序、研究结论组织、待验证问题生成。

## 4. 采集层规则（指南 6.2、21-25 节）

- 平台采集器（雪球/财联社/巨潮等）属于数据采集层，不是功能模块。
- 禁止在功能模块 Prompt 中写死网页结构、CSS 选择器、Cookie 或平台登录流程。
- 未验证数据源时建立 stub，并明确 TODO；不得伪造 API、字段、网页选择器或数据。
- 任何具体源不能写死为唯一依赖；主源失败必须记录失败、切换备源、标明降级、
  禁止估数、在报告中披露实际数据日。
- 默认存储 `metadata_and_excerpt`，不保存全文。
- 社区来源只用于关注点/叙事/分歧/线索，不得单独支持核心事实。
- 来源等级与观点影响力必须分开；来源等级不能自动决定观点正确性。

## 5. 数据契约（指南 11 节）

- 所有外部数据先经过统一 Schema：Task / Entity / RawItem / Event / Opinion /
  Claim / Evidence / ModuleResult / GraphChange。
- 所有对象必须通过对应 JSON Schema 校验（`schemas/*.schema.json` 为权威契约）。
- 所有失败必须返回明确状态（`failed` / `partial_success` / `degraded` /
  `insufficient_evidence`），禁止静默失败。

## 6. 模型路由（指南 51-53、72 节）

- 确定性任务不用模型。
- Flash 默认承担分类/摘要/抽取/简单评分/模板填充/普通代码。
- 满足任一条件升级 Pro：reasoning_conflict_count>=3、独立高等级来源冲突、
  supply_chain_hops>3、候选原因 top2 得分差<8、flash 校验失败>=2、
  图谱本体变更、核心规则修改。
- 调用 Pro 后仍不能解决时输出待人工审核，不继续升级或循环。
- 业务升级路由与 provider 故障回退必须分离，不得混用。

## 7. 工程执行规则（指南 70 节）

1. 先读取本文件、docs/engineering-guide.md 和当前阶段任务。
2. 每次只实现一个明确里程碑。
3. 不增加业务场景。
4. 不自行修改研究规则。
5. 不把采集逻辑写进 Prompt。
6. 所有外部数据先经过统一 Schema。
7. 所有关键行为要有测试。
8. 不伪造 API、字段、网页选择器或数据。
9. 未验证数据源时建立 stub，并明确 TODO。
10. 修改完成后运行测试和校验。
11. 输出变更文件、测试结果和剩余问题。
12. 每个阶段单独 Git commit。

## 8. 实施阶段（指南 63-69 节）

Phase 0 项目骨架与契约 → Phase 1 来源探测与数据底座 → Phase 2 信息筛选与晨报 →
Phase 3 异动分析 → Phase 4 个股研报 → Phase 5 产业图谱 → Phase 6 其余场景。

**Phase 0 验收通过前不得开始 Phase 1；不得在 Phase 0 实现任何网页抓取。**

## 9. 测试要求（指南 62、74 节）

- 每个核心对象至少包含正常、边界、失败测试。
- 修改完成后运行完整测试：`python -m pytest`。
- 模块完成定义：spec、输入输出 Schema、实现、失败状态、正常/边界/失败测试、
  日志、版本号、示例、可被场景调用、输出通过验证器。

## 10. Agent Runtime / Frontend 治理冻结执行规则（Decision #54 / #55）

- DeepSeek Harness 是已批准的 Agent Runtime target，但当前 NOT_IMPLEMENTED。
- 未经 P8-A0 taskbook 不得安装/集成 Harness。
- Agent Runtime 不得替代 Research OS authority。
- Skill 不得直接执行 source-specific collector routing。
- Graph direct write/approve/apply 不得暴露给 Agent。
- 前端不得硬编码虚假 capability status。
- 数据源连接成功不得自动晋级 lifecycle。
- 前端不得显示 private chain-of-thought。
- 新的 UI/API implementation 需要独立 taskbook。
- D4 恢复时继续遵循现有 D4 taskbook，不因 Agent Runtime Decision 改范围。
