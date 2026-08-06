# 当前项目状态（CURRENT STATE）

> 生成日期：2026-08-06 · 由 Phase 4 收尾后更新

## 版本基线（任务书 5.1 节规范）

```yaml
remote_head: "待远端核对（本地实施至 Phase 4 代码基线）"
code_baseline: "待 Phase 4 独立验收后记录"
phase4_start_baseline: 2b7827c
phase4_end_code_commit: "待独立验收后记录"
documentation_head: "待独立验收后记录"
```

> 说明：本地 Phase 4 实施已完成 18 个提交序列（Commit 1—18），
> 最终代码基线/文档 HEAD 以独立验收核实的提交为准（验收任务书 5.9：不允许把
> 仓库文档中的历史本地状态当作当前本地状态，本地 HEAD 只有实际运行 git 后记录）。

## Phase 0—4 状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0（骨架与契约） | **PASS** | 目录结构、Schema、Pydantic 模型、SQLite+迁移、抽象接口、Orchestrator、CLI、运行目录、Front Matter 校验、测试 |
| Phase 0.1（控制面加固） | **PASS** | 契约说明文档、CLI UUID 边界、失败状态持久化、结构化 JSONL 错误日志 |
| Phase 1（来源探测与数据底座） | **PASS** | 来源注册表、探测框架、5 适配器、主备路由、健康检查 |
| Phase 1.1（行情契约修正） | **PASS** | 实时快照与历史日线严格分离 |
| Phase 2（信息筛选系统与每日晨报） | **PASS** | 晨报流水线、四方向覆盖、19 Schema、CLI morning-brief、Skill、Cron 文档、黄金测试集 |
| **Phase 3（异动分析）** | **PASS** | 独立验收结论 PHASE 3 PASS；551 passed；30 Schema；迁移 4 |
| **Phase 4（个股研报）** | **实施完成，待独立验收** | 见下方 Phase 4 交付清单 |

**Phase 5（产业图谱）尚未开始**（见 NEXT_PHASE.md）。

## Phase 4 交付清单（2026-08-06 收尾）

- 正式任务书：`docs/tasks/phase4-equity-research.md`（18 提交序列/50 Schema/
  迁移 5/ERV-001—070/38 章节/25 黄金案例）
- **20 个新 Schema（30→50 总数）**：company_profile / security_profile /
  document_record / document_block / financial_data_manifest / financial_report /
  financial_fact / financial_metric / business_segment / peer_candidate /
  peer_selection / valuation_snapshot / forecast_scenario / competitive_factor /
  catalyst / risk_factor / research_finding / equity_research_request /
  equity_research_run / equity_research_result；Entity 兼容 `security` 枚举
- **迁移 005（user_version=5）**：20 张新表，payload+检索列，唯一约束
  （manifest checksum+data_version、report 五元组、fact 四元组、peer 四元组、
  selection、runs idempotency_key+run_version），TEXT decimal 值列，无 CASCADE
- **财务导入**：`financials/import_service.py`（CSV/JSON/XLSX → Manifest+Report+Fact；
  行级接受/拒绝；十进制字符串；空串=missing≠0；checksum+data_version 幂等；
  dry-run 零副作用；rejected 行不落库）
- **文档底座**：`documents/registry.py`（SHA-256 去重/页码定位/文本块/表格块/
  OCR 协议层/人工纠错不覆盖历史/证据定位器）
- **财务标准化**：taxonomy 映射、单季拆分（derived_from_report）、YoY/QoQ/CAGR/
  TTM、单位换算（CNY yuan）、重述优先级、冲突组
- **财务指标**：24 个确定性公式（增长/利润率/ROE/ROA/ROIC/资产负债/周转/现金流/
  费用率/每股），Decimal 精度 8，输入血缘完整，金融企业 N/A 降级
- **财务质量**：三表勾稽 + 四层阈值（会计硬规则/robust 统计/同行分位/后备阈值）
  20 条规则，只告警不认定造假
- **业务分部**：raw/canonical 名、重分类组、跨期合并安全、LLM 候选不自动批准
- **同行选择**：九维加权评分、防事后选择、样本门槛（5/3-4/<3）、用户 --peer 不自动合格
- **估值**：市值/EV/PE/PB/PS/EV_EBITDA/FCF_Yield/股息率/分位；结构性禁止目标价
- **情景预测**：默认关闭；显式假设；claim_type 非 FACT；model_generated 须真实调用
- **催化剂/风险**：状态机、必填字段、Phase 3 归因只读、widely_known 不自信判断
- **LLM 语义模块**：统一 LlmClient（无旁路）；任务级预算（fast 2/0、std 5/1、deep 8/1）；
  禁止内容拦截；未配置诚实回退
- **研报渲染**：38 章节模板、必须章节、缺数据写覆盖状态、无套话、免责声明
- **Validator**：ERV-001—070 系列（禁止词/FACT 证据/MODEL_INFERENCE 调用/Phase 3
  只读/dry-run 副作用/幂等重复等），error→fail、warning→pass_with_warnings
- **CLI**：`research run equity-research`（参数/退出码 0/2/3/4/5/不猜代码/
  dry-run 零副作用/force 不覆盖旧产物）
- **Hermes Skill**：skills/finance/equity-research/SKILL.md（只构造 CLI）
- **黄金测试集**：tests/golden/equity_research/（25 类案例结构断言）

## 测试数量

```text
921 passed（独立验收修复后全量回归，含 Phase 0-3 551 基线 + Phase 4 新增 370）
0 failed / 0 skipped    全部离线
```

命令：`python -m pytest -ra --tb=short`（在项目根，venv 内）。
**独立验收必须重新运行，不直接引用本数字**（任务书 5.10）。

## 独立验收修复记录（2026-08-06 二审前）

首次独立验收 FAIL（3 BLOCKER），已全部修复：

1. **BLOCKER 1 流水线骨架化** → 已修复：EquityResearchPipeline 接入全部已开发模块
   （文档登记/解析、财务标准化校验、三表勾稽、24 指标、质量规则、业务分部、同行
   候选与选择、估值、Phase 3 归因只读关联、晨报事件复用、催化剂/风险、冲突检测、
   Findings、Claim/Evidence 索引），25 阶段全部执行；研究状态按真实覆盖计算
   （>=2 可比年度 success / 1 年 partial_success / 0 年 insufficient_data exit 3）；
   可选模块缺数据时如实标记 missing_data 并降级 degraded，不以空章节代替。
2. **BLOCKER 2 Validator 未实现** → 已修复：ERV-001—070 全集实现并接入主入口
   （含 check_schema ERV-001/002、check_idempotent_no_duplicate ERV-070、
   财务 ERV-009—027、估值 ERV-029—040、Evidence/OCR ERV-042/050/051、
   引用一致性 ERV-057/058、未来信息 ERV-053 覆盖 facts/blocks）；HYPOTHESIS
   缺失效条件升级为 error（ERV-046 硬约束）；pipeline 传入真实对象
   （facts/metrics/reports/peers/peer_selection/valuation/factors/blocks/
   phase3/runs）。
3. **BLOCKER 3 CLI 语义未实现** → 已修复：Validator 失败 exit 4（独立异常类，
   不再被内部异常吞成 exit 5）；幂等查询返回 idempotent_skipped；force 生成新
   run_version 不覆盖旧产物；peer/scenario/valuation/forecast/document/
   market-file 全部进入 _execute；Request/Run/Result 持久化 + 完整运行目录产物
   （JSON + JSONL）+ 原子写入。
4. **黄金测试非端到端** → 已重建：tests/golden/equity_research/ 改为真实跑
   EquityResearchPipeline（>=2 年度 fixture → 断言 Request/Run/Result/指标/
   facts/运行产物/研究状态/模型路由/Validator/报告无目标价/幂等/force/同行
   不自动合格/Phase 3 只读/重述冲突检出/未来信息 exit 4），删除无意义断言。
5. **CLI 集成覆盖不足** → 已补齐：exit 4/5、幂等、force 不覆盖旧产物、
   peer+valuation 进入流水线。
6. **最低两个可比年度** → 已落实到能力检查（1 年 partial_success、0 年 exit 3）。

## Schema、迁移版本和 CLI

### Schema（50 个，`schemas/`）

Phase 0（9）+ Phase 1（4）+ Phase 1.1（2）+ Phase 2（4）+ Phase 3（11）+ Phase 4（20）。
校验：`research validate`（全部 50 个通过）。

### SQLite 迁移

`PRAGMA user_version` = **5**（001—005）。

### CLI（`research`）

| 命令 | 说明 |
|---|---|
| `run [--task-id/--scenario/--entity/--depth/--as-of/--force]` | 空任务：生成 Task/Plan/Run 目录；幂等 |
| `run morning-brief [...]` | 晨报流水线（默认离线 manual_inbox） |
| `run abnormal-move --entity 600519.SH [...]` | 异动分析流水线（个股/行业/概念） |
| `run equity-research --entity 600519.SH --financial-file fin.csv [...]` | 个股研报流水线（Phase 4） |
| `market-data import-daily --file ...` | 人工日线导入 |
| `validate` | 校验全部 Schema / 报告 |
| `probe-sources` / `health` / `inbox add|list|status` | 来源探测/健康检查/人工 Inbox |

## 真实 LLM Provider 状态

- 未接入真实 Provider（Fake Provider 全链路测试通过）；
- 未配置时报告 Front Matter 与模型路由如实记录
  `model_route: {mode: deterministic_fallback, llm_called: false}`；
- 任务级 Flash/Pro 预算与升级条件已实现，待真实 Provider 客户端接入后生效。

## 来源状态（Phase 4 收尾）

- 新增人工来源：`manual_financial_import`、`user_document`（registry/sources.yaml，candidate）；
- 未验证的自动财务源未登记为 primary/secondary；
- 历史日线仍仅 `manual_import`；分钟级仅协议。

## 当前工作区状态

```text
git status: clean（Phase 4 提交序列完成后）
分支: master
安装: 普通 pip 安装（非 editable，Windows 中文路径 + GBK locale 约束）
Python: venv 3.11.15（uv 托管）；系统 3.12.10
包名: research-os 0.1.0
```

> 本地 HEAD 与远端同步状态、最终代码基线、独立验收结论：待独立验收核实后记录。
