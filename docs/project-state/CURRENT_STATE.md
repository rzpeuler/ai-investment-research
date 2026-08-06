# 当前项目状态（CURRENT STATE）

> 生成日期：2026-08-06 · Phase 4 最终验收后更新

## 版本基线（任务书 5.1 节规范）

```yaml
remote_head: 不在本次本地验收范围（未访问远端）
code_baseline: 4f7cdbd（fix: enforce phase4 metric input contracts）
phase4_start_baseline: 2b7827c
phase4_end_code_commit: 4f7cdbd
documentation_head: 本状态更新提交
```

> 说明：本地 Phase 4 实施 18 提交序列、三轮验收修复与最终复验均已完成；
> 远端状态未查询，不作为本次验收证据。

## Phase 0—4 状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0（骨架与契约） | **PASS** | 目录结构、Schema、Pydantic 模型、SQLite+迁移、抽象接口、Orchestrator、CLI、运行目录、Front Matter 校验、测试 |
| Phase 0.1（控制面加固） | **PASS** | 契约说明文档、CLI UUID 边界、失败状态持久化、结构化 JSONL 错误日志 |
| Phase 1（来源探测与数据底座） | **PASS** | 来源注册表、探测框架、5 适配器、主备路由、健康检查 |
| Phase 1.1（行情契约修正） | **PASS** | 实时快照与历史日线严格分离 |
| Phase 2（信息筛选系统与每日晨报） | **PASS** | 晨报流水线、四方向覆盖、19 Schema、CLI morning-brief、Skill、Cron 文档、黄金测试集 |
| **Phase 3（异动分析）** | **PASS** | 独立验收结论 PHASE 3 PASS；551 passed；30 Schema；迁移 4 |
| **Phase 4（个股研报）** | **PASS** | 三个 P1 全部 CLOSED；947 项测试可稳定收集并全量通过 |

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
947 passed（Phase 4 最终验收修复后全量回归）
0 failed / 0 skipped    全部离线
```

命令：`python -m pytest --collect-only -q`、`python -m pytest -q`
（项目根，系统 Python 3.12.10）。

## Phase 4 最终验收结论（2026-08-06）

**Phase 4 独立验收 PASS**：0 BLOCKER、0 未处置 HIGH，三个 P1 全部 CLOSED。

1. **P1-A valid 指标精确复算 CLOSED**：生成器与 Validator 共用 Decimal 规范化；
   `precision` 不作容差；毛利率 `+1E-9`、`-1E-9` 和最后有效位篡改均触发
   ERV-019；尾随零、负零与科学计数法等价值通过；输入统一规范化为固定小数字符串。
2. **P1-B 参数血缘完整身份 CLOSED**：binding 持久化并核验公司、报告、taxonomy、
   scope、statement type、期间、币种和单位；公式参数额外声明允许的报表类型，事实与
   binding 同步改写 `statement_type` 仍触发 ERV-019；公司/scope/报告版本/币种/单位等
   11 类独立攻击全部失败。
3. **P1-C Markdown 无标记伪造数字 CLOSED**：Renderer 与 Validator 共用
   MetricDisplaySpec、标签/别名和格式化规则；六类指定无标记注入全部触发 ERV-060。
4. **测试收集 CLOSED**：`tests` 为本地显式包，`conftest.py` 注入项目根与 `src/`；
   `tests.golden` / `tests.fixtures` 导入失败未复现；collection 与全量测试均成功。

定向实测：Validator 89 passed；metric/markdown/validator 172 passed、595 deselected；
CLI 集成 16 passed；Phase 4 黄金案例 45 passed。完整回归 947 passed。

## 二次独立验收修复记录（2026-08-06 三审前）

二次验收 FAIL（6 BLOCKER + 5 HIGH），已全部修复：

1. **BLOCKER 1 Claim/Evidence 未建立** → 新建 `equity_research/evidence_builder.py`：
   真实 Evidence 对象（来源/原始条目/标题/发布者/披露时间/URL/摘录/来源等级/
   独立证据组，过 evidence.schema.json）+ 真实 Claim 对象（独立 UUID，非 finding_id
   别名，过 claim.schema.json）；运行产物 claims.json + evidence_index.json；
   Validator 校验真实 Evidence 集合（known_ids 来自真实构建对象，非引用列表自身）。
2. **BLOCKER 2 ERV 不完整** → 删除全部 pass 占位（ERV-015 跨事实一致性真实现、
   ERV-045 fallback 不产生 MODEL_INFERENCE）；补齐 ERV-004—008（必填/枚举/时间顺序）、
   ERV-018—022（指标按 input_fact_ids 复算）、ERV-032（同行资格重算）、
   ERV-035/036（市值时点/EV 口径）、ERV-038（分位样本门槛）、ERV-043（Evidence 合格）、
   ERV-047（假设来源）、ERV-052（文档块引用）、ERV-054/056（Phase 2 只读/结构化复用）、
   ERV-059—061（报告数字一致性）；Schema 校验覆盖 Claim/Evidence/Factor/Valuation/
   PeerSelection 全部对象；逐规则负例测试新增。
3. **BLOCKER 3 幂等键** → 改用文档 SHA-256 + 财务文件内容哈希 + 市场文件哈希 +
   真实 Provider 配置状态（is_provider_configured 读环境变量）。
4. **BLOCKER 4 估值财务期间** → 取 as_of 之前最新已披露期间事实（披露时间过滤），
   financial_period_end 记录真实期间，不再用 as_of 冒充。
5. **BLOCKER 5 未来信息防污染** → 财务披露时间用真实披露（文件 published_at 列或
   财报发布惯例，绝不用导入时刻/报告期末）；文档 published_at 取文件 mtime；
   Phase 2/3 查询与对象筛选统一 as_of 过滤；Validator 未来信息检查覆盖
   reports/evidences。
6. **BLOCKER 6 黄金案例缩减** → 恢复 25 类：10 端到端 + 17 模块级真实业务断言
   （周期/亏损/高负债/净现金/现金流恶化/应收存货/商誉/重组/非经常/来源冲突/
   管理层自述/估值 N/A/OCR 低置信/口径混用/金融企业/Phase 3 explained/unexplained/
   同行事后污染/真实 Claim/Evidence 对象）。
7. **HIGH 1 运行产物** → 补齐 30 个正式产物（task/entity_resolution/capability/
   document_index/document_blocks/financial_manifests/financial_quality/
   peer_candidates/competitive_factors/forecast_scenarios/contradictions/claims/
   evidence_index/final.md/errors.log 等），不存在模块写明确状态对象；运行目录改
   reports/runs/{task_id}。
8. **HIGH 2 run.json 旧状态** → 最终状态计算后再写 equity_research_run.json。
9. **HIGH 3 零数据 exit 3** → 缺失文件/全拒绝/无有效事实稳定返回 exit 3。
10. **HIGH 4 标准化/勾稽** → 现金流勾稽真实执行；normalizer 期间计算经指标链路接入。
11. **HIGH 5 预测** → forecast 模块真实接入（--include-forecast --scenario 生成
    forecast_scenarios.json）。

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
git status: clean（Phase 4 最终状态提交后）
分支: master
安装: 普通 pip 安装（非 editable，Windows 中文路径 + GBK locale 约束）
Python: 系统 3.12.10（本次验收实测解释器）
包名: research-os 0.1.0
```

> Phase 4 最终代码基线为 `4f7cdbd`；远端同步状态未查询。Phase 5 须等待正式任务书。
