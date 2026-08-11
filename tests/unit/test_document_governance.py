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
    assert "版本：V1.5" in guide
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
    assert "Phase 6 Research→GraphChange Candidate integration = DEFERRED" in limitations, \
        "KNOWN_LIMITATIONS must preserve the deferred Phase6 candidate boundary"
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
    """P6-G0/F0 design rules remain frozen after the Phase6 terminal closeout."""
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
    assert "TASKBOOK_STATUS: EXECUTED" in taskbook
    assert "**CURRENT_MILESTONE: P6-S6 GOVERNANCE CLOSEOUT**" in taskbook
    assert "P6-S1" in taskbook or ("P6-S1" in taskbook and "6B Final Closure" in taskbook)
    assert "P6-S2" in taskbook or ("P6-S2" in taskbook and "6A Final Closure" in taskbook)
    assert "P6-S3" in taskbook or ("P6-S3" in taskbook and "Earnings Expectation" in taskbook)
    assert "P6-S4" in taskbook or ("P6-S4" in taskbook and "First Coverage" in taskbook)
    assert "P6-S5" in taskbook, "Taskbook must mention P6-S5"
    assert "P6-S6" in taskbook, "Taskbook must mention P6-S6"
    for milestone in ("P6-G0", "P6-F0", "P6-S0", "P6-S1", "P6-S2", "P6-S3",
                      "P6-S4", "P6-S5", "P6-S6"):
        assert milestone in taskbook, f"taskbook must define {milestone}"

    # ── Serial milestones completed; candidate integration remains deferred ──
    for milestone in ("P6-S0", "P6-S1", "P6-S2", "P6-S3", "P6-S4", "P6-S5"):
        assert f"{milestone}: PASS / MERGED" in taskbook
    assert "P6-S6: GOVERNANCE CLOSEOUT" in taskbook
    assert "CANDIDATE INTEGRATION: DEFERRED" in taskbook
    assert "PARALLEL_PHASE6_BUSINESS_DEVELOPMENT: CANCELLED" in taskbook

    # ── CURRENT-STATE / NEXT_PHASE / README / KNOWN_LIMITATIONS ──
    assert "P6-G0 Top-Level Design | PASS / MERGED" in current
    assert "P6-S0 Serial Governance Reset | PASS / MERGED" in current
    assert "Phase 6 terminal state and current limited authorization" in next_phase
    assert "Phase 6：PASS / CENTRALLY ENABLED" in readme
    assert "Phase 6 research workflows = PASS / centrally enabled" in limitations
    # taskbook completion must not imply candidate or future-phase authorization
    assert "Research capability completion != Research→GraphChange Candidate authorization" in taskbook
    assert "NOT_AUTHORIZED" in next_phase

    # ── DECISION #43, #44 ──
    assert "## 43. Evening Brief Design Correction" in decisions
    assert "## 44. Phase 6 Serial Recovery" in decisions

    # ── V1.3 propagation ──
    assert "V1.3" in guide
    contract = _read("docs/contracts/phase6-shared-contract.md")
    assert "V1.3" in contract
    assert "V1.3" in current

    # ── P6-S5 enablement, not P6-I0 ──
    assert "P6-I0" not in taskbook
    # P6-I0 should not appear in new decisions (#43+#44)
    decisions_43_44 = decisions[decisions.find("## 43."):] if "## 43." in decisions else ""
    assert "P6-I0" not in decisions_43_44, "P6-I0 must not appear in new serial decisions"


def test_phase6_terminal_governance_closeout():
    """P6-S6 living surfaces agree on terminal state without rewriting history."""
    decisions = _read("docs/project-state/DECISIONS.md")
    current = _read("docs/project-state/CURRENT_STATE.md")
    next_phase = _read("docs/project-state/NEXT_PHASE.md")
    limitations = _read("docs/project-state/KNOWN_LIMITATIONS.md")
    guide = _read("docs/engineering-guide.md")
    contract = _read("docs/contracts/phase6-shared-contract.md")
    taskbook = _read("docs/tasks/phase6-research-workflows.md")
    readme = _read("README.md")

    decision_45 = decisions[decisions.index("## 45. Phase 6 Terminal Closeout"):]
    assert "PHASE6: CLOSED / PASS" in decision_45
    assert "PHASE6_ACCEPTED_CODE_MASTER_SHA: 3e0166de11ae9969792a4726913cb68a17c8f2a5" in decision_45
    assert "PHASE6_RESEARCH_TO_GRAPHCHANGE_CANDIDATE: DEFERRED" in decision_45
    for number in range(41, 45):
        assert f"## {number}." in decisions, f"historical Decision #{number} must be preserved"

    current_phase6 = current[current.index("## Phase 6"):]
    readme_phase6 = readme[readme.index("## Phase 6"):readme.index("## 快速开始")]
    limitations_header = "\n".join(limitations.splitlines()[:24])
    next_phase6 = next_phase[next_phase.index("## Phase 6 terminal state"):]
    guide_gate = guide[guide.index("### 69.11 实施门禁"):guide.index("# 第十八部分")]
    taskbook_header = "\n".join(taskbook.splitlines()[:20])
    historical_start = taskbook.index("## 2. Phase 6 启动时工程库存（Historical Snapshot）")
    historical_end = taskbook.index("\n---", historical_start)
    historical_snapshot = taskbook[historical_start:historical_end]

    assert "Phase 6：CLOSED / PASS" in current
    assert "P6-S6 Governance Closeout | GOVERNANCE CLOSEOUT" in current_phase6
    assert "Phase 6 business implementation | NOT_AUTHORIZED" not in current_phase6
    assert "P6-S0 Serial Governance Reset | IN PROGRESS" not in current_phase6
    assert "Phase6 business code on master: NONE" not in current_phase6
    assert "Serial milestone gating: ACTIVE (P6-S0 only)" not in current_phase6

    assert "CURRENT ENGINEERING MILESTONE**: P7-D0 Unified Data Layer Contracts" in next_phase6
    assert "Phase 6.1 Research→GraphChange Candidate Integration**: DEFERRED / NOT_AUTHORIZED" in next_phase6
    assert "Phase 7**: D0 CLOSED / PASS" in next_phase6
    assert "P7-UX1**: CLOSED / PASS / INDEPENDENTLY ACCEPTED" in next_phase6
    assert "Current authorized milestone" not in next_phase6

    assert "Phase 6 research workflows = PASS / centrally enabled" in limitations_header
    assert "Graph→Research = read-only Phase 6A path enabled" in limitations_header
    assert "Phase 6 implementation = NOT_AUTHORIZED" not in limitations_header
    assert "Graph→Research production integration: NOT YET ENABLED" not in limitations_header

    assert "IMPLEMENTATION_STATUS: PASS" in guide_gate
    assert "P6-S6: GOVERNANCE CLOSEOUT" in guide_gate
    assert "PHASE6_CANDIDATE_INTEGRATION: DEFERRED" in guide_gate
    assert "IMPLEMENTATION_STATUS: NOT_STARTED" not in guide_gate
    assert "CURRENT_MILESTONE: P6-G0" not in guide_gate

    assert "PHASE6_RESEARCH: PASS" in contract
    assert "CENTRAL_ENABLEMENT: PASS" in contract
    assert "PHASE6_RESEARCH_TO_GRAPHCHANGE_CANDIDATE: DEFERRED" in contract
    assert "TASKBOOK_STATUS: EXECUTED" in taskbook_header
    assert "CURRENT_MILESTONE: P6-S6 GOVERNANCE CLOSEOUT" in taskbook_header
    assert "## 2. 当前真实工程库存" not in taskbook
    assert "HISTORICAL SNAPSHOT / NOT CURRENT STATE" in historical_snapshot
    assert "e98f5ed" in historical_snapshot
    assert "Phase6 production business code: NONE" in historical_snapshot
    assert "earnings_expectation: NOT_IMPLEMENTED" in historical_snapshot
    assert "first_coverage: NOT_IMPLEMENTED" in historical_snapshot

    assert "Phase 6：PASS / CENTRALLY ENABLED" in readme_phase6
    assert "USER_TRIAL_READY：YES" in readme_phase6
    assert "P6-S0 Serial Governance Reset" not in readme_phase6
    schema_count = len(list((ROOT / "schemas").glob("*.schema.json")))
    assert schema_count > 0
    assert f"当前 **{schema_count} 个 Schema**" in readme
    assert f"Schemas: {schema_count}" in current_phase6
    assert "DB: v6" in current_phase6


def test_phase7_ux1_governance_is_consistent_and_independently_accepted():
    """P7-UX1 living surfaces agree on terminal state after independent acceptance."""
    decisions = _read("docs/project-state/DECISIONS.md")
    taskbook = _read("docs/tasks/phase7-conversational-research-ux.md")
    current = _read("docs/project-state/CURRENT_STATE.md")
    next_phase = _read("docs/project-state/NEXT_PHASE.md")
    limitations = _read("docs/project-state/KNOWN_LIMITATIONS.md")
    guide = _read("docs/engineering-guide.md")
    readme = _read("README.md")

    decision_46 = decisions[decisions.index(
        "## 46. Schema-Driven Conversational Research Gateway"
    ):]
    for required in (
        "Public Request Draft", "Formal Persisted Request", "Orchestrator.execute()",
        "LLM_WRITABLE / USER_SEMANTIC", "AUTHORITATIVE_RESOLVED", "SYSTEM_CONTROLLED",
        "route <= 1 Flash", "total <= 2 Flash", "Pro = 0", "DB: v6 / unchanged",
        "PHASE6.1: NOT_AUTHORIZED", "P7 DATA ACQUISITION: NOT_STARTED",
    ):
        assert required in decision_46
    # 46.7 records independent acceptance / terminal status; 46.8 keeps boundaries.
    assert "### 46.7 Independent Acceptance and Terminal Status" in decision_46
    assert "P7-UX1: PASS / INDEPENDENTLY ACCEPTED" in decision_46
    assert "### 46.8 Terminal Boundary" in decision_46
    for kept in (
        "DATA_ACQUISITION_CHANGED: NO", "COLLECTORS_CHANGED: NO",
        "SOURCE_REGISTRY_CHANGED: NO", "GRAPH_WRITE: NONE", "PHASE6_1: NOT_AUTHORIZED",
        "DB: v6", "MIGRATIONS: NONE", "SCHEMAS: 80",
    ):
        assert kept in decision_46

    header = "\n".join(taskbook.splitlines()[:30])
    assert "TASKBOOK_STATUS: PASS / INDEPENDENTLY ACCEPTED" in header
    assert "P7 DATA ACQUISITION: NOT_STARTED" in header
    for kept in (
        "DATA_ACQUISITION_CHANGED: NO", "COLLECTORS_CHANGED: NO",
        "SOURCE_REGISTRY_CHANGED: NO", "GRAPH_WRITE: NONE",
        "DB: v6", "MIGRATIONS: NONE", "SCHEMAS: 80",
    ):
        assert kept in header

    for surface in (current, next_phase, limitations, guide, readme):
        assert "PASS / INDEPENDENTLY ACCEPTED" in surface
        assert "Phase 6.1" in surface or "PHASE6.1" in surface
    assert "P7 DATA ACQUISITION: NOT_STARTED" in current
    assert "P7 DATA ACQUISITION**: NOT_STARTED" in next_phase
    assert "P7 DATA ACQUISITION = NOT_STARTED" in limitations
    assert "P7 DATA ACQUISITION: NOT_STARTED" in guide
    assert "仍为 `NOT_STARTED`" in readme

    schema_count = len(list((ROOT / "schemas").glob("*.schema.json")))
    assert schema_count == 85
    assert f"Current registry after P7-UX1 implementation: Schemas: 80" in current
    assert f"Current registry after P7-D0 contracts: Schemas: {schema_count}" in current
    assert f"Current Schema registry**: {schema_count}" in next_phase
    assert f"当前 Schema registry 为 **{schema_count}**" in readme
    assert "DB: v6" in current and "migrations: NONE" in current
    assert "SCHEMAS: 85" in current

    # Decision #45's 69-schema terminal snapshot remains historical and explicitly labelled.
    decision_45 = decisions[decisions.index("## 45. Phase 6 Terminal Closeout"):
                            decisions.index("## 46. Schema-Driven Conversational Research Gateway")]
    assert "SCHEMA_REGISTRY: 69" in decision_45
    assert "Historical Phase 6 terminal snapshot: Schemas: 69" in current
    assert "Phase 6 terminal historical snapshot：Schema 69" in readme


def test_p7_d0_governance_is_consistent():
    """P7-D0 living surfaces agree on PASS / INDEPENDENTLY ACCEPTED."""
    decisions = _read("docs/project-state/DECISIONS.md")
    taskbook = _read("docs/tasks/phase7-data-layer-d0.md")
    current = _read("docs/project-state/CURRENT_STATE.md")
    next_phase = _read("docs/project-state/NEXT_PHASE.md")
    limitations = _read("docs/project-state/KNOWN_LIMITATIONS.md")
    guide = _read("docs/engineering-guide.md")
    readme = _read("README.md")
    gc_taskbook = _read("docs/tasks/phase7-data-layer-d0-governance-closeout.md")

    decision_47 = decisions[decisions.index("## 47. P7-D0 Unified Data Layer Contracts"):]
    assert "BRIEF_A: NEW EVENT DISCOVERY" in decision_47
    assert "BRIEF_C: CURRENT-WINDOW ATTENTION MONITORING" in decision_47
    assert "FAST_NEWS ∈ A" in decision_47
    assert "FAST_NEWS ∉ C" in decision_47
    assert "CONTINUOUS_MONITORING: NO" in decision_47
    assert "HEAT_HISTORY: NO" in decision_47
    assert "RANK_CHANGE: NO" in decision_47
    assert "VELOCITY: NO" in decision_47
    assert "SCENARIO_DECLARES_SOURCE: NO" in decision_47
    assert "SECOND_ROUTER: NO" in decision_47
    assert "READINESS_NETWORK_ACCESS: NO" in decision_47
    assert "LLM_DATA_AUTHORITY: NO" in decision_47
    assert "ACQUISITION_PLAN_SELECTED_SOURCE: NO" in decision_47
    assert "P7-D1: NOT AUTHORIZED" in decision_47
    assert "SCHEMAS: 85" in decision_47
    # 47.8 / 47.9：独立验收 + terminal boundary
    assert "### 47.8 Independent Acceptance" in decision_47
    assert "### 47.9 Terminal Boundary" in decision_47
    assert "INDEPENDENT_ACCEPTANCE: PASS" in decision_47
    assert "P7-D0: PASS / INDEPENDENTLY ACCEPTED" in decision_47
    assert "d06d8d714958f58d44fb130f8fb30a3aff7e4a7a" in decision_47

    header = "\n".join(taskbook.splitlines()[:20])
    assert "TASKBOOK_STATUS: IMPLEMENTATION AUTHORIZED" in header
    assert "MILESTONE: P7-D0" in header
    assert "P7-D1 NOT AUTHORIZED" in header
    assert "EXPECTED_SCHEMA_COUNT: 85" in header
    # terminal record 追加，不改写原始授权内容
    assert "IMPLEMENTATION: PASS / INDEPENDENTLY ACCEPTED" in taskbook
    assert "d06d8d714958f58d44fb130f8fb30a3aff7e4a7a" in taskbook

    assert "P7-D0：PASS / INDEPENDENTLY ACCEPTED" in current
    assert "PASS / INDEPENDENTLY ACCEPTED" in next_phase
    assert "P7-D0 = PASS / INDEPENDENTLY ACCEPTED" in limitations
    assert "PASS / INDEPENDENTLY ACCEPTED" in readme
    assert "版本：V1.5" in guide
    assert "P7 Unified Data Layer" in guide or "P7-D0" in guide
    assert "SCHEMAS: 85" in current
    # accepted implementation head 必须明确
    assert "d06d8d714958f58d44fb130f8fb30a3aff7e4a7a" in current
    # P7-D1 仍 NOT AUTHORIZED（eligible ≠ authorized）
    assert "P7-D1" in next_phase and "NOT AUTHORIZED" in next_phase
    assert "NEXT ELIGIBLE MILESTONE" in next_phase
    assert "P7-D1 IN_PROGRESS" not in next_phase
    assert "P7 DATA ACQUISITION STARTED" not in next_phase
    # governance closeout taskbook 存在
    assert "P7-D0-GC" in gc_taskbook
    assert "START_HEAD" in gc_taskbook and "d06d8d7" in gc_taskbook
    assert "SCOPE: governance-only" in gc_taskbook

    schema_count = len(list((ROOT / "schemas").glob("*.schema.json")))
    assert schema_count == 85
    assert f"Current registry after P7-D0 contracts: Schemas: {schema_count}" in current


def test_p7_d0_r1_governance():
    """P7-D0-R1：contract strictness + governance closure 已反映到治理面。"""
    decisions = _read("docs/project-state/DECISIONS.md")
    guide = _read("docs/engineering-guide.md")
    current = _read("docs/project-state/CURRENT_STATE.md")
    next_phase = _read("docs/project-state/NEXT_PHASE.md")
    limitations = _read("docs/project-state/KNOWN_LIMITATIONS.md")
    r1_taskbook = _read("docs/tasks/phase7-data-layer-d0-r1.md")

    # R1-06：Router 措辞收口——不再永久禁止现有 Router 后续演化
    assert "P7_D0_ROUTER_EVOLUTION: NONE" in decisions
    assert "EXISTING_ROUTER_FUTURE_EVOLUTION: ONLY UNDER SEPARATE MILESTONE AUTHORIZATION" in decisions
    assert "SECOND_ROUTER: NO" in decisions
    assert "不得创建并行的第二套路由控制面" in decisions
    # 工程指南不再出现"永久禁止 Router v2"绝对措辞
    assert "只允许演化现有 Router" not in guide
    assert "SECOND_SOURCE_ROUTER: PROHIBITED" in guide
    assert "P7-D0 不实施 Router 演化" in guide

    # R1 taskbook 版本化记录 + terminal record
    assert "TASKBOOK_STATUS" in r1_taskbook or "P7-D0-R1" in r1_taskbook
    assert "1048904" in r1_taskbook or "10489041efbc8e7dc5507fb48101230996b67535" in r1_taskbook
    assert "P7-D1" in r1_taskbook and "NOT AUTHORIZED" in r1_taskbook
    assert "R1: PASS" in r1_taskbook
    assert "INDEPENDENT_RE_ACCEPTANCE: PASS" in r1_taskbook

    # Project State：已验收 → PASS / INDEPENDENTLY ACCEPTED
    assert "PASS / INDEPENDENTLY ACCEPTED" in current
    assert "PASS / INDEPENDENTLY ACCEPTED" in next_phase
    assert "PASS / INDEPENDENTLY ACCEPTED" in limitations
    assert "d06d8d714958f58d44fb130f8fb30a3aff7e4a7a" in current
    # 不得出现旧的 awaiting / 未验收表述
    assert "AWAITING INDEPENDENT RE-ACCEPTANCE" not in current
    assert "AWAITING INDEPENDENT RE-ACCEPTANCE" not in next_phase
    assert "AWAITING INDEPENDENT RE-ACCEPTANCE" not in limitations
    assert "MERGE AUTHORIZED" not in current
    # P7-D1 仍 NOT AUTHORIZED；D0 已 PASS
    assert "P7-D0" in next_phase and "PASS / INDEPENDENTLY ACCEPTED" in next_phase
    assert "P7-D1" in next_phase and "NOT AUTHORIZED" in next_phase


def test_phase6_shared_contract_frozen():
    """P6-F0: shared contract must be frozen with real structural checks.

    机械保护（task 三十六节）：
    - 七 scenario ID 与设计一致（解析 task.schema.json enum，非字符串碰巧）
    - Task/CLI/default registry scenario 集合不漂移
    - Shared contract ownership 列表存在（CONFLICT ZONE）
    - P6-S5 central enablement 只注册既有 3 核心 + 7 Phase6 Runner
    - Graph→Research read-only contract 存在
    - KnowledgeContext != Evidence
    - DB remains v6（migrations 目录恰 6 个）
    - Phase6 output safety contract 存在
    """
    import json

    from research_os.cli.main import SCENARIO_CHOICES
    from research_os.orchestrator.runners import DEFAULT_RUNNER_TYPES

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

    # 2. CLI --scenario choices 与 enum 一致，并复用唯一默认 Runner 注册源
    cli_choices = list(SCENARIO_CHOICES)
    runner_scenarios = [runner_type.scenario for runner_type in DEFAULT_RUNNER_TYPES]
    assert set(cli_choices) == core | phase6, f"CLI choices drifted: {cli_choices}"
    assert len(cli_choices) == len(set(cli_choices)), "CLI choices must be unique"
    assert cli_choices == runner_scenarios, "CLI choices must derive from DEFAULT_RUNNER_TYPES"

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

    # 4. P6-S5 central enablement：默认注册精确覆盖 3 核心 + 7 Phase6 Runner
    runners_init = _read("src/research_os/orchestrator/runners/__init__.py")
    expected_runner_names = (
        "MorningBriefScenarioRunner", "AbnormalMoveScenarioRunner",
        "EquityResearchScenarioRunner", "IndustryResearchScenarioRunner",
        "ThemeDiscoveryScenarioRunner", "EveningBriefScenarioRunner",
        "DailyReviewScenarioRunner", "StockReviewScenarioRunner",
        "FirstCoverageScenarioRunner", "EarningsExpectationScenarioRunner",
    )
    for runner_name in expected_runner_names:
        assert runner_name in runners_init, f"default runner missing: {runner_name}"
    assert "DEFAULT_RUNNER_TYPES" in runners_init
    orchestrator = _read("src/research_os/orchestrator/orchestrator.py")
    assert "from research_os.orchestrator.runners import DEFAULT_RUNNER_TYPES" in orchestrator
    assert "for runner_type in DEFAULT_RUNNER_TYPES" in orchestrator

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

    # 12. §27 串行 heading
    assert "串行业务开发与中央集成方式" in contract or "串行" in contract

    # 13. P6-S5 中央集成，非 P6-I0
    assert "P6-S5" in contract
    assert "P6-I0" not in contract
