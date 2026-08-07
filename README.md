# AI＋A股投研 Skill 系统

个人使用的 AI＋A 股投研系统。四层框架（需求场景层 / 功能模块层 / 数据采集层 /
知识库层）+ 横向工程控制面（任务编排、模型路由、数据契约、证据追踪、来源治理、
质量校验、失败降级、日志审计、版本控制、用户反馈闭环）。

完整规范见 [`docs/engineering-guide.md`](docs/engineering-guide.md)，
执行规则见 [`AGENTS.md`](AGENTS.md)。

## 当前状态

**Phase 0（项目骨架与契约）**：**PASS**。目录结构、30 Schema 前的 9 个核心 JSON Schema、
Python 数据模型、SQLite 初始化与迁移、`ResearchModule` / `CollectorAdapter` 抽象、
Orchestrator、CLI、运行目录与日志、Front Matter 校验器、单元与集成测试。

**Phase 0.1（控制面加固）**：**PASS**。模型-契约说明、CLI UUID 校验、任务失败状态持久化
（task.json/DB/validation.json 同步 failed + finished_at）、结构化 JSONL 错误记录
（含敏感字段过滤）。

**Phase 1（来源探测与数据底座）**：**PASS**。来源注册表（7 个来源已真实探测）、探测框架
（curl 引擎，证据最小化）、正式披露适配器（巨潮 API 已验证）、政府统计适配器
（统计局列表页）、行情候选（新浪报价）、新闻元数据候选（财联社 B 级）、
人工 Inbox、主备路由、健康检查。

**Phase 1.1（行情契约修正）**：**PASS**。实时快照与历史日线严格分离
（sina_quote 仅实时快照；日线 primary 空 + manual_import fallback）。

**Phase 2（信息筛选系统与每日晨报）**：**PASS（Evidence BLOCKER 已关闭）**。候选筛选流水线（窗口过滤→RawItem/Evidence→去重→
事件聚类（确定性第一版：实体+日期预分桶+标题相似度，语义模型未接入）→
分类→硬性否决→评分→Claim→选择→渲染→证据校验）、四个监测方向覆盖说明、
`research run morning-brief`（幂等/延迟补跑/force/dry-run）、报告验证器升级、
Hermes Skill（skills/finance/morning-brief）、Cron 文档（docs/operations/）、
黄金测试集（tests/golden/morning_brief）。模型路由诚实记录
（deterministic_fallback / llm_called: false）。

**Phase 3（异动分析）**：**PASS**（551 passed，独立验收结论 PHASE 3 PASS）。人工日线导入
（`research market-data import-daily`）、确定性异动检测（robust Z/severity/综合规则）、
基准选择（七维评分+防事后选择）、板块联动、分层事件检索+时间因果、原因候选七维评分、
统一 LLM Client（Fake Provider 全链路，未配置时诚实回退）、归因合成状态机
（UNEXPLAINED_MOVE 合法输出）、18 章节报告 + 33 条 Validator、
`research run abnormal-move`、Hermes Skill、14 黄金案例。Schema 19→30，迁移 user_version=4。

**Phase 4（个股研报）**：**工程基础 PASS；完整研究能力 PARTIAL_SUCCESS**（正式任务书见
[`docs/tasks/phase4-equity-research.md`](docs/tasks/phase4-equity-research.md)）。
离线优先、数据优先、证据可定位、财务可复算、结论可审计的 A 股个股研究档案与
Markdown 报告流水线：CSV/JSON/XLSX 财务导入（Manifest/行级校验/dry-run/幂等）、
财务标准化与 24 个确定性指标、三表勾稽与质量告警、业务分部、同行选择（防事后选择）、
估值观察（结构性禁止目标价）、情景预测（默认关闭）、38 章节研报、ERV-001—093
Validator、统一 Orchestrator 场景注册、共享预算的七项必需语义任务、真实
RawItem/Evidence 血缘、按 Provider 实际调用计数的 Flash/Pro 预算、任务级 Evidence
资格校验、分域来源质量、集中状态判定和维度级证据专业评审。未配置真实 Provider、自动财务源、
完整业务/竞争/风险/催化剂/反证覆盖时，报告必须降级，不得标完整 success。
Schema 30→51，迁移 user_version=5。
**Phase 5：BLOCKED**。完整 Phase 4 语义最低覆盖与全部准入条件满足前不得开始；
晚报/复盘、主题挖掘、首次覆盖和自动产业图谱入库均尚未开始。

## 快速开始

### 环境要求

- Python >= 3.11（开发验证于 3.12）
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip

### 安装

```powershell
# 项目根目录（含 schemas/ 与 src/）
cd ai-investment-research

# 方式一：pip（推荐）
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install ".[dev]"

# 方式二：uv（同样有效）
uv venv
uv pip install ".[dev]"
```

> **Windows 中文路径注意**：项目位于含中文的路径（如 `投研工作台`）且系统 locale 为
> GBK 时，**editable 安装（`-e`）存在已知坑**——setuptools/uv 以 UTF-8 写入 `.pth`
> 文件，而 Python 3.11 读 `.pth` 用 locale 编码（cp936），导致路径乱码、模块无法
> 导入。请使用普通安装（不带 `-e`）。代码修改后重装即可：
> `pip install ".[dev]"`。
>
> 开发迭代提示：`pytest` 通过 `pythonpath=src` 直接运行源码，不受安装方式影响；
> `scripts/*.py` 自带 `sys.path` 注入，也可直接运行。

### 初始化数据库

```powershell
python scripts/bootstrap.py
# 或等价的迁移工具
python scripts/migrate.py --status
```

### CLI 用法

```powershell
# 运行空任务（生成 Task、Plan 和 Run 目录；Phase 0 不采集数据）
research run --scenario morning_brief --entity 600519.SH --depth standard

# 指定 task_id（相同 ID 重复执行幂等：已完成后跳过，--force 重建）
research run --task-id <uuid> --scenario abnormal_move_analysis

# 校验报告 Front Matter（缺少必需字段即失败）
research validate --report reports/morning/2026/2026-08/2026-08-05_morning.md

# 校验全部 JSON Schema
research validate
research validate --schemas

# 来源探测（Phase 1：真实 HTTP 探测；无参数时仅列出已登记规格，不联网）
research probe-sources
research probe-sources --all
research probe-sources --source cninfo
research probe-sources --group official
research probe-sources --output data/source_probes/ --no-write

# 来源健康检查（可达性/结构探测）
research health
research health --source cninfo

# 人工 Inbox（用户放入链接/标题/摘要，不自动进入知识图谱）
research inbox add --name 雪球 --url https://xueqiu.com/xxx --title 标题 --excerpt 摘录
research inbox list [--status submitted]
research inbox status <inbox_id> needs_review
```

### 运行测试

```powershell
python -m pytest
```

## 目录结构

```text
ai-investment-research/
├── AGENTS.md               # 不可违反的研究与工程规则
├── docs/engineering-guide.md
├── config/                 # app / model_routing / schedules / source_policy / report_policy / knowledge_policy
├── schemas/                # 9 个核心 JSON Schema（权威数据契约）
├── registry/               # 来源注册表（sources / source_groups / changelog）
├── src/research_os/
│   ├── cli/                # research 命令
│   ├── orchestrator/       # Orchestrator + 运行目录
│   ├── routing/            # 模型路由（占位）
│   ├── collectors/         # CollectorAdapter + stub（Phase 1 实现真实适配器）
│   ├── normalizers/        # 标准化（Phase 1+）
│   ├── modules/            # ResearchModule 抽象（P0-P2 模块清单见指南 12 节）
│   ├── evidence/           # 证据管理（Phase 2+）
│   ├── knowledge/          # 知识库（Phase 5+）
│   ├── reports/            # Front Matter 校验器 + 基础报告校验器
│   ├── storage/            # SQLite + 版本化迁移
│   ├── validators/         # Schema 校验器
│   └── utils/              # 时间 / ID / 日志
├── reports/runs/{task_id}/ # 每次运行：task.json plan.json retrieval_log.jsonl
│                           #   module_results/ evidence_index.json validation.json final.md errors.log
├── tests/                  # unit / integration / contracts / golden / source_health / fixtures
└── scripts/                # bootstrap / probe_sources / run_scenario / validate_report / rebuild_graph / migrate
```

## 数据契约

核心对象（Task / Entity / RawItem / Event / Opinion / Claim / Evidence /
ModuleResult / GraphChange）定义于 `schemas/*.schema.json`，Python 实现位于
`src/research_os/models/`。所有对象必须通过对应 Schema 校验：
确定性逻辑（Schema 校验）使用代码实现，不交给 LLM。

当前 **51 个 Schema**（Phase 0：9 / Phase 1：4 / Phase 1.1：2 / Phase 2：4 /
Phase 3：11 / Phase 4：20 / Phase 4.1：1）。Schema 校验：`research validate`。

## 输出边界

本系统**不输出**目标价、买卖评级、仓位建议或任何交易建议。
报告中的关键结论必须可映射到带证据的 Claim。
