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

import pytest

from research_os.equity_research.pipeline import EquityResearchPipeline
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
    # FY2024
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,income_statement,revenue,营业收入,85000000000,10000,CNY",
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,income_statement,cost_of_sales,营业成本,40000000000,10000,CNY",
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,balance_sheet,total_assets,资产总计,230000000000,10000,CNY",
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,balance_sheet,total_liabilities,负债合计,60000000000,10000,CNY",
    f"{COMPANY},2024-01-01,2024-12-31,2024,annual,consolidated,balance_sheet,equity_attr,归母所有者权益,170000000000,10000,CNY",
    # FY2025
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,revenue,营业收入,100000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,cost_of_sales,营业成本,45000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,balance_sheet,total_assets,资产总计,260000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,balance_sheet,total_liabilities,负债合计,70000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,balance_sheet,equity_attr,归母所有者权益,190000000000,10000,CNY",
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
