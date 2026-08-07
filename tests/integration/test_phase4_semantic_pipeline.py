"""Fake Provider 经统一 LlmClient 进入 Phase 4 正式 Pipeline。"""
from __future__ import annotations

import json

from research_os.equity_research.pipeline import EquityResearchPipeline
from research_os.llm.client import LlmClient
from research_os.models import Evidence, Event, RawItem
from research_os.storage import Database
from tests.fixtures.samples import valid_evidence, valid_event, valid_raw_item


class SemanticProvider:
    def __init__(self, required_evidence_type="official_disclosure"):
        self.required_evidence_type = required_evidence_type

    def complete_json(self, request, output_schema):
        evidence_id = request.input_evidence_ids[0]
        task_name = request.module.rsplit(".", 1)[-1]
        if task_name == "competitive_factor_candidates":
            output = {
                "factor_id": "factor-1", "company_entity_id": "company:600519.SH",
                "factor_type": "brand", "direction": "advantage", "statement": "品牌因素待持续验证",
                "business_segment_ids": [], "mechanism": "消费者认知与渠道覆盖",
                "required_evidence_types": [self.required_evidence_type], "evidence_ids": [evidence_id],
                "counter_evidence_ids": [], "management_only": False, "confidence": 0.6,
                "status": "weakly_supported", "valid_from": "2026-08-01", "valid_to": None,
                "version": 1, "created_at": "2026-08-01T00:00:00",
            }
        elif task_name == "catalyst_candidates":
            output = {
                "catalyst_id": "catalyst-semantic-1", "company_entity_id": "company:600519.SH",
                "event_id": None, "source_phase": "phase4", "catalyst_type": "capacity",
                "description": "已公告产能项目进展需持续核验", "claim_type": "MODEL_INFERENCE",
                "announcement_status": "announced", "time_window_start": None,
                "time_window_end": None, "impact_mechanism": "潜在供给变化",
                "business_segment_ids": [], "prerequisites": ["项目按公告推进"],
                "invalidation_conditions": ["项目取消"], "evidence_ids": [evidence_id],
                "confidence": 0.6, "status": "active", "widely_known": "unknown",
                "phase3_attribution_result_id": None, "version": 1,
                "created_at": "2026-08-01T00:00:00", "updated_at": "2026-08-01T00:00:00",
            }
        elif task_name == "risk_candidates":
            output = {
                "risk_id": "risk-semantic-1", "company_entity_id": "company:600519.SH",
                "event_id": None, "source_phase": "phase4", "risk_type": "market",
                "description": "需求下降与市场波动风险待验证", "claim_type": "MODEL_INFERENCE",
                "time_window_start": None, "time_window_end": None,
                "impact_mechanism": "可能影响收入预期", "business_segment_ids": [],
                "triggers": ["需求下降"], "mitigants": [],
                "invalidation_conditions": ["需求数据持续改善"], "evidence_ids": [evidence_id],
                "counter_evidence_ids": [], "confidence": 0.6, "status": "active",
                "widely_known": "unknown", "phase3_attribution_result_id": None,
                "version": 1, "created_at": "2026-08-01T00:00:00",
                "updated_at": "2026-08-01T00:00:00",
            }
        else:
            finding_type = {
                "business_description_normalization": "business_analysis",
                "management_statement_summary": "governance",
                "counter_evidence_organizing": "controversy",
                "research_questions": "research_question",
            }[task_name]
            obj = {
                "core_products_or_services": ["产品A"], "business_segments": ["板块A"],
                "revenue_or_profit_links": ["待验证"], "customers_or_applications": ["应用A"],
                "upstream_downstream": ["上游原料"], "unknowns": [],
                "challenged_claim": "品牌因素", "strength": "medium",
                "unresolved_questions": ["持续性"], "why_important": "影响竞争判断",
                "required_data": ["渠道数据"], "verification_method": "核查披露",
                "priority": "high", "current_status": "unverified",
                "speaker": "董事长", "role": "董事长",
                "published_at": "2026-07-31T23:00:00+08:00",
                "statement": "管理层表示主营业务与产能项目按计划推进",
                "topic": "业务与产能", "company_view": "项目按计划推进",
                "possible_bias": "公司管理层自述",
                "unresolved_difference": "公告进展与需求压力并存",
                "next_verification_data": ["后续销量与项目进度"],
            }
            output = {
                "finding_id": f"finding-{task_name}", "request_id": request.prompt.split("request_id: ", 1)[1].splitlines()[0],
                "company_entity_id": "company:600519.SH", "finding_type": finding_type,
                "title": task_name, "statement": f"{task_name} 的证据约束输出",
                "claim_type": "SOURCE_OPINION" if task_name == "management_statement_summary" else "MODEL_INFERENCE",
                "predicate": task_name, "object": obj,
                "as_of": "2026-08-01T00:00:00", "evidence_ids": [evidence_id],
                "supporting_object_ids": [],
                "counter_evidence_ids": [evidence_id] if task_name == "counter_evidence_organizing" else [],
                "confidence": 0.6, "support_level": "inferred", "status": "supported",
                "invalidation_conditions": ["后续披露与当前证据矛盾"], "materiality": "medium",
                "section_id": "s8", "model_route": None, "version": 1,
                "created_at": "2026-08-01T00:00:00",
            }
        return {"ok": True, "provider": "semantic-fake", "model_id": "fake-flash", "output": output}


def _financial_file(tmp_path):
    header = (
        "company_entity_id,period_start,period_end,fiscal_year,report_type,statement_scope,"
        "statement_type,taxonomy_code,label_raw,raw_value,unit_scale,currency"
    )
    rows = [header]
    for year in (2024, 2025):
        prefix = f"company:600519.SH,{year}-01-01,{year}-12-31,{year},annual,consolidated"
        rows.extend([
            f"{prefix},income_statement,revenue,营业收入,{1000000 + year},1,CNY",
            f"{prefix},income_statement,cost_of_sales,营业成本,{500000 + year},1,CNY",
            f"{prefix},income_statement,net_profit,净利润,{200000 + year},1,CNY",
        ])
    path = tmp_path / "financial.csv"
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def _seed_official_event(db, *, evidence_type="official_disclosure"):
    raw = RawItem(**valid_raw_item(
        content_excerpt=("公司主营白酒业务，董事长表示产能项目按公告推进；品牌和渠道构成竞争因素，"
                         "但需求下降与市场波动风险仍存在不确定性。"),
        published_at="2026-07-31T23:00:00+08:00",
        retrieved_at="2026-07-31T23:01:00+08:00",
    ))
    evidence = Evidence(**valid_evidence(
        raw_item_id=raw.raw_item_id, evidence_type=evidence_type,
        source_id=raw.source_id, title=raw.title, publisher=raw.publisher, url=raw.url,
        published_at=raw.published_at, retrieved_at=raw.retrieved_at,
        source_tier="S" if evidence_type == "official_disclosure" else "A",
        excerpt=("公司主营白酒业务，董事长表示产能项目按公告推进；品牌和渠道构成竞争因素，"
                 "但需求下降与市场波动风险仍存在不确定性。"),
    ))
    event = Event(**valid_event(
        event_time="2026-07-31T23:00:00+08:00",
        announced_at="2026-07-31T23:00:00+08:00",
        evidence_ids=[evidence.evidence_id],
    ))
    db.upsert(raw)
    db.upsert(evidence)
    db.upsert(event)


def test_fake_provider_semantic_outputs_enter_formal_artifacts(tmp_path):
    db = Database(tmp_path / "research.db")
    db.initialize()
    _seed_official_event(db)
    client = LlmClient(provider=SemanticProvider(), configured=True, db=db)
    pipeline = EquityResearchPipeline(tmp_path, db, llm_client=client)
    try:
        outcome = pipeline.run({
            "entity": "600519.SH", "date": "2026-08-01", "as_of": "2026-08-01T00:00:00",
            "financial_files": [str(_financial_file(tmp_path))], "include_valuation": False,
            "depth": "deep",
        })
    finally:
        db.close()
    assert outcome.exit_code == 0
    assert outcome.model_route["llm_called"] is True
    assert outcome.model_route["semantic_tasks_integrated"] == 7
    assert outcome.research_status != "success", "S 级事件不得掩盖 Tier C 核心财务来源"
    run_dir = tmp_path / "reports" / "runs"
    actual_run = next(run_dir.iterdir())
    semantic = json.loads((actual_run / "semantic_results.json").read_text(encoding="utf-8"))
    assert all(record["validation_status"] == "pass" for record in semantic)
    assert json.loads((actual_run / "business_analysis.json").read_text(encoding="utf-8"))["status"] == "covered"
    assert json.loads((actual_run / "competitive_landscape.json").read_text(encoding="utf-8"))["status"] == "covered"
    assert json.loads((actual_run / "management_statements.json").read_text(encoding="utf-8"))
    assert json.loads((actual_run / "management_opinions.json").read_text(encoding="utf-8"))
    assert json.loads((actual_run / "catalysts.json").read_text(encoding="utf-8"))
    assert json.loads((actual_run / "risks.json").read_text(encoding="utf-8"))
    result_payload = json.loads(
        (actual_run / "equity_research_result.json").read_text(encoding="utf-8"))
    assert result_payload["coverage"]["source_quality"]["core_financial"] is False


def test_competition_required_evidence_type_must_match_actual_type(tmp_path):
    db = Database(tmp_path / "research.db")
    db.initialize()
    _seed_official_event(db, evidence_type="company_official")
    client = LlmClient(provider=SemanticProvider("official_disclosure"), configured=True, db=db)
    pipeline = EquityResearchPipeline(tmp_path, db, llm_client=client)
    try:
        outcome = pipeline.run({
            "entity": "600519.SH", "date": "2026-08-01", "as_of": "2026-08-01T00:00:00",
            "financial_files": [str(_financial_file(tmp_path))], "include_valuation": False,
            "depth": "deep",
        })
    finally:
        db.close()
    assert outcome.exit_code == 0
    run_dir = next((tmp_path / "reports" / "runs").iterdir())
    semantic = json.loads((run_dir / "semantic_results.json").read_text(encoding="utf-8"))
    competition = next(r for r in semantic if r["task_name"] == "competitive_factor_candidates")
    assert competition["validation_status"] == "rejected"
    assert "类型不一致" in competition["fallback_reason"]
