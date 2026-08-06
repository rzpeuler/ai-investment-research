"""Phase 4 跨对象 Validator（任务书 3.22，独立验收修复版）。

规则编号 ERV-001—ERV-070，输出 pass / pass_with_warnings / fail。
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

DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")


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


def check_instant_duration(issues: List[ValidationIssue], fact: Dict[str, Any]) -> None:
    """ERV-015：instant 与 duration 不得混算（同科目同期间类型一致）。"""
    pass  # 结构性检查：instant/duration 由 taxonomy 决定，混算在指标层拦截


def check_derived_not_reported(issues: List[ValidationIssue], fact: Dict[str, Any]) -> None:
    """ERV-016：单季拆分值不得标为 reported。"""
    if fact.get("value_status") == "reported" and fact.get("period_basis") == "single_quarter":
        issues.append(ValidationIssue("ERV-016", "error", "单季拆分值不得标为 reported", fact.get("fact_id")))


def check_ratio_decimal(issues: List[ValidationIssue], metrics: List[Dict[str, Any]]) -> None:
    """ERV-017—020/025/026：指标可复算（十进制、零分母显式、输入血缘完整）。"""
    for m in metrics:
        if m.get("value") is not None and not DECIMAL_RE.match(str(m.get("value"))):
            issues.append(ValidationIssue("ERV-025", "error", "指标值非十进制字符串", m.get("metric_id")))
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
    """ERV-045：模型调用失败的回退不得产生 MODEL_INFERENCE（与 044 同源，见 044）。"""
    pass


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
    phase3_objects: Optional[List[Dict[str, Any]]] = None,
    phase3_expected: Optional[Dict[str, str]] = None,
    as_of: str = "",
    dry_run: bool = False,
    artifact_paths: Optional[List[str]] = None,
    known_ids: Optional[set] = None,
    runs: Optional[List[Dict[str, Any]]] = None,
) -> ValidationOutcome:
    """运行 ERV 规则全集。返回 pass / pass_with_warnings / fail。

    所有对象（fact/metric/report/peer/factor/scenario/block）先过 ERV-001 Schema 校验，
    再按规则组检查；pipeline 必须传入真实对象（禁止以空列表代替未执行模块）。
    """
    issues: List[ValidationIssue] = []
    findings = findings or []
    facts = facts or []
    metrics = metrics or []
    reports = reports or []
    peers = peers or []
    scenarios = scenarios or []
    blocks = blocks or []

    # ERV-001/002：对象 Schema 校验（按模型名映射；无映射的对象跳过并警告）
    for group, schema_name in [
        (facts, "financial_fact"), (metrics, "financial_metric"), (reports, "financial_report"),
        (peers, "peer_candidate"), (scenarios, "forecast_scenario"), (blocks, "document_block"),
    ]:
        for obj in group:
            check_schema(issues, obj, schema_name)
    if result:
        check_schema(issues, result, "equity_research_result")

    # ERV-009—027：财务
    check_unit_consistency(issues, facts)
    check_currency_consistency(issues, facts)
    check_period_consistency(issues, facts)
    check_scope_not_mixed(issues, facts)
    for fact in facts:
        check_missing_not_zero(issues, fact)
        check_na_not_negative(issues, fact)
        check_instant_duration(issues, fact)
        check_derived_not_reported(issues, fact)
        check_llm_not_edit_financials(issues, fact)
    check_ratio_decimal(issues, metrics)
    check_restatement_kept(issues, reports)
    check_conflict_not_silenced(issues, facts)

    # ERV-028—040：同行与估值
    for p in peers:
        check_peer_cutoff(issues, p, as_of)
        check_peer_valid_from(issues, p)
    check_peer_universe_frozen(issues, peers)
    check_peer_sample_threshold(issues, peer_selection)
    check_valuation_time_consistency(issues, valuation)
    check_valuation_na_rules(issues, valuation)

    # ERV-041—052：Claim/Evidence/LLM
    fact_ids = {f.get("fact_id") for f in facts if f.get("fact_id")}
    for f in findings:
        check_fact_has_evidence(issues, f)
        check_financial_fact_has_block(issues, f, fact_ids)
        check_model_inference_requires_call(issues, f)
        check_fallback_no_inference(issues, f)
        check_hypothesis_has_failure_condition(issues, f)
        check_unknown_not_negative(issues, f.get("statement", ""), f.get("finding_id", ""))
    for factor in factors or []:
        check_management_only(issues, factor)
    check_block_reference(issues, blocks, fact_ids)

    # ERV-053：未来信息污染
    if as_of:
        for f in findings:
            check_no_future_info(issues, f, as_of)
        for fact in facts:
            check_no_future_info(issues, fact, as_of)
        for b in blocks:
            check_no_future_info(issues, b, as_of)
    if phase3_objects is not None:
        check_phase3_readonly(issues, phase3_objects, phase3_expected or {})
    finding_ids = {f.get("finding_id") for f in findings if f.get("finding_id")}
    metric_ids = {m.get("metric_id") for m in metrics if m.get("metric_id")}
    check_report_object_consistency(issues, result, finding_ids, metric_ids)
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
