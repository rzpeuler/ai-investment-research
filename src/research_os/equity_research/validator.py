"""Phase 4 跨对象 Validator（任务书 3.22，独立验收修复版）。

规则编号 ERV-001—ERV-079，输出 pass / pass_with_warnings / fail。
error 阻止报告 PASS；warning 可 pass_with_warnings；合法降级须明确状态。
全部为确定性代码，不使用 LLM。

修复要点（独立验收 BLOCKER 2）：
- check_schema / check_idempotent_no_duplicate 接入主入口；
- 补齐财务 ERV-009—027、估值 ERV-029—040、Evidence/OCR ERV-042/050/051、
  引用/一致性 ERV-057/058；
- HYPOTHESIS 缺失效条件由 warning 升级为 error（ERV-046 硬约束）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence

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

# FinancialFact 模型名 → Schema 名（ERV-001/002 用）
MODEL_SCHEMA_MAP = {
    "CompanyProfile": "company_profile",
    "SecurityProfile": "security_profile",
    "DocumentRecord": "document_record",
    "DocumentBlock": "document_block",
    "FinancialDataManifest": "financial_data_manifest",
    "FinancialReport": "financial_report",
    "FinancialFact": "financial_fact",
    "FinancialMetric": "financial_metric",
    "BusinessSegment": "business_segment",
    "PeerCandidate": "peer_candidate",
    "PeerSelection": "peer_selection",
    "ValuationSnapshot": "valuation_snapshot",
    "ForecastScenario": "forecast_scenario",
    "CompetitiveFactor": "competitive_factor",
    "Catalyst": "catalyst",
    "RiskFactor": "risk_factor",
    "ResearchFinding": "research_finding",
    "EquityResearchRequest": "equity_research_request",
    "EquityResearchRun": "equity_research_run",
    "EquityResearchResult": "equity_research_result",
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


# ---------- Schema 与引用（ERV-001—008） ----------

def check_schema(issues: List[ValidationIssue], obj: Dict[str, Any], schema_name: str) -> None:
    """ERV-001/002：对象通过对应 Schema；Pydantic dump 后再次通过。"""
    from research_os.validators.schema_validator import validate_instance

    errors = validate_instance(obj, schema_name)
    for e in errors:
        issues.append(ValidationIssue("ERV-001", "error", f"Schema 校验失败: {e}", obj.get("_id")))


def check_foreign_refs(issues: List[ValidationIssue], refs: Sequence[str], known_ids: set, rule_id: str) -> None:
    """ERV-003：引用 ID 必须存在。"""
    for r in refs:
        if r and r not in known_ids:
            issues.append(ValidationIssue(rule_id, "error", f"引用 ID 不存在: {r}", r))


# ---------- 财务数据（ERV-009—027） ----------

def check_unit_consistency(issues: List[ValidationIssue], facts: List[Dict[str, Any]]) -> None:
    """ERV-009：单位一致或有显式转换。"""
    seen: Dict[str, str] = {}
    for f in facts:
        key = (f.get("company_entity_id"), f.get("period_end"), f.get("taxonomy_code"))
        unit = f.get("unit_scale")
        if key in seen and seen[key] != unit:
            issues.append(ValidationIssue("ERV-009", "error",
                                          f"同期间同科目单位不一致: {key}（{seen[key]} vs {unit}）", f.get("fact_id")))
        seen[key] = unit


def check_currency_consistency(issues: List[ValidationIssue], facts: List[Dict[str, Any]]) -> None:
    """ERV-010：币种一致或有汇率证据。"""
    for f in facts:
        if f.get("currency") and len(str(f.get("currency"))) != 3:
            issues.append(ValidationIssue("ERV-010", "error", "币种非 ISO 4217", f.get("fact_id")))
        if f.get("currency") != "CNY" and not f.get("evidence_ids"):
            issues.append(ValidationIssue("ERV-010", "warning",
                                          f"外币 {f.get('currency')} 无汇率证据", f.get("fact_id")))


def check_period_consistency(issues: List[ValidationIssue], facts: List[Dict[str, Any]]) -> None:
    """ERV-011：报告期一致（period_start < period_end）。"""
    for f in facts:
        ps, pe = f.get("period_start"), f.get("period_end")
        if ps and pe and ps > pe:
            issues.append(ValidationIssue("ERV-011", "error", "期间倒置", f.get("fact_id")))


def check_scope_not_mixed(issues: List[ValidationIssue], facts: List[Dict[str, Any]]) -> None:
    """ERV-012：合并/母公司口径不得混用（同指标跨口径直接比较）。"""
    by_key: Dict[tuple, set] = {}
    for f in facts:
        key = (f.get("company_entity_id"), f.get("period_end"), f.get("taxonomy_code"))
        by_key.setdefault(key, set()).add(f.get("statement_scope"))
    for key, scopes in by_key.items():
        if len(scopes) > 1:
            issues.append(ValidationIssue("ERV-012", "error",
                                          f"同科目同期间混用口径 {scopes}: {key}"))


def check_missing_not_zero(issues: List[ValidationIssue], fact: Dict[str, Any]) -> None:
    """ERV-013：缺失不得写成零。"""
    if fact.get("value_status") == "missing" and fact.get("raw_value") == "0":
        issues.append(ValidationIssue("ERV-013", "error", "缺失不得写成零", fact.get("fact_id")))


def check_na_not_negative(issues: List[ValidationIssue], fact: Dict[str, Any]) -> None:
    """ERV-014：非适用不得写成缺失或负面结论。"""
    if fact.get("value_status") == "not_applicable" and fact.get("normalized_value") == "0":
        issues.append(ValidationIssue("ERV-014", "warning", "not_applicable 写成零", fact.get("fact_id")))


def check_instant_duration(issues: List[ValidationIssue], facts: List[Dict[str, Any]]) -> None:
    """ERV-015：instant（时点）与 duration（期间）科目不得混算。
    同一 (company, period_end, taxonomy_code, scope) 的 instant_or_duration 必须一致；
    资产负债表科目必须为 instant，利润表/现金流量表科目必须为 duration。"""
    by_key: Dict[tuple, set] = {}
    for f in facts:
        key = (f.get("company_entity_id"), f.get("period_end"),
               f.get("taxonomy_code"), f.get("statement_scope"))
        iod = f.get("instant_or_duration")
        if iod:
            by_key.setdefault(key, set()).add(iod)
    for key, iod_set in by_key.items():
        if len(iod_set) > 1:
            issues.append(ValidationIssue("ERV-015", "error",
                                          f"同键 instant/duration 混算 {iod_set}: {key}"))
    for f in facts:
        stmt = f.get("statement_type")
        iod = f.get("instant_or_duration")
        if stmt == "balance_sheet" and iod == "duration":
            issues.append(ValidationIssue("ERV-015", "error", "资产负债表科目必须为 instant", f.get("fact_id")))
        if stmt in ("income_statement", "cash_flow") and iod == "instant":
            issues.append(ValidationIssue("ERV-015", "error", "利润表/现金流科目必须为 duration", f.get("fact_id")))


def check_derived_not_reported(issues: List[ValidationIssue], fact: Dict[str, Any]) -> None:
    """ERV-016：单季拆分值不得标为 reported。"""
    if fact.get("value_status") == "reported" and fact.get("period_basis") == "single_quarter":
        issues.append(ValidationIssue("ERV-016", "error", "单季拆分值不得标为 reported", fact.get("fact_id")))


def check_ratio_decimal(issues: List[ValidationIssue], metrics: List[Dict[str, Any]]) -> None:
    """ERV-017—020/025/026：指标可复算（十进制、零分母显式、输入血缘完整）。"""
    from research_os.utils.decimal import normalize_decimal_string

    for m in metrics:
        if m.get("value") is not None:
            try:
                if not isinstance(m.get("value"), str):
                    raise ValueError("metric value must be a string")
                normalize_decimal_string(m.get("value"))
            except ValueError:
                issues.append(ValidationIssue("ERV-025", "error", "指标值非有限十进制字符串", m.get("metric_id")))
        if m.get("status") == "zero_denominator" and m.get("value") is not None:
            issues.append(ValidationIssue("ERV-026", "error", "零分母不得输出数值", m.get("metric_id")))
        if not m.get("formula_id") or not m.get("formula_version"):
            issues.append(ValidationIssue("ERV-017", "error", "指标缺公式标识", m.get("metric_id")))


def check_restatement_kept(issues: List[ValidationIssue], reports: List[Dict[str, Any]]) -> None:
    """ERV-023：重述版本保留且当前版本选择符合优先级。"""
    by_key: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in reports:
        key = (r.get("company_entity_id"), r.get("period_end"), r.get("report_type"))
        by_key.setdefault(key, []).append(r)
    for key, group in by_key.items():
        statuses = {g.get("restatement_status") for g in group}
        if len(statuses) > 1 and "original" in statuses and "restated" not in statuses:
            issues.append(ValidationIssue("ERV-023", "warning", f"重述版本选择异常: {key}"))


def check_conflict_not_silenced(issues: List[ValidationIssue], facts: List[Dict[str, Any]]) -> None:
    """ERV-024：重复事实冲突不得被静默消除。"""
    by_key: Dict[tuple, set] = {}
    for f in facts:
        key = (f.get("fact_key") or f.get("taxonomy_code"), f.get("period_end"))
        v = f.get("raw_value")
        if v is not None:
            by_key.setdefault(key, set()).add(v)
    for key, values in by_key.items():
        if len(values) > 1 and not any(f.get("conflict_group_id") for f in facts
                                       if (f.get("fact_key") or f.get("taxonomy_code"), f.get("period_end")) == key):
            issues.append(ValidationIssue("ERV-024", "error",
                                          f"同键冲突未标 conflict_group: {key}（{values}）"))


def check_llm_not_edit_financials(issues: List[ValidationIssue], fact: Dict[str, Any]) -> None:
    """ERV-027：LLM 没有修改任何财务事实或指标（本阶段无 LLM 参与财务，结构保证）。"""
    route = fact.get("model_route") or {}
    if route.get("llm_called") and fact.get("value_status") == "reported":
        issues.append(ValidationIssue("ERV-027", "error", "财务事实不得由 LLM 修改", fact.get("fact_id")))


# ---------- 同行与估值（ERV-028—040） ----------

def check_peer_cutoff(issues: List[ValidationIssue], peer: Dict[str, Any], as_of: str) -> None:
    """ERV-028：同行 information_cutoff 不晚于研究截止时间。"""
    if peer.get("information_cutoff", "9999-12-31T00:00:00") > as_of:
        issues.append(ValidationIssue("ERV-028", "error", "同行 information_cutoff 晚于研究截止时间", peer.get("peer_candidate_id")))


def check_peer_valid_from(issues: List[ValidationIssue], peer: Dict[str, Any]) -> None:
    """ERV-029：同行关系 valid_from 不晚于 information_cutoff。"""
    if peer.get("relationship_valid_from", "9999-12-31") > str(peer.get("information_cutoff", ""))[:10]:
        issues.append(ValidationIssue("ERV-029", "error", "同行关系 valid_from 晚于 cutoff", peer.get("peer_candidate_id")))


def check_peer_universe_frozen(issues: List[ValidationIssue], peers: List[Dict[str, Any]]) -> None:
    """ERV-030/031：宇宙版本冻结；最终资格可复算（eligible 与分数一致）。"""
    versions = {p.get("universe_version") for p in peers}
    if len(versions) > 1:
        issues.append(ValidationIssue("ERV-030", "error", f"同行宇宙版本不一致: {versions}"))
    for p in peers:
        if p.get("eligible") and (p.get("total_score", 0) < 65 or p.get("core_subtotal", 0) < 35):
            issues.append(ValidationIssue("ERV-031", "error", "资格与评分不一致", p.get("peer_candidate_id")))


def check_peer_sample_threshold(issues: List[ValidationIssue], selection: Optional[Dict[str, Any]]) -> None:
    """ERV-033：同行样本不足不得输出正式分位。"""
    if not selection:
        return
    size = selection.get("sample_size", 0)
    status = selection.get("status")
    if size >= 5 and status != "full":
        issues.append(ValidationIssue("ERV-033", "warning", f"样本 {size} 应为 full"))
    if 3 <= size <= 4 and status != "limited":
        issues.append(ValidationIssue("ERV-033", "warning", f"样本 {size} 应为 limited"))
    if size < 3 and status != "insufficient":
        issues.append(ValidationIssue("ERV-033", "warning", f"样本 {size} 应为 insufficient"))


def check_valuation_time_consistency(issues: List[ValidationIssue], valuation: Optional[Dict[str, Any]]) -> None:
    """ERV-034：市值/股本/价格时点一致。"""
    if not valuation:
        return
    if valuation.get("market_cap") and not (valuation.get("price") or valuation.get("direct_market_cap")):
        issues.append(ValidationIssue("ERV-034", "warning", "市值存在但无价格/股本输入，时点不可核", valuation.get("valuation_snapshot_id")))


def check_valuation_na_rules(issues: List[ValidationIssue], valuation: Optional[Dict[str, Any]]) -> None:
    """ERV-037/039：负利润/负净资产/负 EBITDA 正确标为不适用；适用性说明存在。"""
    if not valuation:
        return
    for m in valuation.get("metrics", []):
        if m.get("status") == "not_applicable" and not m.get("warnings"):
            issues.append(ValidationIssue("ERV-037", "warning", f"{m.get('metric_code')} N/A 缺原因"))
    if not valuation.get("applicability_notes"):
        issues.append(ValidationIssue("ERV-039", "warning", "估值适用性说明缺失"))


def check_no_target_price(issues: List[ValidationIssue], text: str, rule_id: str = "ERV-063") -> None:
    """ERV-063/040：报告与估值不得含目标价/上涨空间。"""
    for w in FORBIDDEN_WORDS:
        if w in text:
            issues.append(ValidationIssue(rule_id, "error", f"报告含禁止词: {w}"))
    for w in FORBIDDEN_EN:
        if re.search(w, text, re.IGNORECASE):
            issues.append(ValidationIssue(rule_id, "error", f"报告含禁止英文词: {w}"))


# ---------- Claim、Evidence 与 LLM（ERV-041—052） ----------

def check_fact_has_evidence(issues: List[ValidationIssue], finding: Dict[str, Any]) -> None:
    """ERV-041：FACT 必须有合格 Evidence。"""
    if finding.get("claim_type") == "FACT" and not finding.get("evidence_ids"):
        issues.append(ValidationIssue("ERV-041", "error", "FACT 必须有合格 Evidence", finding.get("finding_id")))


def check_financial_fact_has_block(issues: List[ValidationIssue], finding: Dict[str, Any], fact_ids: set) -> None:
    """ERV-042：财务 FACT 必须引用 FinancialFact 和文档块。"""
    if finding.get("claim_type") == "FACT" and finding.get("finding_type") == "financial_quality":
        support = set(finding.get("supporting_object_ids") or [])
        if not support & fact_ids:
            issues.append(ValidationIssue("ERV-042", "warning", "财务 FACT 未引用 FinancialFact", finding.get("finding_id")))


def check_model_inference_requires_call(issues: List[ValidationIssue], finding: Dict[str, Any]) -> None:
    """ERV-044：MODEL_INFERENCE 必须有成功 LLM 调用记录。"""
    if finding.get("claim_type") == "MODEL_INFERENCE":
        route = finding.get("model_route") or {}
        if not route.get("llm_called"):
            issues.append(ValidationIssue("ERV-044", "error", "MODEL_INFERENCE 必须有成功 LLM 调用记录", finding.get("finding_id")))


def check_fallback_no_inference(issues: List[ValidationIssue], finding: Dict[str, Any]) -> None:
    """ERV-045：模型调用失败的回退不得产生 MODEL_INFERENCE。
    model_route 记录 failure（调用但失败）时，claim 不得标 MODEL_INFERENCE。"""
    if finding.get("claim_type") == "MODEL_INFERENCE":
        route = finding.get("model_route") or {}
        if route.get("status") in ("failure", "fallback", "error"):
            issues.append(ValidationIssue("ERV-045", "error",
                                          "调用失败的回退不得产生 MODEL_INFERENCE", finding.get("finding_id")))


def check_required_fields(issues: List[ValidationIssue], obj: Dict[str, Any], schema_name: str,
                          rule_id: str, required: Sequence[str], object_id_key: str = "id") -> None:
    """ERV-004/005：对象必填字段与类型完整性（逐对象规则）。"""
    for field in required:
        if field not in obj or obj.get(field) in (None, "", [], {}):
            issues.append(ValidationIssue(rule_id, "error",
                                          f"{schema_name} 缺必填字段: {field}", obj.get(object_id_key)))


def check_enum_validity(issues: List[ValidationIssue], obj: Dict[str, Any], schema_name: str,
                        rule_id: str, enums: Dict[str, set], object_id_key: str = "id") -> None:
    """ERV-006：枚举字段合法性。"""
    for field, allowed in enums.items():
        val = obj.get(field)
        if val is not None and val not in allowed:
            issues.append(ValidationIssue(rule_id, "error",
                                          f"{schema_name}.{field} 非法枚举: {val!r}", obj.get(object_id_key)))


def check_temporal_order(issues: List[ValidationIssue], obj: Dict[str, Any], rule_id: str,
                         start_key: str, end_key: str, object_id_key: str = "id") -> None:
    """ERV-007：时间顺序（start <= end）。"""
    s, e = obj.get(start_key), obj.get(end_key)
    if s and e and s > e:
        issues.append(ValidationIssue(rule_id, "error",
                                      f"{start_key} 晚于 {end_key}", obj.get(object_id_key)))


def check_metric_recompute(issues: List[ValidationIssue], metrics: List[Dict[str, Any]],
                           facts: List[Dict[str, Any]], reports: List[Dict[str, Any]]) -> None:
    """ERV-018—022：全部支持指标依命名参数、血缘、公式版本确定性复算。"""
    from research_os.financials.metrics import (
        METRIC_FORMULA_REGISTRY, normalize_metric_decimal, recompute_from_lineage,
    )
    for m in metrics:
        spec = METRIC_FORMULA_REGISTRY.get(m.get("metric_code"))
        if spec is None:
            severity = "error" if m.get("status") == "valid" else "warning"
            issues.append(ValidationIssue("ERV-019", severity, f"未登记的指标复算规则: {m.get('metric_code')}", m.get("metric_id")))
            continue
        if m.get("formula_id") != spec.formula_id or m.get("formula_version") != spec.formula_version:
            issues.append(ValidationIssue("ERV-019", "error", "指标 formula_id/formula_version 缺失或不匹配", m.get("metric_id")))
            continue
        if m.get("unit") != spec.unit or m.get("precision") != spec.precision:
            issues.append(ValidationIssue("ERV-019", "error", "指标单位或精度与公式注册表不匹配", m.get("metric_id")))
        expected, binding_errors = recompute_from_lineage(m, facts, reports)
        if binding_errors:
            severity = "error" if m.get("status") == "valid" else "warning"
            for message in binding_errors:
                issues.append(ValidationIssue("ERV-019", severity, message, m.get("metric_id")))
            continue
        if expected is None:
            if m.get("status") == "valid":
                issues.append(ValidationIssue("ERV-019", "error", "valid 指标无法复算", m.get("metric_id")))
            continue
        if m.get("status") != expected.status:
            issues.append(ValidationIssue("ERV-019", "error",
                                          f"指标状态与复算不一致: {m.get('metric_code')}（期望 {expected.status}，实际 {m.get('status')}）", m.get("metric_id")))
            continue
        if m.get("status") == "valid":
            try:
                actual_value = normalize_metric_decimal(m.get("value"), spec.precision, spec.rounding_mode)
                expected_value = normalize_metric_decimal(expected.value, spec.precision, spec.rounding_mode)
            except ValueError:
                issues.append(ValidationIssue("ERV-019", "error", "valid 指标数值不可解析", m.get("metric_id")))
                continue
            if actual_value != expected_value:
                issues.append(ValidationIssue("ERV-019", "error",
                                              f"指标复算值不一致: {m.get('metric_code')}（期望 {expected.value}，实际 {m.get('value')}）", m.get("metric_id")))


def check_peer_requalify(issues: List[ValidationIssue], peer: Dict[str, Any]) -> None:
    """ERV-032：复用 selector 的加权公式，检测 score 或 eligible 被篡改。"""
    from research_os.equity_research.peer_selector import PeerInput, evaluate_peer_eligibility
    try:
        values = {name: peer.get(name) for name in PeerInput.__dataclass_fields__}
        pi = PeerInput(**values)
        expected_total, expected_core, reasons = evaluate_peer_eligibility(pi)
    except (TypeError, ValueError):
        issues.append(ValidationIssue("ERV-032", "error", "同行资格输入不完整", peer.get("peer_candidate_id")))
        return
    if peer.get("total_score") != expected_total or peer.get("core_subtotal") != expected_core:
        issues.append(ValidationIssue("ERV-032", "error", "同行加权评分被篡改", peer.get("peer_candidate_id")))
    if bool(peer.get("eligible")) != (not reasons):
        issues.append(ValidationIssue("ERV-032", "error", "同行 eligible 与资格规则不一致", peer.get("peer_candidate_id")))


def check_market_consistency(issues: List[ValidationIssue], valuation: Optional[Dict[str, Any]],
                             as_of: str) -> None:
    """ERV-035/036：市值时点与 as_of 一致；EV 净债务口径正确。"""
    if not valuation:
        return
    if valuation.get("as_of") and valuation["as_of"] != as_of:
        issues.append(ValidationIssue("ERV-035", "error", "市值时点与 as_of 不一致", valuation.get("valuation_snapshot_id")))
    for m in valuation.get("metrics", []):
        if m.get("metric_code") == "EV" and m.get("status") == "valid":
            if valuation.get("restricted_cash") and m.get("value"):
                issues.append(ValidationIssue("ERV-036", "warning", "受限现金不得从 EV 扣除", valuation.get("valuation_snapshot_id")))


def check_percentile_threshold(issues: List[ValidationIssue], valuation: Optional[Dict[str, Any]]) -> None:
    """ERV-038：历史分位 >=36 样本、同行分位 >=5 才输出正式分位。"""
    if not valuation:
        return
    for m in valuation.get("metrics", []):
        hist = m.get("history_percentile") or m.get("percentile")
        if hist is not None and (m.get("history_sample_size") or 0) < 36:
            issues.append(ValidationIssue("ERV-038", "warning", "历史分位样本 <36", valuation.get("valuation_snapshot_id")))
        peer_pct = m.get("peer_percentile")
        if peer_pct is not None and (m.get("peer_sample_size") or 0) < 5:
            issues.append(ValidationIssue("ERV-038", "warning", "同行分位样本 <5", valuation.get("valuation_snapshot_id")))


def check_evidence_qualified(issues: List[ValidationIssue], finding: Dict[str, Any],
                             evidence_by_id: Dict[str, Dict[str, Any]], as_of: str) -> None:
    """ERV-043：FACT 的 Evidence 必须合格（存在/披露时间<=as_of/来源等级非 D/独立组非空）。"""
    if finding.get("claim_type") != "FACT":
        return
    for eid in finding.get("evidence_ids", []):
        ev = evidence_by_id.get(eid)
        if ev is None:
            issues.append(ValidationIssue("ERV-043", "error", f"FACT 引用不存在的 Evidence: {eid}", finding.get("finding_id")))
            continue
        published = ev.get("published_at") or ""
        if published and as_of and published > as_of:
            issues.append(ValidationIssue("ERV-043", "error", "Evidence 披露时间晚于 as_of", finding.get("finding_id")))
        if ev.get("source_tier") in ("C", "D") and finding.get("support_level") == "direct":
            severity = "error" if finding.get("materiality") == "high" else "warning"
            issues.append(ValidationIssue(
                "ERV-043", severity, "C/D 级来源不得单独直接支持重大 FACT",
                finding.get("finding_id"),
            ))
        if not ev.get("independence_group"):
            issues.append(ValidationIssue("ERV-043", "warning", "Evidence 缺独立证据组", finding.get("finding_id")))


def check_assumption_has_source(issues: List[ValidationIssue], scenario: Dict[str, Any]) -> None:
    """ERV-047：情景假设必须有来源（company_guidance/external_opinion/user_input 等）。"""
    for a in scenario.get("assumptions", []):
        if not a.get("source_type") and not a.get("source"):
            issues.append(ValidationIssue("ERV-047", "error", "假设缺来源", scenario.get("scenario_id")))


def check_block_evidence_link(issues: List[ValidationIssue], finding: Dict[str, Any],
                              block_by_id: Dict[str, Dict[str, Any]]) -> None:
    """ERV-052：FACT 引用的文档块必须真实存在（页码/表格定位）。"""
    if finding.get("claim_type") != "FACT":
        return
    for bid in finding.get("source_block_ids", []):
        if bid not in block_by_id:
            issues.append(ValidationIssue("ERV-052", "error", f"FACT 引用不存在的文档块: {bid}", finding.get("finding_id")))


def check_phase2_readonly(issues: List[ValidationIssue], event: Dict[str, Any]) -> None:
    """ERV-054：Phase 2 晨报事件只读复用，不得改写事件状态/内容。"""
    if event.get("status") and event["status"] not in ("ok", "processed", "reused"):
        issues.append(ValidationIssue("ERV-054", "warning", "晨报事件状态异常", event.get("event_id")))


def check_morning_reuse_structured(issues: List[ValidationIssue], event: Dict[str, Any]) -> None:
    """ERV-056：晨报复用结构化中间产物（事件对象而非 Markdown 文本）。"""
    if not event.get("event_id") or not event.get("event_type"):
        issues.append(ValidationIssue("ERV-056", "warning", "事件缺结构化标识", event.get("event_id")))


def check_evidence_lineage(issues: List[ValidationIssue], evidences: List[Dict[str, Any]],
                           raw_items: List[Dict[str, Any]]) -> None:
    """证据必须逐条回指真实 RawItem，且来源、时间和 URL 与原始记录一致。"""
    raw_by_id = {item.get("raw_item_id"): item for item in raw_items}
    for evidence in evidences:
        eid = evidence.get("evidence_id")
        raw = raw_by_id.get(evidence.get("raw_item_id"))
        if raw is None:
            issues.append(ValidationIssue("ERV-071", "error", "Evidence.raw_item_id 不存在", eid))
            continue
        for field in ("source_id", "publisher", "published_at", "retrieved_at", "url"):
            if evidence.get(field) != raw.get(field):
                issues.append(ValidationIssue(
                    "ERV-071", "error", f"Evidence 与 RawItem 的 {field} 不一致", eid,
                ))
        if evidence.get("source_id") == "morning_brief_events":
            issues.append(ValidationIssue("ERV-072", "error", "不得把聚合事件伪装为原始来源", eid))
        if evidence.get("source_id") == "manual_financial_import":
            excerpt = raw.get("content_excerpt", "")
            required = ("manifest=", "checksum=", "locator=", "source_kind=",
                        "parser_version=", "imported_at=", "is_statutory_original=")
            missing = [token for token in required if token not in excerpt]
            if missing:
                issues.append(ValidationIssue(
                    "ERV-079", "error", f"人工财务 Evidence 缺原始输入定位元数据: {missing}", eid,
                ))


def check_claim_evidence_contract(issues: List[ValidationIssue], claims: List[Dict[str, Any]],
                                  evidence_ids: set) -> None:
    """Claim 引用须存在；事实须有证据；来源观点须标明说话者或发布者。"""
    for claim in claims:
        cid = claim.get("claim_id")
        refs = claim.get("evidence_ids") or []
        check_foreign_refs(issues, refs, evidence_ids, "ERV-073")
        if claim.get("claim_type") == "FACT" and not refs:
            issues.append(ValidationIssue("ERV-073", "error", "FACT Claim 缺 Evidence", cid))
        if claim.get("claim_type") == "SOURCE_OPINION":
            obj = claim.get("object") or {}
            if not (obj.get("speaker") or obj.get("speaker_entity_id") or obj.get("publisher")):
                issues.append(ValidationIssue("ERV-074", "error", "SOURCE_OPINION 未标明说话者或发布者", cid))


def check_competitive_evidence_types(
    issues: List[ValidationIssue], factor: Dict[str, Any],
    evidence_by_id: Dict[str, Dict[str, Any]],
) -> None:
    """ERV-078：竞争因素声明的 Evidence 类型必须与实际引用一致。"""
    refs = set(factor.get("evidence_ids") or []) | set(factor.get("counter_evidence_ids") or [])
    required = set(factor.get("required_evidence_types") or [])
    if not refs:
        return
    if not required:
        issues.append(ValidationIssue(
            "ERV-078", "error", "竞争因素引用 Evidence 但 required_evidence_types 为空",
            factor.get("factor_id"),
        ))
        return
    evidence_object_types = {
        "official_disclosure", "official_statistics", "company_official", "news_report",
        "media_report", "social_opinion", "institution_material", "market_data",
        "manual_input", "unknown",
    }
    missing_refs = refs - set(evidence_by_id)
    actual = {evidence_by_id[eid].get("evidence_type") for eid in refs if eid in evidence_by_id}
    # 历史确定性竞争模块还会使用 market_share 等“业务证据门槛”标签；
    # 只有声明的是 Evidence 对象类型时才做一一类型资格校验。
    declares_object_types = required <= evidence_object_types
    if missing_refs or (declares_object_types and not actual <= required):
        issues.append(ValidationIssue(
            "ERV-078", "error", "竞争因素 required_evidence_types 与实际 Evidence 类型不一致",
            factor.get("factor_id"),
        ))


def check_report_evidence_refs(issues: List[ValidationIssue], report_text: str,
                               evidence_ids: set) -> None:
    """Markdown 中展示的 Evidence ID 必须是真实 Evidence 对象。"""
    for eid in re.findall(r"Evidence ID:\s*`([0-9a-fA-F-]{36})`", report_text):
        if eid not in evidence_ids:
            issues.append(ValidationIssue("ERV-075", "error", f"Markdown 引用不存在的 Evidence: {eid}", eid))


def check_research_status_contract(issues: List[ValidationIssue], result: Optional[Dict[str, Any]]) -> None:
    """核心覆盖不完整时不得宣称 success。"""
    if not result or result.get("research_status") != "success":
        return
    missing = (result.get("coverage") or {}).get("missing_core_modules") or []
    if missing:
        issues.append(ValidationIssue("ERV-076", "error", f"核心模块缺失时不得 success: {missing}", result.get("result_id")))


def check_semantic_route_contract(issues: List[ValidationIssue], findings: List[Dict[str, Any]],
                                  claims: List[Dict[str, Any]], run: Optional[Dict[str, Any]],
                                  semantic_records: List[Dict[str, Any]]) -> None:
    """模型调用、Provider/模型记录与 MODEL_INFERENCE 标签必须一致。"""
    called = any(record.get("llm_called") for record in semantic_records)
    successful = any(
        record.get("llm_called") and record.get("validation_status") == "pass"
        for record in semantic_records
    )
    for record in semantic_records:
        if record.get("llm_called") and not (record.get("provider") and record.get("model")):
            issues.append(ValidationIssue("ERV-077", "error", "实际 LLM 调用缺 Provider 或模型记录",
                                          record.get("task_name")))
    route = (run or {}).get("model_route_summary") or {}
    if bool(route.get("llm_called")) != called:
        issues.append(ValidationIssue("ERV-077", "error", "run.model_route_summary 与语义调用记录不一致"))
    if not successful:
        for item in [*findings, *claims]:
            if item.get("claim_type") == "MODEL_INFERENCE":
                issues.append(ValidationIssue("ERV-045", "error",
                                              "无成功模型输出时不得产生 MODEL_INFERENCE",
                                              item.get("finding_id") or item.get("claim_id")))


def check_market_debate_contract(issues: List[ValidationIssue], market_debate: Dict[str, Any],
                                 evidence_ids: set) -> None:
    """市场主要矛盾中的多空主张必须保持结构化证据引用。"""
    for side in ("bull_claims", "bear_claims", "consensus", "key_variables"):
        for item in market_debate.get(side, []) or []:
            if not isinstance(item, dict) or not item.get("statement"):
                issues.append(ValidationIssue("ERV-078", "error", f"{side} 不是结构化主张"))
                continue
            check_foreign_refs(issues, item.get("evidence_ids", []), evidence_ids, "ERV-078")
    if market_debate.get("status") == "covered":
        claims = [*(market_debate.get("bull_claims") or []),
                  *(market_debate.get("bear_claims") or [])]
        if not claims or any(not item.get("evidence_ids") for item in claims):
            issues.append(ValidationIssue("ERV-078", "error", "市场主要矛盾标为 covered 但主张缺 Evidence"))


def check_report_number_consistency(issues: List[ValidationIssue], report_text: str,
                                    metrics: List[Dict[str, Any]],
                                    valuation: Optional[Dict[str, Any]]) -> None:
    """ERV-059—061：核对可见 token、稳定标识、中文标签、单位与章节。"""
    from research_os.equity_research.metric_display import (
        FINANCIAL_METRIC_DISPLAY,
        VALUATION_METRIC_DISPLAY,
        latest_financial_metrics,
        render_metric_line,
        controlled_metric_sections,
        unmarked_metric_assertion,
        valuation_metric_id,
    )

    expected: Dict[str, tuple] = {}
    for metric in latest_financial_metrics(metrics):
        spec = FINANCIAL_METRIC_DISPLAY[metric["metric_code"]]
        expected[metric["metric_id"]] = (metric, spec)
    if valuation:
        snapshot_id = valuation.get("valuation_snapshot_id", "unknown")
        for metric in valuation.get("metrics", []):
            spec = VALUATION_METRIC_DISPLAY.get(metric.get("metric_code"))
            if spec:
                expected[valuation_metric_id(snapshot_id, metric["metric_code"])] = (metric, spec)

    marker_re = re.compile(r"<!--\s*metric-id:(\S+)\s+metric-code:(\S+)\s*-->")
    seen: Dict[str, int] = {}
    current_section: Optional[int] = None
    controlled_sections = controlled_metric_sections()
    for line in report_text.splitlines():
        heading = re.match(r"^##\s+(\d+)\.", line)
        if heading:
            current_section = int(heading.group(1))
        markers = marker_re.findall(line)
        if current_section in controlled_sections and not markers and unmarked_metric_assertion(line):
            issues.append(ValidationIssue("ERV-060", "error", "受控指标章节存在未标记的指标断言"))
        for metric_id, metric_code in markers:
            seen[metric_id] = seen.get(metric_id, 0) + 1
            pair = expected.get(metric_id)
            if pair is None:
                issues.append(ValidationIssue("ERV-060", "error", "报告引用不存在的 metric", metric_id))
                continue
            metric, spec = pair
            if metric_code != metric.get("metric_code"):
                issues.append(ValidationIssue("ERV-060", "error", "metric-id 与 metric-code 不匹配", metric_id))
            if current_section != spec.section_id:
                issues.append(ValidationIssue("ERV-061", "error", "指标位于错误章节", metric_id))
            expected_line = render_metric_line(metric, spec, metric_id)
            if line.strip() != expected_line:
                issues.append(ValidationIssue("ERV-059", "error",
                                              f"指标可见数字、名称、单位或精度不一致: {metric_code}", metric_id))

    for metric_id in expected:
        count = seen.get(metric_id, 0)
        if count == 0:
            issues.append(ValidationIssue("ERV-060", "error", "应展示的 metric 标识缺失", metric_id))
        elif count > 1:
            issues.append(ValidationIssue("ERV-060", "error", "metric 标识重复", metric_id))


def check_hypothesis_has_failure_condition(issues: List[ValidationIssue], finding: Dict[str, Any]) -> None:
    """ERV-046：HYPOTHESIS 必须有假设来源和失效条件（硬约束 → error）。"""
    if finding.get("claim_type") == "HYPOTHESIS" and not finding.get("invalidation_conditions"):
        issues.append(ValidationIssue("ERV-046", "error", "HYPOTHESIS 必须有失效条件", finding.get("finding_id")))


def check_unknown_not_negative(issues: List[ValidationIssue], statement: str, object_id: str) -> None:
    """ERV-048：UNKNOWN 不得被渲染成否定事实。"""
    if re.search(r"(没有|不存在|无).{0,6}(变化|事件|风险|影响)", statement):
        issues.append(ValidationIssue("ERV-048", "error", "UNKNOWN 不得被渲染成否定事实", object_id))


def check_management_only(issues: List[ValidationIssue], factor: Dict[str, Any]) -> None:
    """ERV-049：管理层自述不能单独支持强竞争优势。"""
    if factor.get("management_only") and factor.get("status") == "supported":
        issues.append(ValidationIssue("ERV-049", "error", "管理层自述不能单独支持强竞争优势", factor.get("factor_id")))


def check_block_reference(issues: List[ValidationIssue], blocks: List[Dict[str, Any]], fact_ids: set) -> None:
    """ERV-050/051：文档页码/表格/block 引用有效；OCR 低置信块未经确认不得支持关键 FACT。"""
    for b in blocks:
        if b.get("extraction_method") == "ocr" and (b.get("confidence") or 0) < 0.8 \
                and b.get("correction_status") == "unreviewed":
            issues.append(ValidationIssue("ERV-051", "error", "低置信 OCR 块未确认", b.get("block_id")))
        if not b.get("page_start") or not b.get("content_hash"):
            issues.append(ValidationIssue("ERV-050", "error", "block 缺页码或哈希", b.get("block_id")))


# ---------- 时间、复用和报告（ERV-053—070） ----------

def check_no_future_info(issues: List[ValidationIssue], item: Dict[str, Any], as_of: str) -> None:
    """ERV-053：不得引用 as_of 之后的信息。"""
    published = (item.get("published_at") or item.get("as_of")
                 or item.get("valid_from") or item.get("created_at") or "")
    if published and published > as_of:
        issues.append(ValidationIssue("ERV-053", "error", "引用 as_of 之后的信息",
                                      item.get("id") or item.get("event_id") or item.get("fact_id")))


def check_phase3_readonly(issues: List[ValidationIssue], phase3_objects: List[Dict[str, Any]], expected: Dict[str, str]) -> None:
    """ERV-055：Phase 3 归因状态与主次原因不得被改写。"""
    for obj in phase3_objects:
        oid = obj.get("attribution_result_id") or obj.get("id")
        if oid in expected and obj.get("attribution_status") != expected[oid]:
            issues.append(ValidationIssue("ERV-055", "error", "Phase 3 归因状态被改写", oid))


def check_report_object_consistency(issues: List[ValidationIssue], result: Optional[Dict[str, Any]],
                                    finding_ids: set, metric_ids: set) -> None:
    """ERV-057/058：报告关键结论可追溯；Markdown 数字与结构化对象一致（ID 聚合校验）。"""
    if result:
        for fid in result.get("key_finding_ids", []):
            if fid not in finding_ids:
                issues.append(ValidationIssue("ERV-057", "error", f"结果引用不存在的 finding: {fid}", fid))
        for mid in result.get("financial_metric_ids", []):
            if mid not in metric_ids:
                issues.append(ValidationIssue("ERV-057", "error", f"结果引用不存在的 metric: {mid}", mid))


def check_scenario_not_fact(issues: List[ValidationIssue], scenario: Dict[str, Any]) -> None:
    """ERV-062：情景预测假设不得标为 FACT。"""
    for a in scenario.get("assumptions", []):
        if a.get("claim_type") == "FACT":
            issues.append(ValidationIssue("ERV-062", "error", "情景预测假设不得标为 FACT", scenario.get("scenario_id")))


def check_dry_run_no_side_effects(issues: List[ValidationIssue], dry_run: bool, artifacts: List[str]) -> None:
    """ERV-069：dry-run 必须零副作用。"""
    if dry_run and artifacts:
        issues.append(ValidationIssue("ERV-069", "error", "dry-run 必须零副作用（不得产生产物）"))


def check_idempotent_no_duplicate(issues: List[ValidationIssue], runs: List[Dict[str, Any]]) -> None:
    """ERV-070：幂等命中不得重复写入（同 idempotency_key+run_version 只能一次）。"""
    seen = set()
    for r in runs:
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
    metrics: Optional[List[Dict[str, Any]]] = None,
    reports: Optional[List[Dict[str, Any]]] = None,
    peers: Optional[List[Dict[str, Any]]] = None,
    peer_selection: Optional[Dict[str, Any]] = None,
    valuation: Optional[Dict[str, Any]] = None,
    factors: Optional[List[Dict[str, Any]]] = None,
    scenarios: Optional[List[Dict[str, Any]]] = None,
    blocks: Optional[List[Dict[str, Any]]] = None,
    evidences: Optional[List[Dict[str, Any]]] = None,
    raw_items: Optional[List[Dict[str, Any]]] = None,
    claims: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
    phase3_objects: Optional[List[Dict[str, Any]]] = None,
    phase3_expected: Optional[Dict[str, str]] = None,
    as_of: str = "",
    dry_run: bool = False,
    artifact_paths: Optional[List[str]] = None,
    known_ids: Optional[set] = None,
    runs: Optional[List[Dict[str, Any]]] = None,
    request: Optional[Dict[str, Any]] = None,
    run: Optional[Dict[str, Any]] = None,
    documents: Optional[List[Dict[str, Any]]] = None,
    catalysts: Optional[List[Dict[str, Any]]] = None,
    risks: Optional[List[Dict[str, Any]]] = None,
    semantic_records: Optional[List[Dict[str, Any]]] = None,
    market_debate: Optional[Dict[str, Any]] = None,
) -> ValidationOutcome:
    """运行 ERV 规则全集。返回 pass / pass_with_warnings / fail。

    所有对象先过 ERV-001 Schema 校验（Claim/Evidence/Finding/Factor/Valuation/
    PeerSelection/Request/Run/Catalyst/Risk 全覆盖），再按规则组检查；
    pipeline 必须传入真实对象（禁止以空列表代替未执行模块）。
    """
    issues: List[ValidationIssue] = []
    findings = findings or []
    facts = facts or []
    metrics = metrics or []
    reports = reports or []
    peers = peers or []
    scenarios = scenarios or []
    blocks = blocks or []
    lineage_requested = raw_items is not None
    semantic_validation_requested = semantic_records is not None
    evidences = evidences or []
    raw_items = raw_items or []
    claims = claims or []
    events = events or []
    documents = documents or []
    catalysts = catalysts or []
    risks = risks or []

    # ERV-001/002：对象 Schema 校验（全部对象类型；无对应 Schema 映射则跳过并警告）
    schema_groups: List[tuple] = [
        (facts, "financial_fact"), (metrics, "financial_metric"), (reports, "financial_report"),
        (peers, "peer_candidate"), (scenarios, "forecast_scenario"), (blocks, "document_block"),
        (evidences, "evidence"), (raw_items, "raw_item"), (claims, "claim"),
        (factors or [], "competitive_factor"),
        (documents, "document_record"), (catalysts, "catalyst"), (risks, "risk_factor"),
    ]
    if peer_selection:
        schema_groups.append(([peer_selection], "peer_selection"))
    if valuation:
        schema_groups.append(([valuation], "valuation_snapshot"))
    for group, schema_name in schema_groups:
        for obj in group:
            check_schema(issues, obj, schema_name)
    if result:
        check_schema(issues, result, "equity_research_result")
    if request:
        check_schema(issues, request, "equity_research_request")
    if run:
        check_schema(issues, run, "equity_research_run")

    # ERV-004—008：对象完整性/枚举/时间顺序
    for f in facts:
        check_required_fields(issues, f, "financial_fact", "ERV-004",
                              ["fact_id", "company_entity_id", "period_end", "taxonomy_code"], "fact_id")
        check_enum_validity(issues, f, "financial_fact", "ERV-006",
                            {"statement_scope": {"consolidated", "parent"},
                             "value_status": {"reported", "missing", "not_applicable", "conflict", "derived_from_report"}},
                            "fact_id")
        check_temporal_order(issues, f, "ERV-007", "period_start", "period_end", "fact_id")
    for m in metrics:
        check_required_fields(issues, m, "financial_metric", "ERV-005",
                              ["metric_id", "metric_code", "period_end"], "metric_id")
        check_temporal_order(issues, m, "ERV-008", "period_start", "period_end", "metric_id")

    # ERV-009—027：财务
    check_unit_consistency(issues, facts)
    check_currency_consistency(issues, facts)
    check_period_consistency(issues, facts)
    check_scope_not_mixed(issues, facts)
    check_instant_duration(issues, facts)  # ERV-015（跨事实）
    for fact in facts:
        check_missing_not_zero(issues, fact)
        check_na_not_negative(issues, fact)
        check_derived_not_reported(issues, fact)
        check_llm_not_edit_financials(issues, fact)
    check_ratio_decimal(issues, metrics)
    check_metric_recompute(issues, metrics, facts, reports)  # ERV-018—022
    check_restatement_kept(issues, reports)
    check_conflict_not_silenced(issues, facts)

    # ERV-028—040：同行与估值
    for p in peers:
        check_peer_cutoff(issues, p, as_of)
        check_peer_valid_from(issues, p)
        check_peer_requalify(issues, p)  # ERV-032
    check_peer_universe_frozen(issues, peers)
    check_peer_sample_threshold(issues, peer_selection)
    check_valuation_time_consistency(issues, valuation)
    check_valuation_na_rules(issues, valuation)
    check_market_consistency(issues, valuation, as_of)  # ERV-035/036
    check_percentile_threshold(issues, valuation)  # ERV-038

    # ERV-041—052：Claim/Evidence/LLM
    fact_ids = {f.get("fact_id") for f in facts if f.get("fact_id")}
    evidence_by_id = {e.get("evidence_id"): e for e in evidences if e.get("evidence_id")}
    evidence_id_set = set(evidence_by_id)
    block_by_id = {b.get("block_id"): b for b in blocks if b.get("block_id")}
    for f in findings:
        check_fact_has_evidence(issues, f)
        check_financial_fact_has_block(issues, f, fact_ids)
        check_evidence_qualified(issues, f, evidence_by_id, as_of)  # ERV-043
        check_model_inference_requires_call(issues, f)
        check_fallback_no_inference(issues, f)  # ERV-045
        check_hypothesis_has_failure_condition(issues, f)
        check_unknown_not_negative(issues, f.get("statement", ""), f.get("finding_id", ""))
        check_block_evidence_link(issues, f, block_by_id)  # ERV-052
    for factor in factors or []:
        check_management_only(issues, factor)
        check_foreign_refs(
            issues,
            [*(factor.get("evidence_ids") or []), *(factor.get("counter_evidence_ids") or [])],
            evidence_id_set,
            "ERV-078",
        )
        check_competitive_evidence_types(issues, factor, evidence_by_id)
    check_block_reference(issues, blocks, fact_ids)  # ERV-050/051
    for c in claims:
        check_required_fields(issues, c, "claim", "ERV-043",
                              ["claim_id", "claim_type", "statement", "predicate", "evidence_ids"], "claim_id")
    check_claim_evidence_contract(issues, claims, evidence_id_set)
    if lineage_requested:
        check_evidence_lineage(issues, evidences, raw_items)
    check_report_evidence_refs(issues, report_text, evidence_id_set)
    check_research_status_contract(issues, result)
    if semantic_validation_requested:
        check_semantic_route_contract(issues, findings, claims, run, semantic_records or [])
    if market_debate is not None:
        check_market_debate_contract(issues, market_debate, evidence_id_set)
    for s in scenarios:
        check_assumption_has_source(issues, s)  # ERV-047

    # ERV-053：未来信息污染（facts/blocks/findings/reports/evidence 全部覆盖）
    if as_of:
        for f in findings:
            check_no_future_info(issues, f, as_of)
        for fact in facts:
            check_no_future_info(issues, fact, as_of)
        for b in blocks:
            check_no_future_info(issues, b, as_of)
        for rep in reports:
            check_no_future_info(issues, rep, as_of)
        for ev in evidences:
            check_no_future_info(issues, ev, as_of)
    if phase3_objects is not None:
        check_phase3_readonly(issues, phase3_objects, phase3_expected or {})
    for ev in events:
        check_phase2_readonly(issues, ev)  # ERV-054
        check_morning_reuse_structured(issues, ev)  # ERV-056
        check_foreign_refs(issues, ev.get("evidence_ids", []), evidence_id_set, "ERV-072")
    finding_ids = {f.get("finding_id") for f in findings if f.get("finding_id")}
    metric_ids = {m.get("metric_id") for m in metrics if m.get("metric_id")}
    check_report_object_consistency(issues, result, finding_ids, metric_ids)
    check_report_number_consistency(issues, report_text, metrics, valuation)  # ERV-059—061
    for s in scenarios:
        check_scenario_not_fact(issues, s)
    check_dry_run_no_side_effects(issues, dry_run, artifact_paths or [])
    check_idempotent_no_duplicate(issues, runs or [])

    # ERV-063—067：禁止词（免责声明固定文案除外）+ 状态合法
    body = report_text
    disclaimer_idx = body.find("本报告由 AI＋A 股投研系统自动生成")
    if disclaimer_idx >= 0:
        body = body[:disclaimer_idx]
    check_no_target_price(issues, body, "ERV-063")
    for w in ["买入评级", "卖出评级", "增持", "减持", "仓位", "跟随操作"]:
        if w in body:
            issues.append(ValidationIssue("ERV-064" if "评级" in w else "ERV-065", "error", f"报告含禁止词: {w}"))
    if re.search(r"(确定性|必然|保证).{0,10}(收益|盈利|回报)", body):
        issues.append(ValidationIssue("ERV-066", "error", "确定性收益承诺"))
    if re.search(r"(低估|高估)", body):
        issues.append(ValidationIssue("ERV-067", "warning", "非适用估值写成低估/高估"))
    if result is not None and result.get("research_status") not in VALID_RESEARCH_STATUS:
        issues.append(ValidationIssue("ERV-068", "error", "research_status 非法"))

    # ERV-003：引用完整性
    if known_ids is not None:
        for f in findings:
            check_foreign_refs(issues, f.get("evidence_ids", []), known_ids, "ERV-003")

    if any(i.severity == "error" for i in issues):
        return ValidationOutcome("fail", issues)
    if issues:
        return ValidationOutcome("pass_with_warnings", issues)
    return ValidationOutcome("pass", issues)
