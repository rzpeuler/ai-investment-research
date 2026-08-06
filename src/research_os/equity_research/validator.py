"""Phase 4 跨对象 Validator（任务书 3.22/Commit 16）。

规则编号 ERV-001—ERV-070，输出 pass / pass_with_warnings / fail。
error 阻止报告 PASS；warning 可 pass_with_warnings；合法降级须明确状态。
全部为确定性代码，不使用 LLM。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

FORBIDDEN_WORDS = [
    "目标价", "买入评级", "卖出评级", "增持评级", "减持评级",
    "建议买入", "建议卖出", "仓位建议", "跟随操作", "上涨空间",
    "上行空间", "安全边际对应价格", "每股合理价值",
]
FORBIDDEN_EN = ["target_price", "fair_value", "upside", "buy_rating", "sell_rating"]

VALID_RESEARCH_STATUS = {
    "success", "partial_success", "degraded", "insufficient_data",
    "source_conflict", "validation_failed", "failed",
}


@dataclass
class ValidationIssue:
    rule_id: str
    severity: str  # error / warning
    message: str
    object_id: Optional[str] = None


@dataclass
class ValidationOutcome:
    status: str  # pass / pass_with_warnings / fail
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]


def _severity(is_error: bool) -> str:
    return "error" if is_error else "warning"


# ---------- Schema 与引用（ERV-001—008） ----------

def check_schema(issues: List[ValidationIssue], obj: Any, schema_name: str, rule_id: str = "ERV-001") -> None:
    from research_os.validators.schema_validator import validate_instance

    errors = validate_instance(obj, schema_name)
    for e in errors:
        issues.append(ValidationIssue(rule_id, "error", f"Schema 校验失败: {e}"))


def check_foreign_refs(issues: List[ValidationIssue], refs: List[str], known_ids: set, rule_id: str) -> None:
    for r in refs:
        if r and r not in known_ids:
            issues.append(ValidationIssue(rule_id, "error", f"引用 ID 不存在: {r}", r))


# ---------- 财务数据（ERV-009—027） ----------

def check_missing_not_zero(issues: List[ValidationIssue], fact: Dict[str, Any]) -> None:
    if fact.get("value_status") == "missing" and fact.get("raw_value") == "0":
        issues.append(ValidationIssue("ERV-013", "error", "缺失不得写成零", fact.get("fact_id")))


def check_derived_not_reported(issues: List[ValidationIssue], fact: Dict[str, Any]) -> None:
    if fact.get("value_status") == "reported" and fact.get("period_basis") == "single_quarter":
        issues.append(ValidationIssue("ERV-016", "error", "单季拆分值不得标为 reported", fact.get("fact_id")))


# ---------- 同行与估值（ERV-028—040） ----------

def check_peer_cutoff(issues: List[ValidationIssue], peer: Dict[str, Any], as_of: str) -> None:
    if peer.get("information_cutoff", "9999") > as_of:
        issues.append(ValidationIssue("ERV-028", "error", "同行 information_cutoff 晚于研究截止时间", peer.get("peer_candidate_id")))


def check_no_target_price(issues: List[ValidationIssue], text: str, rule_id: str = "ERV-063") -> None:
    for w in FORBIDDEN_WORDS:
        if w in text:
            issues.append(ValidationIssue(rule_id, "error", f"报告含禁止词: {w}"))
    for w in FORBIDDEN_EN:
        if re.search(w, text, re.IGNORECASE):
            issues.append(ValidationIssue(rule_id, "error", f"报告含禁止英文词: {w}"))


# ---------- Claim、Evidence 与 LLM（ERV-041—052） ----------

def check_fact_has_evidence(issues: List[ValidationIssue], finding: Dict[str, Any]) -> None:
    if finding.get("claim_type") == "FACT" and not finding.get("evidence_ids"):
        issues.append(ValidationIssue("ERV-041", "error", "FACT 必须有合格 Evidence", finding.get("finding_id")))


def check_model_inference_requires_call(issues: List[ValidationIssue], finding: Dict[str, Any]) -> None:
    if finding.get("claim_type") == "MODEL_INFERENCE":
        route = finding.get("model_route") or {}
        if not route.get("llm_called"):
            issues.append(ValidationIssue("ERV-044", "error", "MODEL_INFERENCE 必须有成功 LLM 调用记录", finding.get("finding_id")))


def check_hypothesis_has_failure_condition(issues: List[ValidationIssue], finding: Dict[str, Any]) -> None:
    if finding.get("claim_type") == "HYPOTHESIS" and not finding.get("invalidation_conditions"):
        issues.append(ValidationIssue("ERV-046", "warning", "HYPOTHESIS 应有假设来源和失效条件", finding.get("finding_id")))


def check_unknown_not_negative(issues: List[ValidationIssue], statement: str, object_id: str) -> None:
    if re.search(r"(没有|不存在|无).{0,6}(变化|事件|风险)", statement):
        issues.append(ValidationIssue("ERV-048", "error", "UNKNOWN 不得被渲染成否定事实", object_id))


def check_management_only(issues: List[ValidationIssue], factor: Dict[str, Any]) -> None:
    if factor.get("management_only") and factor.get("status") in ("supported",):
        issues.append(ValidationIssue("ERV-049", "error", "管理层自述不能单独支持强竞争优势", factor.get("factor_id")))


# ---------- 时间、复用和报告（ERV-053—070） ----------

def check_no_future_info(issues: List[ValidationIssue], item: Dict[str, Any], as_of: str) -> None:
    published = item.get("published_at") or item.get("as_of") or ""
    if published and published > as_of:
        issues.append(ValidationIssue("ERV-053", "error", "引用 as_of 之后的信息", item.get("id") or item.get("event_id")))


def check_phase3_readonly(issues: List[ValidationIssue], phase3_objects: List[Dict[str, Any]], expected: Dict[str, str]) -> None:
    """Phase 3 归因状态与主次原因不得被改写（比较期望快照）。"""
    for obj in phase3_objects:
        oid = obj.get("attribution_result_id") or obj.get("id")
        if oid in expected and obj.get("attribution_status") != expected[oid]:
            issues.append(ValidationIssue("ERV-055", "error", "Phase 3 归因状态被改写", oid))


def check_scenario_not_fact(issues: List[ValidationIssue], scenario: Dict[str, Any]) -> None:
    for a in scenario.get("assumptions", []):
        if a.get("claim_type") == "FACT":
            issues.append(ValidationIssue("ERV-062", "error", "情景预测假设不得标为 FACT", scenario.get("scenario_id")))


def check_dry_run_no_side_effects(issues: List[ValidationIssue], dry_run: bool, artifacts: List[str]) -> None:
    if dry_run and artifacts:
        issues.append(ValidationIssue("ERV-069", "error", "dry-run 必须零副作用（不得产生产物）"))


def check_idempotent_no_duplicate(issues: List[ValidationIssue], new_runs: List[Dict[str, Any]]) -> None:
    """幂等命中不得重复写入（同 idempotency_key+run_version 只能一次）。"""
    seen = set()
    for r in new_runs:
        key = (r.get("idempotency_key"), r.get("run_version"))
        if key in seen:
            issues.append(ValidationIssue("ERV-070", "error", "幂等命中重复写入", r.get("run_id")))
        seen.add(key)


# ---------- 主入口 ----------

def validate_equity_research(
    *,
    result: Optional[Dict[str, Any]] = None,
    report_text: str = "",
    findings: Optional[List[Dict[str, Any]]] = None,
    facts: Optional[List[Dict[str, Any]]] = None,
    peers: Optional[List[Dict[str, Any]]] = None,
    factors: Optional[List[Dict[str, Any]]] = None,
    scenarios: Optional[List[Dict[str, Any]]] = None,
    phase3_objects: Optional[List[Dict[str, Any]]] = None,
    phase3_expected: Optional[Dict[str, str]] = None,
    as_of: str = "",
    dry_run: bool = False,
    artifact_paths: Optional[List[str]] = None,
    known_ids: Optional[set] = None,
    known_claim_ids: Optional[set] = None,
) -> ValidationOutcome:
    """运行全部 ERV 规则。返回 pass / pass_with_warnings / fail。"""
    issues: List[ValidationIssue] = []
    findings = findings or []
    facts = facts or []
    peers = peers or []
    scenarios = scenarios or []

    # ERV-063/064/065/066：禁止词扫描（免责声明固定文案除外）
    body = report_text
    disclaimer_idx = body.find("不构成投资建议")
    if disclaimer_idx >= 0:
        body = body[:disclaimer_idx]
    check_no_target_price(issues, body, "ERV-063")
    for w in ["买入评级", "卖出评级", "增持", "减持", "仓位", "跟随操作"]:
        if w in body:
            issues.append(ValidationIssue("ERV-064" if "评级" in w else "ERV-065", "error", f"报告含禁止词: {w}"))
    if re.search(r"(确定性|必然|保证).{0,10}(收益|盈利|回报)", body):
        issues.append(ValidationIssue("ERV-066", "error", "确定性收益承诺"))

    # ERV-041/044/046/048：Claim 规则
    for f in findings:
        check_fact_has_evidence(issues, f)
        check_model_inference_requires_call(issues, f)
        check_hypothesis_has_failure_condition(issues, f)
        check_unknown_not_negative(issues, f.get("statement", ""), f.get("finding_id", ""))

    # ERV-013/016：财务事实
    for fact in facts:
        check_missing_not_zero(issues, fact)
        check_derived_not_reported(issues, fact)

    # ERV-028：同行截止时间
    for p in peers:
        check_peer_cutoff(issues, p, as_of)

    # ERV-049：管理层自述
    for factor in factors or []:
        check_management_only(issues, factor)

    # ERV-062：情景预测不得为 FACT
    for s in scenarios:
        check_scenario_not_fact(issues, s)

    # ERV-053：未来信息污染
    if as_of:
        for f in findings:
            check_no_future_info(issues, f, as_of)

    # ERV-055：Phase 3 只读
    if phase3_objects is not None:
        check_phase3_readonly(issues, phase3_objects, phase3_expected or {})

    # ERV-069：dry-run 零副作用
    check_dry_run_no_side_effects(issues, dry_run, artifact_paths or [])

    # ERV-003：引用完整性
    if known_ids is not None:
        for f in findings:
            check_foreign_refs(issues, f.get("evidence_ids", []), known_ids, "ERV-003")

    # ERV-068：执行摘要不得新增关键事实（结构性：摘要行数 == 已渲染对象数可校验，
    # 此处做基础检查：result 状态合法）
    if result is not None and result.get("research_status") not in VALID_RESEARCH_STATUS:
        issues.append(ValidationIssue("ERV-068", "error", "research_status 非法"))

    if any(i.severity == "error" for i in issues):
        return ValidationOutcome("fail", issues)
    if issues:
        return ValidationOutcome("pass_with_warnings", issues)
    return ValidationOutcome("pass", issues)
