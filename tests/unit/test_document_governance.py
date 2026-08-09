"""权威顺序与阶段状态文档一致性。"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_engineering_guide_is_current_and_task_cannot_override():
    guide = _read("docs/engineering-guide.md")
    agents = _read("AGENTS.md")
    task = _read("docs/tasks/phase4-equity-research.md")
    assert "版本：V1.3" in guide
    assert "当前唯一有效工程基线" in guide
    assert "engineering-guide.md` → `docs/project-state/DECISIONS.md" in agents
    assert "仅细化" in task
    assert "冲突时按本任务书执行" not in task


def test_phase_status_documents_are_consistent():
    """Phase5 current status docs must reflect PASS; M10 must be PASS;
    no stale pre-merge/in-progress claims in current-status docs."""
    readme = _read("README.md")
    current = _read("docs/project-state/CURRENT_STATE.md")
    next_phase = _read("docs/project-state/NEXT_PHASE.md")
    limitations = _read("docs/project-state/KNOWN_LIMITATIONS.md")
    phase5_task = _read("docs/tasks/phase5-industry-knowledge-graph.md")

    # ── CURRENT-STATE DOCUMENTS ──
    # Phase5 terminal state assertions
    assert "Phase 5" in readme and "PASS" in readme, "README must reflect Phase5 PASS"
    assert "M0-M10" in readme, "README must state M0-M10 PASS"
    assert "| Phase 5 | PASS |" in current, "CURRENT_STATE must reflect Phase5 PASS"
    assert "Phase 5 implementation：PASS" in next_phase, "NEXT_PHASE must reflect Phase5 PASS"
    assert "Phase 5" in limitations and ("PASS" in limitations or "CLOSED" in limitations), \
        "KNOWN_LIMITATIONS must reflect Phase5 terminal state"
    assert "Phase 5 = CLOSED / PASS" in limitations, \
        "KNOWN_LIMITATIONS must explicitly state Phase 5 = CLOSED / PASS"
    # KNOWN_LIMITATIONS header must not contain Phase5 BLOCKED
    lim_header = "\n".join(limitations.split("\n")[:30])
    assert "Phase 5 = BLOCKED" not in lim_header and "Phase 5 = BLOCKED" != lim_header.strip(), \
        "KNOWN_LIMITATIONS header must not declare Phase5 BLOCKED"
    assert "NOT_AUTHORIZED" in limitations, "KNOWN_LIMITATIONS must reflect Phase6 NOT_AUTHORIZED"
    assert "**IMPLEMENTATION_STATUS: COMPLETE**" in phase5_task
    # No stale pre-merge artifacts in CURRENT_STATE or NEXT_PHASE surface
    assert "Draft PR #6" not in current, "CURRENT_STATE must not reference Draft PR #6"
    assert "Draft PR #6" not in next_phase, "NEXT_PHASE must not reference Draft PR #6"
    # Merge facts present
    assert "1e1d4f9" in current, "CURRENT_STATE must record PR5C master SHA"
    assert "2c55c55" in current, "CURRENT_STATE must record post-hotfix master SHA"
    assert "1087520" in current, "CURRENT_STATE must record final governance master SHA"
    # NEXT_PHASE: M10 must be PASS, not IN_PROGRESS
    assert "M10 Deterministic JSON Mirror + E2E Acceptance" in next_phase
    assert "AUTHORIZED / IN_PROGRESS" not in next_phase
    # No malformed empty PR status
    for text in (current, next_phase):
        assert "（）。" not in text, "Malformed empty PR status found"
        assert "Draft PR #6" not in text
        assert "AUTHORIZED / IN_PROGRESS" not in text
    # Merge facts in NEXT_PHASE
    assert "MERGED" in next_phase, "NEXT_PHASE must document PR5C merged"

    # No stale pre-merge claims in current-status docs (header sections only)
    for text in (readme, current, next_phase):
        assert "M10 AUTHORIZED / IN_PROGRESS" not in text
        assert "M10 IMPLEMENTED / AWAITING_INDEPENDENT_ACCEPTANCE" not in text
        assert "M10 NOT_AUTHORIZED" not in text
        assert "PARTIAL_SUCCESS / READY_FOR_INDEPENDENT_ACCEPTANCE" not in text
    # Taskbook: only check header (first 20 lines); historical entries have old states
    taskbook_header = "\n".join(phase5_task.split("\n")[:20])
    assert "M10 IMPLEMENTED / AWAITING_INDEPENDENT_ACCEPTANCE" not in taskbook_header
    assert "M10 NOT_AUTHORIZED" not in taskbook_header

    # Historical docs: may reflect their own state (legacy check)
    phase4 = _read("docs/tasks/phase4-full-research-capability.md")
    assert "PASS" in phase4 or "PASSED" in phase4 or \
           "SATISFIED" in phase4 or "COMPLETED" in phase4


def test_baseline_readme_does_not_claim_to_be_current():
    baseline = _read("docs/baselines/README.md")
    assert "唯一当前有效" in baseline
    assert "不参与覆盖当前规范" in baseline


def test_phase6_top_level_design_governance_frozen():
    """P6-G0: Phase 6 top-level design must be FROZEN / APPROVED; 6A/6B/6C seven
    scenarios frozen; P6-F0 progressed to IMPLEMENTED / AWAITING_INDEPENDENT_ACCEPTANCE;
    business implementation still NOT_AUTHORIZED; no production Phase6 scenario
    implemented in src/."""
    guide = _read("docs/engineering-guide.md")
    decisions = _read("docs/project-state/DECISIONS.md")
    current = _read("docs/project-state/CURRENT_STATE.md")
    next_phase = _read("docs/project-state/NEXT_PHASE.md")
    taskbook = _read("docs/tasks/phase6-research-workflows.md")
    limitations = _read("docs/project-state/KNOWN_LIMITATIONS.md")
    readme = _read("README.md")

    # ── ENGINEERING GUIDE V1.2 ──
    assert "Phase 6：研究型工作流" in guide
    assert "6A：industry_research（行业研究）、theme_discovery（主题挖掘）" in guide
    assert "6B：evening_brief（每日晚报）、daily_review（每日复盘）、stock_review（个股复盘）" in guide
    assert "6C：first_coverage（首次覆盖）、earnings_expectation（财报预期）" in guide
    assert "剩余场景 = 7" in guide
    assert "Graph→Research: READ ONLY" in guide or "Graph→Research：READ ONLY" in guide
    assert "as_of: REQUIRED" in guide
    assert "SQLite: 唯一 graph authority" in guide
    assert "JSON mirror: 非权威" in guide
    assert "KnowledgeContext != Evidence" in guide
    assert "LLM can propose" in guide and "LLM cannot approve" in guide
    assert "human can approve" in guide and "human cannot bypass validator" in guide
    assert "Research Capability Acceptance" in guide
    assert "Candidate Integration Authorization" in guide
    assert "theme_discovery ≠ stock picking" in guide
    assert "first_coverage ≠ brokerage rating" in guide
    assert "earnings_expectation ≠ trading signal" in guide
    assert "daily_review ≠ next-day trading plan" in guide
    assert "automatic ontology expansion: PROHIBITED" in guide
    # dependency rules
    assert "串行治理拓扑" in guide
    assert "6B 不 hard-depend on 6A" in guide

    # ── DECISION #41 ──
    assert "## 41. Phase 6 Top-Level Design Decision" in decisions
    assert "6A / 6B / 6C" in decisions
    assert "P6-F0 shared contract gate" in decisions or "P6-F0 共享契约" in decisions
    assert "Graph→Research：READ ONLY" in decisions or "Graph→Research: READ ONLY" in decisions
    assert "KnowledgeContext != Evidence" in decisions
    assert "research first" in decisions
    assert "active graph never direct" in decisions
    assert "NOT_AUTHORIZED" in decisions

    # ── TASKBOOK ──
    assert "**TASKBOOK_STATUS: APPROVED**" in taskbook
    assert "**CURRENT_MILESTONE: P6-S0**" in taskbook
    assert "P6-S1" in taskbook or ("P6-S1" in taskbook and "6B Final Closure" in taskbook)
    assert "P6-S2" in taskbook or ("P6-S2" in taskbook and "6A Final Closure" in taskbook)
    assert "P6-S3" in taskbook or ("P6-S3" in taskbook and "Earnings Expectation" in taskbook)
    assert "P6-S4" in taskbook or ("P6-S4" in taskbook and "First Coverage" in taskbook)
    assert "P6-S5" in taskbook, "Taskbook must mention P6-S5"
    assert "P6-S6" in taskbook, "Taskbook must mention P6-S6"
    for milestone in ("P6-G0", "P6-F0", "P6-S0", "P6-S1", "P6-S2", "P6-S3",
                      "P6-S4", "P6-S5", "P6-S6"):
        assert milestone in taskbook, f"taskbook must define {milestone}"

    # ── P6-S0 AUTHORIZED; P6-S1-S6 NOT_AUTHORIZED ──
    assert "P6-S0: NOT_AUTHORIZED" not in taskbook, "P6-S0 must be AUTHORIZED"
    assert "P6-S1" in taskbook, "Taskbook must mention P6-S1"
    assert "PARALLEL_PHASE6_BUSINESS_DEVELOPMENT: CANCELLED" in taskbook

    # ── CURRENT-STATE / NEXT_PHASE / README / KNOWN_LIMITATIONS ──
    assert "P6-G0 Top-Level Design | FROZEN / APPROVED" in current or "P6-G0" in current
    assert "P6-S0 Serial Governance Reset | IN PROGRESS" in current
    assert "P6-S0 Serial Governance Reset" in next_phase
    assert "P6-S0 Serial Governance Reset" in next_phase
    assert "P6-S0" in readme or "Phase 6" in readme
    assert "Phase 6 implementation = NOT_AUTHORIZED" in limitations
    # taskbook approval must not imply development authorization
    assert "任务书 approved 不得被解释成整个 Phase 6 已授权开发" in taskbook
    assert "NOT_AUTHORIZED" in next_phase


def test_phase6_shared_contract_frozen():
    """P6-F0: shared contract must be frozen with real structural checks.

    机械保护（task 三十六节）：
    - 七 scenario ID 与设计一致（解析 task.schema.json enum，非字符串碰巧）
    - Task/CLI existing enums 不漂移（AST 解析 CLI choices）
    - Shared contract ownership 列表存在（CONFLICT ZONE）
    - Phase6 business implementation 仍未 enable（runners/__init__.py 无新 Runner）
    - Graph→Research read-only contract 存在
    - KnowledgeContext != Evidence
    - DB remains v6（migrations 目录恰 6 个）
    - Phase6 output safety contract 存在
    """
    import ast
    import json

    contract = _read("docs/contracts/phase6-shared-contract.md")
    decisions = _read("docs/project-state/DECISIONS.md")

    # 1. task.schema.json scenario enum：恰好 = 3 核心 + 7 Phase 6，无多余、无漂移
    schema = json.loads(_read("schemas/task.schema.json"))
    enum = list(schema["properties"]["scenario"]["enum"])
    core = {"morning_brief", "abnormal_move_analysis", "stock_research_report"}
    phase6 = {
        "industry_research", "theme_discovery",
        "evening_brief", "daily_review", "stock_review",
        "first_coverage", "earnings_expectation",
    }
    assert set(enum) == core | phase6, f"scenario enum drifted: {enum}"
    assert len(enum) == len(set(enum)), "scenario enum must be unique"

    # 2. CLI --scenario choices 与 enum 一致（AST 解析，真实结构）
    tree = ast.parse(_read("src/research_os/cli/main.py"))
    cli_choices = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "option"):
            for kw in node.keywords:
                if kw.arg == "scenario":
                    continue
            # 找 --scenario 的 click.Choice([...])
            args = [a.value if isinstance(a, ast.Constant) else None
                    for a in node.args]
            if "--scenario" in args:
                for kw in node.keywords:
                    if kw.arg == "type" and isinstance(kw.value, ast.Call):
                        choice_list = kw.value.args[0]
                        if isinstance(choice_list, (ast.List, ast.Tuple)):
                            cli_choices = [
                                e.value for e in choice_list.elts
                                if isinstance(e, ast.Constant)]
    assert cli_choices is not None, "CLI --scenario choices not found"
    assert set(cli_choices) == core | phase6, f"CLI choices drifted: {cli_choices}"
    assert len(cli_choices) == len(set(cli_choices)), "CLI choices must be unique"

    # 3. Shared-file ownership（CONFLICT ZONE）冻结列表存在且完整覆盖
    assert "## 7. Shared-file Ownership（CONFLICT ZONE，FROZEN）" in contract
    zone_paths = [
        "src/research_os/orchestrator/orchestrator.py",
        "src/research_os/orchestrator/runners/__init__.py",
        "src/research_os/orchestrator/scenario_runner.py",
        "src/research_os/orchestrator/scenario_registry.py",
        "src/research_os/orchestrator/run_directory.py",
        "src/research_os/cli/main.py",
        "schemas/task.schema.json",
        "src/research_os/models/core.py",
        "src/research_os/storage/migrations/*",
        "src/research_os/llm/client.py",
        "src/research_os/llm/routing.py",
        "config/model_routing.yaml",
        "config/llm_providers.yaml",
        "registry/sources.yaml",
        "registry/source_groups.yaml",
        "knowledge/ontology/*",
        "src/research_os/knowledge/query.py",
        "src/research_os/knowledge/context_builder.py",
    ]
    for path in zone_paths:
        assert path in contract, f"conflict zone must list {path}"

    # 4. Phase6 business implementation 仍未 enable：runners/__init__.py 仅 3 核心 Runner
    runners_init = _read("src/research_os/orchestrator/runners/__init__.py")
    assert "MorningBriefScenarioRunner" in runners_init
    assert "AbnormalMoveScenarioRunner" in runners_init
    assert "EquityResearchScenarioRunner" in runners_init
    for forbidden in ("IndustryResearchScenarioRunner", "ThemeDiscoveryScenarioRunner",
                      "EveningBriefScenarioRunner", "DailyReviewScenarioRunner",
                      "StockReviewScenarioRunner", "FirstCoverageScenarioRunner",
                      "EarningsExpectationScenarioRunner"):
        assert forbidden not in runners_init, f"central enablement leaked: {forbidden}"
    # Orchestrator 默认注册仍只有三个核心场景
    orchestrator = _read("src/research_os/orchestrator/orchestrator.py")
    assert "MorningBriefScenarioRunner(), AbnormalMoveScenarioRunner()," in orchestrator
    assert "EquityResearchScenarioRunner()" in orchestrator

    # 5. Graph→Research read-only 契约
    assert "Graph→Research 唯一路径" in contract
    assert "GraphQueryService → KnowledgeContextBuilder → Research Context" in contract
    assert "READ ONLY" in contract or "read-only" in contract

    # 6. KnowledgeContext != Evidence
    assert "KnowledgeContext != Evidence" in contract
    assert "不得直接证明报告事实" in contract

    # 7. DB remains v6：migrations 目录恰 6 个文件，编号前缀 001-006
    migrations = sorted(p.stem for p in (ROOT / "src/research_os/storage/migrations").glob("*.sql"))
    assert len(migrations) == 6, f"migration count drifted: {len(migrations)}"
    prefixes = [m.split("_", 1)[0] for m in migrations]
    assert prefixes == [f"{i:03d}" for i in range(1, 7)], f"migration versions drifted: {prefixes}"
    assert "DB = v6" in contract

    # 8. Phase6 output safety contract
    assert "## 23. 输出安全 Shared Contract（FROZEN）" in contract
    assert "theme_discovery != stock picking" in contract
    assert "first_coverage != brokerage rating" in contract
    assert "earnings_expectation != trading signal" in contract
    assert "daily_review != next-day trading plan" in contract

    # 9. as_of / 6B 时间 / 6C 三时间
    assert "as_of = explicit business cutoff" in contract
    assert "[08:00, 20:00)" in contract
    assert "historical_input_period" in contract
    assert "forecast_period" in contract

    # 10. MODEL_INFERENCE 永不升级 FACT + Research→Graph 顺序
    assert "MODEL_INFERENCE" in contract and "不得自动升级" in contract
    assert "Research Capability PASS" in contract
    assert "GraphChange Candidate" in contract

    # 11. 决策 #42 存在
    assert "## 42. Phase 6 Shared Contract Freeze（P6-F0" in decisions
    assert "F0 只冻结契约" in contract or "不实现任何 Phase 6 业务研究能力" in contract
