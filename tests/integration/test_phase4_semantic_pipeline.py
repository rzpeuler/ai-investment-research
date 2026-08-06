"""Fake Provider 经统一 LlmClient 进入 Phase 4 正式 Pipeline。"""
from __future__ import annotations

import json

from research_os.equity_research.pipeline import EquityResearchPipeline
from research_os.llm.client import LlmClient
from research_os.storage import Database


class SemanticProvider:
    def complete_json(self, request, output_schema):
        evidence_id = request.input_evidence_ids[0]
        task_name = request.module.rsplit(".", 1)[-1]
        if task_name == "competitive_factor_candidates":
            output = {
                "factor_id": "factor-1", "company_entity_id": "company:600519.SH",
                "factor_type": "brand", "direction": "advantage", "statement": "品牌因素待持续验证",
                "business_segment_ids": [], "mechanism": "消费者认知与渠道覆盖",
                "required_evidence_types": ["official_disclosure"], "evidence_ids": [evidence_id],
                "counter_evidence_ids": [], "management_only": False, "confidence": 0.6,
                "status": "weakly_supported", "valid_from": "2026-08-01", "valid_to": None,
                "version": 1, "created_at": "2026-08-01T00:00:00",
            }
        else:
            finding_type = {
                "business_description_normalization": "business_analysis",
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
            }
            output = {
                "finding_id": f"finding-{task_name}", "request_id": request.prompt.split("request_id: ", 1)[1].splitlines()[0],
                "company_entity_id": "company:600519.SH", "finding_type": finding_type,
                "title": task_name, "statement": f"{task_name} 的证据约束输出",
                "claim_type": "MODEL_INFERENCE", "predicate": task_name, "object": obj,
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


def test_fake_provider_semantic_outputs_enter_formal_artifacts(tmp_path):
    db = Database(tmp_path / "research.db")
    db.initialize()
    client = LlmClient(provider=SemanticProvider(), configured=True, db=db)
    pipeline = EquityResearchPipeline(tmp_path, db, llm_client=client)
    try:
        outcome = pipeline.run({
            "entity": "600519.SH", "date": "2026-08-01", "as_of": "2026-08-01T00:00:00",
            "financial_files": [str(_financial_file(tmp_path))], "include_valuation": False,
        })
    finally:
        db.close()
    assert outcome.exit_code == 0
    assert outcome.model_route["llm_called"] is True
    assert outcome.model_route["semantic_tasks_integrated"] == 4
    run_dir = tmp_path / "reports" / "runs"
    actual_run = next(run_dir.iterdir())
    semantic = json.loads((actual_run / "semantic_results.json").read_text(encoding="utf-8"))
    assert all(record["validation_status"] == "pass" for record in semantic)
    assert json.loads((actual_run / "business_analysis.json").read_text(encoding="utf-8"))["status"] == "covered"
    assert json.loads((actual_run / "competitive_landscape.json").read_text(encoding="utf-8"))["status"] == "covered"
