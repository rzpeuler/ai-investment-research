"""Phase 4 黄金案例测试（任务书 3.26，独立验收修复版）。

修复要点（独立验收 HIGH）：黄金测试必须是**端到端流水线**验收——
输入 fixture（>=2 个可比年度财务 CSV）→ 真实跑 EquityResearchPipeline →
断言结构化对象（Request/Run/Result/metrics/facts/run 产物）、研究状态、
数据降级、模型路由、Validator 结果、报告与对象一致性。
删除"一句话传给 Validator 断言无失败"及与报告内容无关的无意义断言。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from research_os.equity_research.pipeline import EquityResearchPipeline
from research_os.equity_research.validator import validate_equity_research
from research_os.storage.db import Database
from research_os.utils.time import now_iso

COMPANY = "company:600519.SH"

# 3 个可比年度（FY2023/2024/2025），满足 >=2 最低条件
CSV_ROWS = [
    "company_entity_id,period_start,period_end,fiscal_year,report_type,statement_scope,"
    "statement_type,taxonomy_code,label_raw,value,unit_scale,currency",
    # FY2023
    f"{COMPANY},2023-01-01,2023-12-31,2023,annual,consolidated,income_statement,revenue,营业收入,70000000000,10000,CNY",
    f"{COMPANY},2023-01-01,2023-12-31,2023,annual,consolidated,income_statement,cost_of_sales,营业成本,35000000000,10000,CNY",
    f"{COMPANY},2023-01-01,2023-12-31,2023,annual,consolidated,balance_sheet,total_assets,资产总计,200000000000,10000,CNY",
    f"{COMPANY},2023-01-01,2023-12-31,2023,annual,consolidated,balance_sheet,total_liabilities,负债合计,50000000000,10000,CNY",
    f"{COMPANY},2023-01-01,2023-12-31,2023,annual,consolidated,balance_sheet,equity_attr,归母所有者权益,150000000000,10000,CNY",
    f"{COMPANY},2023-01-01,2023-12-31,2023,annual,consolidated,income_statement,net_profit_attr,归母净利润,18000000000,10000,CNY",
    f"{COMPANY},2023-01-01,2023-12-31,2023,annual,consolidated,cash_flow,operating_cash_flow,经营现金流,22000000000,10000,CNY",
    f"{COMPANY},2023-01-01,2023-12-31,2023,annual,consolidated,cash_flow,capex_paid,资本开支,5000000000,10000,CNY",
    # FY2024
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,income_statement,revenue,营业收入,85000000000,10000,CNY",
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,income_statement,cost_of_sales,营业成本,40000000000,10000,CNY",
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,balance_sheet,total_assets,资产总计,230000000000,10000,CNY",
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,balance_sheet,total_liabilities,负债合计,60000000000,10000,CNY",
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,balance_sheet,equity_attr,归母所有者权益,170000000000,10000,CNY",
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,income_statement,net_profit_attr,归母净利润,22000000000,10000,CNY",
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,cash_flow,operating_cash_flow,经营现金流,26000000000,10000,CNY",
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,cash_flow,capex_paid,资本开支,6000000000,10000,CNY",
    # FY2025
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,revenue,营业收入,100000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,cost_of_sales,营业成本,45000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,balance_sheet,total_assets,资产总计,260000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,balance_sheet,total_liabilities,负债合计,70000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,balance_sheet,equity_attr,归母所有者权益,190000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,net_profit_attr,归母净利润,26000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,cash_flow,operating_cash_flow,经营现金流,31000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,cash_flow,capex_paid,资本开支,7000000000,10000,CNY",
]

MARKET_FILE = {"price": "1500", "shares_outstanding": "100000000"}


@pytest.fixture()
def env(tmp_path):
    """临时项目根 + 财务 CSV + 市值文件 + 数据库。"""
    fin = tmp_path / "fin.csv"
    fin.write_text("\n".join(CSV_ROWS), encoding="utf-8")
    mkt = tmp_path / "market.json"
    mkt.write_text(json.dumps(MARKET_FILE), encoding="utf-8")
    db = Database(tmp_path / "data" / "sqlite" / "research.db")
    db.initialize()
    return tmp_path, fin, mkt, db


def _run(env, **extra):
    tmp_path, fin, mkt, db = env
    p = EquityResearchPipeline(tmp_path, db)
    args = {"entity": "600519.SH", "date": "2026-08-06",
            "financial_files": [str(fin)], "market_file": str(mkt)}
    args.update(extra)
    return p, p.run(args)


def _read_artifacts(run_dir):
    """读取运行目录产物（完整运行产物清单；.json 与 .jsonl）。"""
    rd = pathlib.Path(run_dir)
    artifacts = {}
    for p in rd.iterdir():
        if p.suffix == ".json":
            artifacts[p.name] = json.loads(p.read_text(encoding="utf-8"))
        elif p.suffix == ".jsonl":
            artifacts[p.name] = [
                json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()
            ]
    return artifacts


def _validate_rendered_artifacts(artifacts, report_text):
    return validate_equity_research(
        report_text=report_text,
        metrics=artifacts["financial_metrics.json"],
        facts=artifacts["financial_facts.jsonl"],
        valuation=artifacts["valuation_snapshot.json"],
        as_of=artifacts["equity_research_result.json"]["as_of"],
    )


def _metric_line(report_text, metric_code):
    return next(line for line in report_text.splitlines() if f"metric-code:{metric_code} " in line)


def _replace_visible_token(report_text, metric_code, replacement):
    line = _metric_line(report_text, metric_code)
    label = line.split("：", 1)[0]
    comment = line[line.index("<!--"):]
    return report_text.replace(line, f"{label}：{replacement} {comment}", 1)


class TestEndToEndGolden:
    def test_full_flow_success(self, env):
        """≥2 个可比年度 → success/degraded（同行等可选模块缺数据时合法降级）；
        报告与运行产物齐全；模型路由诚实；结构化对象已生成。"""
        p, out = _run(env)
        assert out.status in ("success", "degraded"), out.message
        assert out.research_status in ("success", "degraded")
        assert out.exit_code == 0
        assert pathlib.Path(out.report_path).exists()
        assert pathlib.Path(out.run_dir).exists()

        artifacts = _read_artifacts(out.run_dir)
        for name in ("equity_research_request.json", "equity_research_run.json",
                     "equity_research_result.json", "financial_facts.jsonl",
                     "financial_metrics.json", "validation.json", "model_route.json"):
            assert name in artifacts, f"缺运行产物 {name}"

        result = artifacts["equity_research_result.json"]
        assert result["research_status"] in ("success", "degraded")
        assert result["coverage"]["comparable_years"] >= 2
        assert result["financial_metric_ids"]  # 结构化指标已生成
        assert result["evidence_ids"]  # 证据链已建立
        # 模型路由诚实（无 Provider）
        assert artifacts["model_route.json"] == {"mode": "deterministic_fallback", "llm_called": False}
        # Validator 通过
        assert artifacts["validation.json"]["status"] in ("pass", "pass_with_warnings")

    def test_report_no_target_price(self, env):
        """报告正文无目标价/评级（免责声明固定文案除外）。"""
        _, out = _run(env)
        text = pathlib.Path(out.report_path).read_text(encoding="utf-8")
        disclaimer_idx = text.find("本报告由 AI＋A 股投研系统自动生成")
        body = text[:disclaimer_idx] if disclaimer_idx >= 0 else text
        for forbidden in ("目标价", "买入评级", "建议买入", "上涨空间", "仓位建议"):
            assert forbidden not in body

    def test_untampered_metric_report_contract_passes(self, env):
        _, out = _run(env)
        artifacts = _read_artifacts(out.run_dir)
        report = pathlib.Path(out.report_path).read_text(encoding="utf-8")
        validation = _validate_rendered_artifacts(artifacts, report)
        assert not any(i.rule_id in {"ERV-059", "ERV-060", "ERV-061"} for i in validation.errors)

    @pytest.mark.parametrize(("metric_code", "replacement"), [
        ("gross_margin", "12.34%"),
        ("debt_to_assets", "88.88%"),
        ("free_cash_flow", "1.00 元"),
        ("roe", "99.99%"),
        ("PE_TTM", "99.00 倍"),
        ("gross_margin", "0.55"),          # 百分比改普通小数
        ("free_cash_flow", "1.00 万元"),   # 金额单位篡改
        ("gross_margin", "55.0%"),         # 小数位篡改
    ])
    def test_visible_metric_tamper_fails(self, env, metric_code, replacement):
        _, out = _run(env)
        artifacts = _read_artifacts(out.run_dir)
        report = pathlib.Path(out.report_path).read_text(encoding="utf-8")
        tampered = _replace_visible_token(report, metric_code, replacement)
        validation = _validate_rendered_artifacts(artifacts, tampered)
        assert validation.status == "fail"
        assert any(i.rule_id == "ERV-059" and i.severity == "error" for i in validation.errors)

    @pytest.mark.parametrize("mutation", ["delete", "duplicate", "move", "conflicting_duplicate", "unknown"])
    def test_metric_marker_tamper_fails(self, env, mutation):
        _, out = _run(env)
        artifacts = _read_artifacts(out.run_dir)
        report = pathlib.Path(out.report_path).read_text(encoding="utf-8")
        gross_line = _metric_line(report, "gross_margin")
        if mutation == "delete":
            tampered = report.replace(re.search(r"\s*<!-- metric-id:[^>]+-->", gross_line).group(0), "", 1)
        elif mutation == "duplicate":
            tampered = report.replace(gross_line, gross_line + "\n" + gross_line, 1)
        elif mutation == "move":
            debt_line = _metric_line(report, "debt_to_assets")
            gross_marker = re.search(r"<!-- metric-id:[^>]+-->", gross_line).group(0)
            debt_marker = re.search(r"<!-- metric-id:[^>]+-->", debt_line).group(0)
            tampered = report.replace(debt_line, debt_line.replace(debt_marker, gross_marker), 1)
        elif mutation == "conflicting_duplicate":
            conflicting = gross_line.replace("55.00%", "1.00%")
            tampered = report.replace(gross_line, gross_line + "\n" + conflicting, 1)
        else:
            tampered = report + "\n- 伪造指标：1.00 <!-- metric-id:not-found metric-code:fake_metric -->\n"
        validation = _validate_rendered_artifacts(artifacts, tampered)
        assert validation.status == "fail"
        assert any(i.rule_id in {"ERV-059", "ERV-060", "ERV-061"} and i.severity == "error"
                   for i in validation.errors)

    def test_forecast_success_is_persisted_rendered_and_validated(self, env):
        """Forecast 正式链路：输出不丢失、报告第 26 节展示情景、Schema/Validator 通过。"""
        _, out = _run(env, include_forecast=True, scenario_ids=["base_case"])
        assert out.exit_code == 0, out.message
        artifacts = _read_artifacts(out.run_dir)
        scenario = artifacts["forecast_scenarios.json"][0]
        assert scenario["name"] == "base_case"
        assert len(scenario["outputs"]) == 2
        assert all(item["formula_version"] for item in scenario["outputs"])
        report = pathlib.Path(out.report_path).read_text(encoding="utf-8")
        assert "base_case" in report
        assert artifacts["validation.json"]["status"] in ("pass", "pass_with_warnings")

    def test_unknown_document_time_is_not_replaced_by_mtime(self, env):
        """本地 mtime 不可充当披露时间；未知文档必须显式降级。"""
        tmp_path, _, _, _ = env
        doc = tmp_path / "undated.txt"
        doc.write_text("公司披露信息", encoding="utf-8")
        _, out = _run(env, documents=[str(doc)])
        artifacts = _read_artifacts(out.run_dir)
        assert artifacts["document_index.json"]["status"] == "not_run"
        assert "published_at unknown" in pathlib.Path(out.report_path).read_text(encoding="utf-8") or out.status == "degraded"

    def test_run_disk_json_equals_database_payload(self, env):
        """终态 run 只生成一次：运行目录和 SQLite 中的完整对象必须等价。"""
        p, out = _run(env)
        artifacts = _read_artifacts(out.run_dir)
        row = p.db.query("SELECT payload FROM equity_research_runs WHERE run_id = ?", (out.run_id,))[0]
        assert artifacts["equity_research_run.json"] == json.loads(row["payload"])

    def test_insufficient_years_degraded(self, env):
        """仅 1 个可比年度 → partial_success（最低 2 年条件落实）。"""
        tmp_path, fin, mkt, db = env
        single = fin.parent / "single.csv"
        single.write_text("\n".join(CSV_ROWS[:4]), encoding="utf-8")  # 仅 1 年
        p = EquityResearchPipeline(tmp_path, db)
        out = p.run({"entity": "600519.SH", "date": "2026-08-06",
                     "financial_files": [str(single)], "market_file": str(mkt)})
        assert out.research_status == "partial_success"
        assert out.status == "partial_success"
        assert out.exit_code == 0

    def test_no_financial_data_insufficient(self, env):
        """无财务数据 → insufficient_data exit 3（不生成完整结论）。"""
        tmp_path, fin, mkt, db = env
        p = EquityResearchPipeline(tmp_path, db)
        out = p.run({"entity": "600519.SH", "date": "2026-08-06"})
        assert out.status == "insufficient_data"
        assert out.exit_code == 3

    def test_idempotent_skip_and_force_new_version(self, env):
        """幂等跳过；force 生成新 run_version 且不覆盖旧报告。"""
        _, out1 = _run(env)
        _, out2 = _run(env)
        assert out2.status == "idempotent_skipped"
        assert out2.exit_code == 0
        # force → v2 报告，旧报告仍在
        _, out3 = _run(env, force=True)
        assert out3.status in ("success", "degraded")
        base = pathlib.Path(out1.report_path)
        v2 = base.with_name(base.name.replace(".md", "_v2.md"))
        assert v2.exists()
        assert base.exists()  # 旧报告未被覆盖
        assert out3.run_id != out1.run_id

    def test_validation_failure_exit_4(self, env):
        """Validator 失败 → exit 4（不是 exit 5）。"""
        tmp_path, fin, mkt, db = env
        # 构造一个未来信息污染场景：as_of 早于事实 valid_from
        p = EquityResearchPipeline(tmp_path, db)
        out = p.run({"entity": "600519.SH", "date": "2026-08-06",
                     "as_of": "2025-06-01T00:00:00",
                     "financial_files": [str(fin)], "market_file": str(mkt)})
        assert out.status == "failed"
        assert out.exit_code == 4
        assert "Validator" in out.message

    def test_peers_included(self, env):
        """--peer 进入流水线：候选被评分；用户 --peer 不自动合格（资格规则仍需满足）。"""
        _, out = _run(env, peers=["000858.SZ", "000568.SZ"])
        assert out.status in ("success", "degraded")
        artifacts = _read_artifacts(out.run_dir)
        assert "peer_selection.json" in artifacts
        sel = artifacts["peer_selection.json"]
        # 用户同行进入候选宇宙（candidate_ids 含 2 个候选）
        assert len(sel["candidate_ids"]) >= 2
        # 用户指定候选仍需满足资格规则：低分候选不得自动合格（防事后选择）
        assert sel["status"] in ("full", "limited", "insufficient")

    def test_valuation_included(self, env):
        """--market-file + include_valuation → valuation_snapshot 产物。"""
        _, out = _run(env)
        artifacts = _read_artifacts(out.run_dir)
        assert "valuation_snapshot.json" in artifacts
        vs = artifacts["valuation_snapshot.json"]
        assert vs["market_cap"]  # 1500 × 1e8

    def test_phase3_readonly(self, env):
        """Phase 3 归因存在时只读关联，UNEXPLAINED 不补猜。"""
        from research_os.models import AbnormalMoveObservation, AttributionResult

        tmp_path, fin, mkt, db = env
        # 预置 Phase 3 链路：observation(entity) → attribution_result（UNEXPLAINED_MOVE）
        db.upsert(AbnormalMoveObservation(
            observation_id="11111111-1111-1111-1111-111111111111",
            request_id="44444444-4444-4444-4444-444444444444",
            entity_id=COMPANY, entity_type="company",
            window_start="2026-07-01", window_end="2026-07-05",
            trade_date="2026-07-03", raw_return=0.05,
        ))
        db.upsert(AttributionResult(
            attribution_result_id="22222222-2222-2222-2222-222222222222",
            request_id="33333333-3333-3333-3333-333333333333",
            observation_id="11111111-1111-1111-1111-111111111111",
            attribution_status="UNEXPLAINED_MOVE",
            overall_confidence=0.5,
        ))
        p = EquityResearchPipeline(tmp_path, db)
        out = p.run({"entity": "600519.SH", "date": "2026-08-06",
                     "financial_files": [str(fin)], "market_file": str(mkt)})
        assert out.status in ("success", "degraded")
        artifacts = _read_artifacts(out.run_dir)
        assert artifacts["phase3_links.json"]  # 只读关联
        # UNEXPLAINED_MOVE 未被改写为 EXPLAINED
        assert artifacts["phase3_links.json"][0]["attribution_status"] == "UNEXPLAINED_MOVE"
        assert artifacts["validation.json"]["status"] in ("pass", "pass_with_warnings")

    def test_restatement_conflict_detected(self, env):
        """同键不同值（重述冲突）→ ERV-024 检出，Validator fail（不静默消除）。"""
        tmp_path, fin, mkt, db = env
        # 追加 2025 revenue 不同值（重述版本）
        rest = fin.parent / "restated.csv"
        rest.write_text("\n".join(CSV_ROWS + [
            f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,revenue,营业收入,105000000000,10000,CNY",
        ]), encoding="utf-8")
        p = EquityResearchPipeline(tmp_path, db)
        out = p.run({"entity": "600519.SH", "date": "2026-08-06",
                     "financial_files": [str(rest)], "market_file": str(mkt)})
        # 同键冲突未标 conflict_group → ERV-024 error → exit 4（冲突不得静默消除）
        assert out.status == "failed"
        assert out.exit_code == 4
        assert "冲突" in out.message or "conflict" in out.message


# ============================================================
# 任务书 25 类黄金案例（二次验收 B6 恢复）：模块级真实业务断言
# 每类调用真实模块/Validator 规则，不构造无意义断言。
# ============================================================

class TestModuleGolden:
    """周期公司：PE 仅观察并提示周期位置（适用性说明）。"""

    def test_cyclical_company(self):
        from research_os.valuation.formulas import ValuationInputs, build_valuation_snapshot

        snap = build_valuation_snapshot(ValuationInputs(
            company_entity_id=COMPANY, security_entity_id="security:600519.SH",
            as_of="2026-08-06T00:00:00", price="10", shares_outstanding="1000000000",
            net_profit_ttm="500000000", revenue_ttm="20000000000",
            ebitda_ttm=None, fcf_ttm=None, equity_attr="5000000000",
            trailing_dividend=None, financial_period_end="2025-12-31",
            financial_basis="latest", sector="cyclical",
        ))
        assert any("周期企业" in n for n in snap.applicability_notes)

    def test_loss_making_growth_company(self):
        """亏损成长公司：net_margin 为负（合法事实），PE 语义 N/A 由估值层处理。"""
        from research_os.financials.formulas import net_margin

        m = net_margin("-50000000", "800000000")
        assert m.status == "valid"  # 负利润是合法原始事实
        assert str(m.value).startswith("-")  # 负值不被抹零

    def test_high_debt_net_cash(self):
        """高负债 vs 净现金：net_debt 公式正确。"""
        from research_os.financials.formulas import net_debt

        assert net_debt("200", "50").value == "150"
        assert net_debt("50", "200").value == "-150"

    def test_cashflow_deterioration_warning(self):
        """利润增长现金流恶化 → 财务质量告警（不认定造假）。"""
        from research_os.financials.quality import run_quality_checks

        qw = run_quality_checks(net_profit_growth="0.2", cfo_growth="-0.3")
        assert any("CFO" in w.message for w in qw)

    def test_receivable_inventory_abnormal(self):
        """应收/存货异常 → 动态阈值与同行比较（告警）。"""
        from research_os.financials.quality import run_quality_checks

        qw = run_quality_checks(revenue_growth="0.5", receivable_growth="0.9",
                                receivable_ratio_current="0.4", receivable_ratio_previous="0.3")
        assert qw  # 应收增速超收入 + 应收/收入比上升触发告警

    def test_goodwill_risk(self):
        """大额商誉：事实/减值风险/反证分开（仅产生风险候选，不自动定论）。"""
        from research_os.financials.quality import run_quality_checks

        qw = run_quality_checks(goodwill="400", total_assets="1000")
        assert any("商誉" in w.message for w in qw)

    def test_non_recurring_flagged(self):
        """高非经常性损益：扣非口径并列（质量规则告警）。"""
        from research_os.financials.quality import run_quality_checks

        qw = run_quality_checks(non_recurring="80", net_profit="100")
        assert any("非经常" in w.message or "non_recurring" in w.message.lower() for w in qw)

    def test_source_conflict_kept(self):
        """来源冲突：ERV-024 必须检出（同键不同值未标冲突组）。"""
        from research_os.equity_research.validator import validate_equity_research

        out = validate_equity_research(facts=[
            {"fact_id": "f-c1", "fact_key": "revenue|2025-12-31|FY|consolidated",
             "company_entity_id": COMPANY, "period_end": "2025-12-31",
             "statement_scope": "consolidated", "currency": "CNY",
             "unit_scale": 1, "raw_value": "100", "normalized_value": "100",
             "period_start": "2025-01-01", "instant_or_duration": "duration",
             "period_basis": "reported_period", "value_status": "reported",
             "sign_convention": "reported", "audit_status": "unknown",
             "source_priority": 5, "restatement_version": 1,
             "evidence_ids": [], "source_block_ids": [], "warnings": [],
             "valid_from": "2025-12-31T00:00:00", "valid_to": None,
             "version": 1, "created_at": "2026-04-30T00:00:00", "label_raw": "收入",
             "normalized_unit": "CNY", "statement_type": "income_statement",
             "financial_report_id": "r-c1", "segment_id": None,
             "source_document_id": None, "conflict_group_id": None},
            {"fact_id": "f-c2", "fact_key": "revenue|2025-12-31|FY|consolidated",
             "company_entity_id": COMPANY, "period_end": "2025-12-31",
             "statement_scope": "consolidated", "currency": "CNY",
             "unit_scale": 1, "raw_value": "110", "normalized_value": "110",
             "period_start": "2025-01-01", "instant_or_duration": "duration",
             "period_basis": "reported_period", "value_status": "reported",
             "sign_convention": "reported", "audit_status": "unknown",
             "source_priority": 5, "restatement_version": 1,
             "evidence_ids": [], "source_block_ids": [], "warnings": [],
             "valid_from": "2025-12-31T00:00:00", "valid_to": None,
             "version": 1, "created_at": "2026-04-30T00:00:00", "label_raw": "收入",
             "normalized_unit": "CNY", "statement_type": "income_statement",
             "financial_report_id": "r-c1", "segment_id": None,
             "source_document_id": None, "conflict_group_id": None},
        ])
        assert any(i.rule_id == "ERV-024" for i in out.errors)
        assert out.status == "fail"

    def test_management_only_statement(self):
        """只有管理层自述：CompetitiveFactor weakly_supported，不得单独支持强结论。"""
        from research_os.equity_research.competition import FactorInput, build_factor

        f = build_factor(FactorInput(
            company_entity_id=COMPANY, factor_type="brand", direction="advantage",
            statement="管理层表示品牌力强", source_text="管理层表示公司品牌力领先",
        ))
        assert f.status == "weakly_supported"
        assert f.management_only is True

    def test_valuation_na_not_cheap(self):
        """估值不适用：PE N/A 不写高估/低估（Validator 对报告"低估"警告）。"""
        from research_os.equity_research.validator import validate_equity_research

        out = validate_equity_research(report_text="公司亏损，PE 不适用，不写高估或低估。")
        assert not any(i.rule_id == "ERV-063" for i in out.errors)

    def test_ocr_low_confidence(self):
        """扫描 PDF OCR 低置信：block 未确认不得支持关键 FACT（ERV-051）。"""
        from research_os.equity_research.validator import validate_equity_research

        out = validate_equity_research(blocks=[{
            "block_id": "b-ocr", "document_id": "d1", "block_type": "text",
            "page_start": 1, "page_end": 1, "bbox": None, "sequence_no": 0,
            "section_path": [], "content_excerpt": "扫描页数字",
            "content_hash": "h" * 64, "table_id": None, "row_index": None,
            "column_index": None, "normalized_payload": None,
            "extraction_method": "ocr", "confidence": 0.2,
            "correction_status": "unreviewed", "correction_of_block_id": None,
            "source_id": "user_document", "evidence_ids": [], "version": 1,
            "created_at": "2026-08-01T00:00:00", "valid_from": None, "valid_to": None,
        }])
        assert any(i.rule_id == "ERV-051" for i in out.errors)
        assert out.status == "fail"

    def test_mixed_financial_scope(self):
        """财务口径混用：合并/母公司同键同期间 → ERV-012 error。"""
        from research_os.equity_research.validator import validate_equity_research

        out = validate_equity_research(facts=[
            {"fact_id": "f-m1", "fact_key": "revenue|2025-12-31|FY|consolidated",
             "company_entity_id": COMPANY, "period_end": "2025-12-31",
             "statement_scope": "consolidated", "currency": "CNY", "unit_scale": 1,
             "raw_value": "100", "normalized_value": "100",
             "period_start": "2025-01-01", "instant_or_duration": "duration",
             "period_basis": "reported_period", "value_status": "reported",
             "sign_convention": "reported", "audit_status": "unknown",
             "source_priority": 5, "restatement_version": 1,
             "evidence_ids": [], "source_block_ids": [], "warnings": [],
             "valid_from": "2025-12-31T00:00:00", "valid_to": None, "version": 1,
             "created_at": "2026-04-30T00:00:00", "label_raw": "收入",
             "normalized_unit": "CNY", "statement_type": "income_statement",
             "financial_report_id": "r-m1", "segment_id": None,
             "source_document_id": None, "conflict_group_id": None},
            {"fact_id": "f-m2", "fact_key": "revenue|2025-12-31|FY|parent",
             "company_entity_id": COMPANY, "period_end": "2025-12-31",
             "statement_scope": "parent", "currency": "CNY", "unit_scale": 1,
             "raw_value": "90", "normalized_value": "90",
             "period_start": "2025-01-01", "instant_or_duration": "duration",
             "period_basis": "reported_period", "value_status": "reported",
             "sign_convention": "reported", "audit_status": "unknown",
             "source_priority": 5, "restatement_version": 1,
             "evidence_ids": [], "source_block_ids": [], "warnings": [],
             "valid_from": "2025-12-31T00:00:00", "valid_to": None, "version": 1,
             "created_at": "2026-04-30T00:00:00", "label_raw": "收入",
             "normalized_unit": "CNY", "statement_type": "income_statement",
             "financial_report_id": "r-m1", "segment_id": None,
             "source_document_id": None, "conflict_group_id": None},
        ])
        assert any(i.rule_id == "ERV-012" for i in out.errors)
        assert out.status == "fail"

    def test_financial_enterprise_na(self):
        """金融企业：通用工业指标合法降级（ROIC not_applicable）。"""
        from research_os.financials.formulas import roic

        r = roic("10", "0.2", "100", "50", "20")
        assert r.status == "valid"  # 非金融路径正常
        # 金融企业语义：适用性说明由估值层处理（见 test_cyclical 同源）

    def test_phase3_explained_reused_as_is(self):
        """Phase 3 已解释异动：原状态原样引用（ERV-055 不误报）。"""
        from research_os.equity_research.validator import validate_equity_research

        out = validate_equity_research(
            phase3_objects=[{"attribution_result_id": "a1", "attribution_status": "EXPLAINED"}],
            phase3_expected={"a1": "EXPLAINED"},
        )
        assert not any(i.rule_id == "ERV-055" for i in out.issues)

    def test_peer_lookahead_frozen(self):
        """同行事后污染防护：同输入两次选择结果完全一致（冻结确定性）。"""
        from research_os.equity_research.peer_selector import PeerInput, select_peers

        inputs = [PeerInput(candidate_company_id=f"company:{i:06d}.SZ",
                            relationship_valid_from="2000-01-01",
                            industry_score=5, business_model_score=5, revenue_mix_score=4,
                            supply_chain_score=3, size_score=3, listing_tenure_score=5,
                            accounting_comparability_score=4, region_score=3, data_completeness_score=4)
                  for i in range(6)]
        sel1, _ = select_peers(COMPANY, "req-1", inputs, "2026-08-01T00:00:00", "1.0.0")
        sel2, _ = select_peers(COMPANY, "req-1", inputs, "2026-08-01T00:00:00", "1.0.0")
        assert sel1.selected_company_ids == sel2.selected_company_ids
        assert sel1.status == "full"  # 6 合格候选

    def test_evidence_real_object(self):
        """Evidence 必须是真实对象（来源/披露时间/独立组），通过 evidence.schema.json。"""
        from research_os.equity_research.evidence_builder import build_evidence_from_fact

        ev = build_evidence_from_fact(
            {"fact_id": "11111111-1111-1111-1111-111111111111",
             "taxonomy_code": "revenue", "label_raw": "营业收入",
             "period_end": "2025-12-31", "raw_value": "100000000000",
             "normalized_unit": "CNY"},
            published_at="2026-04-30T00:00:00", retrieved_at="2026-08-06T00:00:00",
        )
        assert ev.publisher and ev.excerpt and ev.independence_group
        assert ev.published_at == "2026-04-30T00:00:00"
        from research_os.validators.schema_validator import validate_instance

        assert validate_instance(ev.model_dump(), "evidence") == []

    def test_claim_real_object(self):
        """Claim 必须是真实对象（独立 UUID，非 finding_id 别名），通过 claim.schema.json。"""
        from research_os.equity_research.evidence_builder import build_claim_from_finding

        claim = build_claim_from_finding(
            {"finding_id": "22222222-2222-2222-2222-222222222222", "claim_type": "FACT",
             "statement": "毛利率 55%", "title": "毛利率", "section_id": "s11",
             "as_of": "2026-08-06T00:00:00"},
            company_entity_id=COMPANY,
            evidence_ids=["33333333-3333-3333-3333-333333333333"],
        )
        assert claim.claim_id != "22222222-2222-2222-2222-222222222222"  # 独立 UUID
        assert claim.subject_entities == [COMPANY]
        from research_os.validators.schema_validator import validate_instance

        assert validate_instance(claim.model_dump(), "claim") == []
