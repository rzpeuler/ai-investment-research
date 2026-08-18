# Frontend Product Architecture（AI 投研工作台）

> 状态：**DESIGN FROZEN / IMPLEMENTATION NOT AUTHORIZED**
> 治理依据：`docs/project-state/DECISIONS.md` **Decision #55**
> 治理任务书：`docs/tasks/governance-agent-runtime-frontend-design-freeze.md`（GOV-ARUX1）
> 日期：2026-08-18
>
> 本文件冻结**最终产品结构（页面与职责层）**。本任务不授权任何 UI 代码实现；
> 当前 UI 代码保持 UNCHANGED。任何后续前端实现须独立 frontend taskbook。

---

## 1. 产品定位

"个人 AI 投研操作系统 / AI Research OS"。

核心价值：

- 用对话发起研究；
- 用真实数据支撑研究；
- 用 Evidence 验证研究；
- 用产业图谱积累长期认知。

不得把产品定位成：交易终端、自动荐股系统、量化下单系统、目标价生成器、ChatGPT 套壳。

## 2. 设计原则

1. 前端是 **projection / read-model**，不是第二套业务 authority。
2. 状态展示不得夸大能力：Registry 存在 ≠ Collector 实现 ≠ Workflow 接线 ≠ 业务充分。
3. 数据不足 != 执行失败；`partial_success / degraded / insufficient_evidence` 不得
   统一映射成"失败"。
4. AI 理解 gate 与 Research Live Data gate 永远独立，不得合并。
5. Evidence drawer / lineage 是正式产品能力。
6. 前端不得显示模型 private chain-of-thought。
7. 数据源编辑属于治理写操作：Diff + Impact + Confirm + Audit。
8. 一级页面职责冻结，视觉可调整；实现 Agent 不得擅自改变页面职责。

## 3. 一级导航

左侧主导航冻结为：

```text
今天

研究
  AI研究
  公司
  产业图谱
  研究库

系统能力
  能力指南
  数据中心
  待审核

右上：设置

全局：搜索 / 当前研究上下文 / Evidence drawer / status indicator
```

## 4. 全局布局

- 全局搜索：跨公司 / 行业 / 主题 / 研究 / 证据检索。
- 当前研究上下文：当前 target / as_of / 场景 / 状态常驻可见。
- Evidence drawer：右侧抽屉，任何事实性结论可"查看依据"。
- status indicator：全局数据 / 系统状态指示。

## 5. 今天

"今天"是日常工作入口，**不使用工程术语 Dashboard**。包含：

- 大型自然语言研究输入框；
- 快捷入口：今日晨报 / 今日复盘 / 行业研究 / 个股研究；
- 最近研究；
- 当前数据高层状态；
- 当前需要用户处理的待审核项。

首页禁止主要展示：pytest 数量、schema 数量、DB version、CI run、内部 class name、
debug logs。这些只进入高级/工程状态。

## 6. AI研究

目标布局：

```text
左：AUTO / 10 个正式研究场景 + 历史研究/会话
中：Conversation + Business Progress + Research Result
右：current target / as_of / data readiness / online data /
    model profile/status / source/evidence context
```

业务进度显示（禁止 private chain-of-thought）：

```text
正在确认研究对象
正在检查数据
正在获取缺失数据
正在读取财务
正在读取产业图谱
正在整理证据
正在运行研究
正在验证结果
已完成
```

当前阶段（Harness 未接入前）继续由 P7-UX1 existing chat 承担会话入口；未来演进为
Harness Session/Agent 驱动，但 AI Research session integration 必须兼容最终 Harness
boundary。

## 7. 研究结果

Tabs：研究结论 / 财务 / 事件 / 风险与催化 / 证据 / 数据状态。

默认显示：

- 研究对象、场景、as_of、状态、信息完整度
- 核心研究判断、财务质量、竞争优势/弱点
- 风险、催化、研究限制

禁止：Buy / Sell、目标价、仓位、自动交易。

## 8. Evidence Drawer

对事实性结论支持"查看依据"，右侧 drawer 至少展示：

- source、publisher、document/report、published_at
- page / block / locator
- excerpt or structured value
- source tier、Evidence ID
- RawItem / Document reference
- as_of eligibility

Evidence UI 不得凭前端自己创造 source authority。

## 9. 公司

Tabs：概览 / 财务 / 公告 / 研究 / 产业链 / 证据。

未有真实数据时必须显式显示："尚未自动接入" / "数据不足" / "仅支持人工输入"。

禁止伪造 K 线、实时价格、历史估值。D4 / D5 / realtime 能力只有在对应独立验收后才
允许 UI 宣布自动可用。

## 10. 产业图谱

默认视图：行业树 + 1-hop graph + 节点详情。

支持关系：上游 / 下游 / 竞争 / 替代 / 受益 / 受损（根据实际 ontology/relations
显示，不在前端写死虚构行业关系）。

epistemic 显示：

```text
基础治理结构      GOVERNANCE
已证实事实        FACT
研究判断          MODEL_INFERENCE
```

MODEL_INFERENCE 必须可查看：evidence、confidence、as_of、review state。

as_of selector 为正式产品能力。不得用超大蜘蛛网作为默认首页。

## 11. 研究库

支持按：公司 / 行业 / 主题 / 日期 / 场景 / 状态 检索历史研究。

Report / Run / Evidence authority 仍来自 Research OS。

## 12. 能力指南（正式一级能力）

不是静态帮助页面。它回答：

1. 系统能做什么？
2. 某个真实研究场景怎么工作？
3. 工作流经过哪些步骤？
4. 每一步由哪个功能模块负责？
5. 每个模块需要什么数据？
6. 使用哪些 Skill / Tool / Workflow？
7. 当前能力是可用、部分可用还是未接入？

两个入口：按研究场景、按功能模块。

### 12.1 需求场景层

从正式 Scenario Registry / accepted scenario metadata 投影当前十场景：
每日晨报 / 异动分析 / 个股研报 / 每日晚报 / 每日复盘 / 个股复盘 / 行业研究 /
主题发现 / 财报预期 / 首次覆盖。不得维护第二套硬编码业务场景 authority。

每个场景页面至少包括：这个能力做什么、适合什么时候使用、示例提问、需要的数据、
输出、正式工作流、每一步状态、相关功能模块、相关 Skill、相关 Tool、相关数据类型、
当前限制。

### 12.2 Workflow 可视化

显示 business workflow state（例如个股研报）：

```text
理解需求 → 确认公司 → 检查数据 → 补充数据 → 财务分析 → 业务/竞争分析 →
图谱上下文 → 语义研究 → Evidence validation → 正式报告
```

禁止显示 private chain-of-thought。

### 12.3 功能模块层

按功能模块展示：研究入口 / 研究控制 / 数据处理 / 研究分析 / 知识能力 / 输出能力。

每个模块至少显示：负责什么、被哪些场景使用、输入、输出、是否确定性、是否使用 LLM、
是否允许网络、是否写数据库、依赖数据、当前状态、实现位置（高级信息）、
Skill / Tool mapping。

### 12.4 Capability Catalog 原则

能力指南不得在 HTML/JS 中硬写完整能力真相。未来建立 **Capability Catalog
Projection**（不是新的 business authority），组合读取：

- Scenario Registry
- Scenario Data Requirements
- Data Acquisition Capabilities
- Source Registry
- module metadata
- Research OS tool metadata
- 未来 Harness Skill Registry

前端只消费 projection。禁止创建 `frontend_capabilities.yaml` 作为第二套 authority，
除非后续正式 Decision 明确批准。

## 13. 数据中心（正式一级能力）

Tabs：数据准备度 / 数据源 / 采集能力 / 采集记录。

### 13.1 数据准备度

面向业务显示：数据类型、当前状态、覆盖对象、覆盖期间、最新时间、来源等级、
自动化程度、缺口。

DataGap 状态翻译固定：

| 后端状态 | 前端文案 |
|---|---|
| READY / AVAILABLE | 已准备 |
| AUTO_ACQUIRABLE | 可以自动获取 |
| STALE_REFRESHABLE | 数据较旧，可以更新 |
| MANUAL_INPUT_REQUIRED | 需要你提供数据 |
| HUMAN_REVIEW_REQUIRED | 需要确认 |
| NOT_ACQUIRABLE / UNAVAILABLE | 当前没有可用数据源 |
| SOURCE_UNHEALTHY | 数据源暂时不可用 |

不得把"Source Registry 已登记"翻译成"数据已准备"。

### 13.2 数据源

按 Platform → Source 展示（一个平台可含多个 Source）。展示字段至少：平台、source_id、
display name、source type、source tier、access level、paid、login required、
automation level、update frequency、storage policy、allowed usage、governance
status、verification status、lifecycle、提供的数据类型、被哪些场景使用。

需要支持：官方披露、政府监管、行情、新闻、社区、人工数据、未来其他平台。
实际名单只能来自 Source Registry / governance metadata。

### 13.3 Source != Capability

```text
Source Registered ≠ Collector Implemented ≠ Workflow Wired ≠ Business Sufficient
```

lifecycle 展示（枚举与值以项目当前正式 lifecycle contract 为准）：

```text
REGISTERED → PROBED → ADAPTER_IMPLEMENTED → WORKFLOW_WIRED → BUSINESS_SUFFICIENT
```

禁止前端自行晋级状态。

### 13.4 数据能力矩阵

展示：Data Type / Current primary path / Automation / Lifecycle / Readiness /
Used by scenarios / Known limitations。

矩阵来源：`scenario_data_requirements` + `data_requirements` +
`data_acquisition_capabilities` + source registry + readiness projection。
不得从单一 sources.yaml 猜业务充分性。

### 13.5 数据源详情

例如 CNINFO 页面展示：平台信息、来源等级、访问方式、费用、登录要求、存储策略、
允许用途、提供数据、Collector / Adapter 状态、Workflow 状态、Capability lifecycle、
最近验证、被哪些数据类型使用、被哪些场景间接使用、Known limitations。

必须明确："连接正常" ≠ "业务充分"。

### 13.6 测试连接

未来 UI 可提供"测试连接"，但 Test Connection PASS 只代表 connectivity / probe。
绝对不得自动 `REGISTERED → WORKFLOW_WIRED` 或 `WORKFLOW_WIRED → BUSINESS_SUFFICIENT`；
任何 capability 晋级继续走正式治理。

## 14. 数据能力矩阵

见 §13.4。矩阵是 read-model projection，不是业务 authority。

## 15. 数据源编辑

允许未来提供：编辑数据源 / 新增数据源 / 停用数据源；但禁止把 Source Registry 暴露为
普通 YAML 编辑器。

两类修改分开处理：

- A. Runtime / operational preference：临时禁用、请求频率限制、当前不优先使用、
  用户 preference；
- B. Governance fields：source_tier、paid、login_required、allowed_usage、
  storage_policy、source_type、authority、status。

Governance 修改流程：

```text
编辑 → Validate → Diff Preview → Impact Analysis → User Confirm →
Governance Write Path → Audit Record → New Effective Configuration
```

不得"表单保存 → 直接无提示覆盖 registry"。

Impact Analysis 至少展示：修改前、修改后、影响的数据类型、影响的场景、影响的
storage policy、影响的 acquisition capability、可能要求重新 probe / acceptance 的
项目。例如 `metadata_and_excerpt → full_text` 必须高亮存储政策变化、版权/来源治理
变化、Evidence/Document 影响，不得静默生效。

新增数据源向导：

```text
基本信息 → 访问方式 → 数据内容 → 使用范围 → 存储政策 →
Probe → Governance Review → Register
```

必须显示："登记数据源 ≠ 自动可用于正式研究"。

## 16. 待审核

对应现有 Graph candidate / review / apply 治理。展示：subject、relation、object、
fact / inference、evidence、conflict、review state。

用户动作：批准 / 修改后批准 / 暂缓 / 拒绝。但任何前端批准动作仍必须经过：

```text
Review Contract → Validator → Deterministic Apply
```

前端按钮不得绕过 Validator。在 Phase 6.1 / future integration 未授权时，不得出现
"AI 自动更新图谱"开关。

## 17. 设置 / Agent Profile 未来入口

设置页面为未来 Agent model profile / 套餐 / Session 策略入口的容器。当前：
Agent model profile / 套餐 UI 尚未实现。生产 Session retention / encryption /
cleanup policy 由 P8-A0 先验证，正式上线前单独冻结。

## 18. 用户状态语言

前端统一使用：已完成 / 部分完成 / 数据不足 / 正在获取数据 / 正在研究 /
需要你确认 / 执行失败。

必须冻结：

```text
DATA INSUFFICIENT != EXECUTION FAILED
partial_success / degraded / insufficient_evidence 不得统一映射成"失败"
```

## 19. AI/Live 两开关

必须继续保留两个独立开关：

```text
AI 理解（AI / Agent enabled）  —— 控制 Agent/LLM 交互
在线数据（Research Live Data） —— 控制正式 Research OS 数据获取权限
```

不得合并。未来 Harness 接入后语义不变：

- Agent ON 不等于自动联网；
- Online Data ON 不等于允许任意 Agent 网络访问。

## 20. Capability lifecycle UI semantics

- 前端只展示后端 authority（Source Registry / data_acquisition_capabilities /
  readiness projection）给出的 lifecycle 值；
- 前端不晋级、不降级、不发明 lifecycle；
- "连接正常 / probe 成功" 只显示为 connectivity 状态，绝不自动晋级 capability；
- 用户可见文案用 §13.1 固定翻译表，不显示内部枚举歧义。

## 21. 权威数据来源

| 前端页面 | 数据来源（唯一 authority） |
|---|---|
| 场景列表 / 场景详情 | Scenario Registry（`scenario_data_requirements.yaml` 等） |
| 数据准备度 | readiness projection（DataReadiness / DataGap） |
| 数据源列表 / 详情 | Source Registry（`sources.yaml` + governance metadata） |
| 采集能力 | `data_acquisition_capabilities.yaml` |
| 待审核 | Graph candidate / review 治理数据 |
| Evidence | Evidence / RawItem / Document authority |
| 研究 / 报告 / 运行 | Research OS Report / Run / Result authority |
| 能力指南 | Capability Catalog Projection（组合读取，见 §12.4） |

## 22. Feature gating

- 只有对应独立验收通过的 capability，UI 才允许显示为"自动可用"；
- D4 / D5 / realtime 能力在独立验收前一律显示"尚未自动接入 / 数据不足 /
  仅支持人工输入"；
- 未实现的未来能力显示为"未接入 / 设计中"，不得渲染成已可用；
- 所有 gate 在 projection 层判定，前端不自行打开。

## 23. 当前可实现 / D4 后 / D5 后 / future

| 阶段 | 可进入前端的能力 |
|---|---|
| 当前 | P7-UX1 existing chat（本地会话入口）、研究结果/证据查看、现有 Graph 只读查询、待审核展示 |
| P7-D4 后 | 仅当 D4 独立验收通过并由治理 closeout 晋级后：company_document / financial_statement_data 的 WORKFLOW_WIRED → 后续 BUSINESS_SUFFICIENT 展示 |
| D5 后 | 仅当 D5 独立 taskbook + 验收通过后：对应新增数据能力 |
| future | Harness session UI（NOT_IMPLEMENTED）、能力指南、数据中心完整 surface、数据源编辑 |

## 24. 明确禁止项

- 首页主要展示 pytest / schema / DB version / CI / class name / debug logs；
- 伪造 K 线、实时价格、历史估值；
- Buy / Sell / 目标价 / 仓位 / 自动交易；
- 把 Registry 存在、Collector 存在、连接测试成功误表示成业务能力可用；
- 前端绕过 Validator 直接批准 Graph change；
- "AI 自动更新图谱"开关（Phase 6.1 未授权前）；
- 显示模型 private chain-of-thought；
- 硬编码第二套业务场景 / 能力 / 数据源 authority（如 `frontend_capabilities.yaml`）；
- 把 Source Registry 暴露为普通 YAML 编辑器；
- 表单保存后无提示覆盖 registry。

## 25. 能力状态表

| 功能 | 当前设计状态 |
|---|---|
| 今天 | DESIGN_FROZEN |
| AI研究 | EXISTING UX1 + FUTURE HARNESS EVOLUTION |
| 公司 | DESIGN_FROZEN |
| 产业图谱 | DESIGN_FROZEN |
| 研究库 | DESIGN_FROZEN |
| 能力指南 | DESIGN_FROZEN / NOT_IMPLEMENTED |
| 数据中心 | DESIGN_FROZEN / PARTIAL BACKEND CAPABILITY |
| 数据源编辑 | DESIGN_FROZEN / NOT_IMPLEMENTED |
| 待审核 | BACKEND GOVERNANCE EXISTS / PRODUCT UI NOT IMPLEMENTED |
| Harness session UI | NOT_IMPLEMENTED |

---

## 附：与 Agent Runtime 的连接关系

最终目标：

```text
Frontend → Harness Session/Agent → Skill → Tool → Research OS →
Data / Evidence / Graph / Report
```

能力指南关联：Scenario ↔ Skill ↔ Capability Module ↔ Tool ↔ Data Type ↔ Source ↔
Evidence。

数据中心关联：Source ↔ Data Type ↔ Capability ↔ Scenario。

用户可以从"个股研报 → 财务数据步骤"跳转到"数据中心 → financial_statement_data"；
也可以从"CNINFO → 被哪些研究使用"反向看到相关场景。这种关联是 read-model /
projection，不是改变业务 authority。
