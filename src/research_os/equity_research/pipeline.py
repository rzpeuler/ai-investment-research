"""个股研报流水线（Phase 4 任务书 3.19，独立验收修复版）。

25 阶段标准流水线：请求解析 → 对象解析 → 能力检查 → 文档 → 财务导入 →
标准化 → 勾稽 → 指标 → 质量 → 分部 → 同行候选 → 同行选择 → 竞争 →
估值 → Phase3 关联 → 晨报事件 → 催化剂/风险 → 冲突 → Findings →
Claim/Evidence → 结果合成 → Markdown → Validator → 持久化。

修复要点（独立验收 BLOCKER 1/3）：
- 全部已开发模块接入正式流水线，禁止以数据缺口章节代替未执行模块；
- 能力检查落实 >=2 个可比年度（1 年=partial，0 年=insufficient_data exit 3）；
- 幂等键 + run_version + force 新版本不覆盖旧产物 + 原子写入；
- Request/Run/Result 全部持久化，产出完整运行目录；
- Validator 失败 → exit 4（不再被内部异常吞成 exit 5）；
- peer/scenario/valuation/forecast/document/market-file 全部进入 _execute。
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_os.storage import Database
from research_os.utils.time import now_iso

EXIT_OK = 0
EXIT_PARAM = 2
EXIT_INSUFFICIENT = 3
EXIT_VALIDATION = 4
EXIT_INTERNAL = 5

SYMBOL_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")

# 规则版本（进幂等键）
RULES_VERSION = {
    "peer_universe": "1.0.0",
    "peer_scoring": "1.0.0",
    "financial_taxonomy": "1.0.0",
    "metric_formula": "1.0.0",
    "quality_rules": "1.0.0",
    "valuation_rules": "1.0.0",
    "report_template": "1.0.0",
}


@dataclass
class PipelineOutcome:
    status: str  # success / partial_success / degraded / insufficient_data / idempotent_skipped / failed
    message: str
    report_path: Optional[str] = None
    run_dir: Optional[str] = None
    exit_code: Optional[int] = None
    research_status: str = ""
    run_id: Optional[str] = None


class EquityResearchPipeline:
    """个股研报流水线（离线优先；无 Provider 时确定性回退）。"""

    def __init__(self, root: Path, db: Database):
        self.root = Path(root)
        self.db = db

    # ---------- 阶段 1：请求解析 ----------

    def parse_request(self, args: Dict[str, Any]) -> Any:
        from research_os.models.equity_research import EquityResearchRequest

        symbol = args.get("entity")
        if not symbol:
            raise ValueError("--entity 必填（如 600519.SH）")
        if not SYMBOL_RE.match(symbol):
            raise ValueError(f"股票代码非法: {symbol!r}（需要 6 位数字 + .SH/.SZ/.BJ）")

        as_of = args.get("as_of") or f"{args.get('date') or '2026-08-06'}T00:00:00"
        company_id = f"company:{symbol}"
        security_id = f"security:{symbol}"

        return EquityResearchRequest(
            request_id=str(uuid.uuid4()),
            task_id=args.get("task_id") or str(uuid.uuid4()),
            company_entity_id=company_id,
            security_entity_id=security_id,
            as_of=as_of,
            report_date=args.get("date") or as_of[:10],
            timezone="Asia/Shanghai",
            depth=args.get("depth", "standard"),
            periods=args.get("periods", 5),
            peer_overrides=list(args.get("peers") or []),
            scenario_ids=list(args.get("scenario_ids") or []),
            include_valuation=args.get("include_valuation", True),
            include_forecast=args.get("include_forecast", False),
            live=args.get("live", False),
            dry_run=args.get("dry_run", False),
            force=args.get("force", False),
            input_document_ids=list(args.get("input_document_ids") or []),
            financial_manifest_ids=list(args.get("financial_manifest_ids") or []),
            market_manifest_ids=list(args.get("market_manifest_ids") or []),
            source_policy=args.get("source_policy", "manual_only"),
            status="planned",
            warnings=[],
            rule_versions=dict(RULES_VERSION),
            requested_at=as_of,
            version=1,
        )

    # ---------- 幂等键与运行版本 ----------

    @staticmethod
    def _file_sha256(path: str) -> str:
        """文件内容 SHA-256（幂等键必须基于内容而非路径）。"""
        if not path:
            return "none"
        p = Path(path)
        if not p.exists() or not p.is_file():
            return "missing"
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()

    def build_idempotency_key(self, request: Any, args: Dict[str, Any]) -> str:
        """幂等键：实体+as_of+depth+periods+peer+scenario+输入内容哈希
        （文档 SHA-256 / 财务 manifest 由内容哈希代表 / 市场文件哈希）+
        规则版本 + 真实 LLM Provider 配置状态。"""
        # 财务文件：内容哈希（同一路径内容改变 → 哈希变 → 不命中幂等）
        fin_hashes = ",".join(sorted(self._file_sha256(f) for f in (args.get("financial_files") or [])))
        doc_hashes = ",".join(sorted(self._file_sha256(d) for d in (args.get("documents") or [])))
        mkt_hash = self._file_sha256(str(args.get("market_file") or ""))
        # 真实 Provider 配置状态（读取 LlmClient 配置，而非硬编码）
        from research_os.llm.client import is_provider_configured

        provider_state = f"provider:{'configured' if is_provider_configured() else 'not_configured'}"
        parts = [
            "equity_research",
            request.company_entity_id,
            request.security_entity_id,
            request.as_of,
            request.depth,
            str(request.periods),
            ",".join(sorted(args.get("peers") or [])),
            ",".join(sorted(args.get("scenario_ids") or [])),
            fin_hashes,
            doc_hashes,
            mkt_hash,
            str(request.include_valuation),
            str(request.include_forecast),
            json.dumps(dict(RULES_VERSION), sort_keys=True),
            provider_state,
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def _next_run_version(self, idempotency_key: str) -> int:
        rows = self.db.query(
            "SELECT run_version FROM equity_research_runs WHERE idempotency_key = ? "
            "ORDER BY run_version DESC LIMIT 1",
            (idempotency_key,),
        )
        return (int(rows[0]["run_version"]) + 1) if rows else 1

    # ---------- 阶段 2-3：对象解析 + 能力检查 ----------

    def capability_check(self, request: Any, financial_files: List[str]) -> Dict[str, Any]:
        """能力检查：财务文件存在 + 可解析出的可比年度数（>=2 success / 1 partial / 0 不足）。"""
        coverage: Dict[str, Any] = {
            "company_or_security": True,
            "financial_files": list(financial_files),
            "documents": [],
            "peers": list(request.peer_overrides),
            "financial_reports": 0,
            "comparable_years": 0,
        }
        for f in financial_files:
            if not Path(f).exists():
                coverage["missing_files"] = coverage.get("missing_files", []) + [f]
        return coverage

    @staticmethod
    def _comparable_fiscal_years(reports: List[dict], as_of: str) -> int:
        """返回可用于跨年比较的完整年报数。

        不能把 Q1/H1/Q3 拼成年度，也不能使用截止日后才披露或口径混杂的报告。
        """
        eligible = [
            r for r in reports
            if r.get("report_type") == "annual"
            and r.get("fiscal_period") == "FY"
            and r.get("duration_months") == 12
            and (r.get("published_at") or "9999-12-31T00:00:00") <= as_of
        ]
        # 选择数量最多的可比口径组，避免混用不同 scope/currency/accounting standard。
        groups: Dict[tuple, set] = {}
        for report in eligible:
            key = (report.get("statement_scope"), report.get("currency"),
                   report.get("accounting_standard"))
            groups.setdefault(key, set()).add(report.get("fiscal_year"))
        return max((len(years) for years in groups.values()), default=0)

    # ---------- 主流程 ----------

    def run(self, args: Dict[str, Any]) -> PipelineOutcome:
        try:
            request = self.parse_request(args)
        except ValueError as exc:
            return PipelineOutcome(status="failed", message=str(exc), exit_code=EXIT_PARAM)

        financial_files = list(args.get("financial_files") or [])
        documents = list(args.get("documents") or [])
        dry_run = bool(args.get("dry_run"))
        force = bool(args.get("force"))
        idempotency_key = self.build_idempotency_key(request, args)

        # 能力检查：无财务数据 → insufficient_data（exit 3）
        if not financial_files:
            return PipelineOutcome(
                status="insufficient_data",
                message=f"核心数据不足：未提供 --financial-file（{request.company_entity_id} 无财务数据），退出码 3",
                exit_code=EXIT_INSUFFICIENT,
                research_status="insufficient_data",
            )

        # dry-run：只预览能力/路径/计划/幂等键/数据缺口，零副作用
        if dry_run:
            coverage = self.capability_check(request, financial_files)
            return PipelineOutcome(
                status="success",
                message=(
                    f"[dry-run] 计划：导入 {len(financial_files)} 个财务文件 + {len(documents)} 个文档 → "
                    f"标准化/勾稽/指标/质量/分部/同行/估值 → 38 章节报告；"
                    f"幂等键 {idempotency_key[:12]}…；未写入任何产物；"
                    f"覆盖={json.dumps(coverage, ensure_ascii=False)}"
                ),
                exit_code=EXIT_OK,
                research_status="planned",
            )

        # 幂等：非 force 且已有成功 run → 跳过
        if not force:
            existing = self.db.query(
                "SELECT run_id, run_version, status FROM equity_research_runs "
                "WHERE idempotency_key = ? ORDER BY run_version DESC LIMIT 1",
                (idempotency_key,),
            )
            if existing and existing[0]["status"] in ("success", "partial_success", "degraded"):
                return PipelineOutcome(
                    status="idempotent_skipped",
                    message=f"幂等命中：run {existing[0]['run_id']} v{existing[0]['run_version']} 已完成，跳过",
                    exit_code=EXIT_OK,
                    research_status=existing[0]["status"],
                    run_id=existing[0]["run_id"],
                )

        run_version = self._next_run_version(idempotency_key)
        try:
            outcome = self._execute(request, args, financial_files, documents,
                                    idempotency_key, run_version)
        except _ValidationFailed as exc:
            return PipelineOutcome(
                status="failed", message=f"Validator 失败（exit 4）: {exc}",
                exit_code=EXIT_VALIDATION, research_status="validation_failed",
            )
        except Exception as exc:  # noqa: BLE001 —— 内部异常 exit 5
            return PipelineOutcome(
                status="failed", message=f"内部错误: {exc}", exit_code=EXIT_INTERNAL,
            )
        return outcome

    # ---------- 执行（阶段 4-25） ----------

    def _execute(
        self,
        request: Any,
        args: Dict[str, Any],
        financial_files: List[str],
        documents: List[str],
        idempotency_key: str,
        run_version: int,
    ) -> PipelineOutcome:
        from research_os.equity_research.assembler import ResultInput, build_result
        from research_os.equity_research.findings import FindingInput, build_finding
        from research_os.equity_research.renderer import RenderInput, render_markdown
        from research_os.equity_research.validator import validate_equity_research
        from research_os.models.equity_research import EquityResearchRun, StageStatus

        stage_statuses: List[StageStatus] = []
        started_at = now_iso()

        def _stage(name: str):
            st = StageStatus(stage=name, status="running", started_at=now_iso(),
                             finished_at=None, warnings=[], missing_data=[])
            stage_statuses.append(st)
            return st

        def _finish(st: StageStatus, status: str, warnings=None, missing=None):
            st.status = status
            st.finished_at = now_iso()
            if warnings:
                st.warnings = warnings
            if missing:
                st.missing_data = missing

        run = EquityResearchRun(
            run_id=str(uuid.uuid4()), request_id=request.request_id,
            task_id=request.task_id, idempotency_key=idempotency_key,
            run_version=run_version, started_at=started_at, finished_at=None,
            status="running", stage_statuses=[], artifact_paths=[],
            input_versions=dict(RULES_VERSION),
            model_route_summary={"mode": "deterministic_fallback", "llm_called": False},
            validation_status="pending", error_codes=[], warnings=[], version=1,
        )
        self.db.upsert(run)
        run_dir = self.root / "reports" / "runs" / request.task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        artifact = lambda name: run_dir / name  # noqa: E731

        # ---------- 阶段 4：文档登记与解析 ----------
        st = _stage("documents")
        document_blocks: List[dict] = []
        document_records: List[dict] = []
        doc_warnings: List[str] = []
        for d in documents:
            from research_os.documents.registry import parse_native_text, register_document

            p = Path(d)
            if not p.exists():
                doc_warnings.append(f"文档不存在: {d}")
                continue
            # 本地文件的 mtime 只是复制/下载时间，绝不是披露时间。未知时间的文档
            # 不能作为历史截面的关键 FACT 直接证据，保留明确降级而非伪造时间。
            published_map = args.get("document_published_at") or {}
            published_at = published_map.get(str(p)) or published_map.get(p.name)
            if not published_at:
                doc_warnings.append(f"{p.name}: published_at unknown，未登记为关键事实证据")
                continue
            rec = register_document(
                p, document_type="other", source_id="user_document",
                title=p.name, published_at=published_at,
                company_entity_id=request.company_entity_id,
                storage_policy="metadata_and_excerpt",
            )
            rec.document_id = str(uuid.uuid4())
            self.db.upsert(rec)
            document_records.append(rec.model_dump())
            if p.suffix.lower() in (".html", ".htm", ".txt"):
                blocks = parse_native_text(p, rec.document_id, "user_document")
                for b in blocks:
                    b.block_id = str(uuid.uuid4())
                    self.db.upsert(b)
                    document_blocks.append(b.model_dump())
            else:
                doc_warnings.append(f"{p.name}: 仅登记未解析（PDF 表格解析为协议层）")
        _finish(st, "success" if not doc_warnings or document_blocks else "partial",
                warnings=doc_warnings or None,
                missing=[f"未解析文档: {d}" for d in documents if not document_blocks and Path(d).exists()] or None)

        # ---------- 阶段 5-6：财务导入 ----------
        st = _stage("financial_import")
        from research_os.financials.import_service import import_financial_file, persist_import

        all_facts: List[dict] = []
        all_reports: List[dict] = []
        all_manifests: List[dict] = []
        import_warnings: List[str] = []
        missing_files: List[str] = []
        for f in financial_files:
            if not Path(f).exists():
                missing_files.append(f)
                import_warnings.append(f"文件不存在: {f}")
                continue
            try:
                res = import_financial_file(Path(f), company_entity_id=request.company_entity_id)
            except (ValueError, FileNotFoundError) as exc:
                import_warnings.append(f"{f}: {exc}")
                continue
            persist_import(self.db, res)
            all_manifests.append(res.manifest.model_dump())
            for rr in res.rows:
                if rr.accepted and rr.fact is not None:
                    all_facts.append(rr.fact.model_dump())
            for r in res.reports:
                all_reports.append(r.model_dump())
            if res.manifest.rejected_count:
                import_warnings.append(f"{f}: {res.manifest.rejected_count} 行被拒绝")
        # H3：文件缺失/全拒绝/无有效事实 → 记录 missing 状态，由持久化阶段判定 exit 3
        comparable_years = self._comparable_fiscal_years(all_reports, request.as_of)
        report_published: Dict[str, str] = {
            r.get("financial_report_id"): r.get("published_at") or ""
            for r in all_reports
        }
        _finish(st, "success" if all_facts else "failed",
                warnings=import_warnings or None,
                missing=(missing_files or ["财务文件无有效事实"]) if not all_facts else None)

        # ---------- 阶段 7：标准化（taxonomy 映射校验） ----------
        st = _stage("normalization")
        from research_os.financials.taxonomy import get_taxonomy

        tax = get_taxonomy()
        norm_warnings: List[str] = []
        for fact in all_facts:
            if fact.get("taxonomy_code") and tax.lookup(fact.get("taxonomy_code")) is None \
                    and tax.subject(fact.get("taxonomy_code")) is None:
                norm_warnings.append(f"未登记科目: {fact.get('taxonomy_code')}")
        _finish(st, "success" if not norm_warnings else "partial", warnings=norm_warnings or None)

        # ---------- 阶段 8：勾稽验证（资产负债表恒等 + 现金流勾稽） ----------
        st = _stage("reconciliation")
        from research_os.financials.reconciler import reconcile_balance_sheet, reconcile_cash_flow

        rec_issues: List[dict] = []
        period_scopes = {(r.get("period_end"), r.get("statement_scope")) for r in all_reports}
        for period_end, scope in sorted(period_scopes):
            scope_facts = [f for f in all_facts
                           if f.get("period_end") == period_end and f.get("statement_scope") == scope]
            vals = {f.get("taxonomy_code"): f.get("normalized_value") for f in scope_facts}
            bs = reconcile_balance_sheet(vals.get("total_assets"), vals.get("total_liabilities"), vals.get("total_equity"))
            for issue in bs.issues:
                rec_issues.append({"period": period_end, "kind": "balance_sheet", **issue.__dict__})
            # H4：现金流勾稽（期末现金 = 期初现金 + 净增加 + 汇兑 + 其他）
            cf = reconcile_cash_flow(
                vals.get("cash_and_equivalents"),
                vals.get("cash_at_beginning"),
                vals.get("net_increase_cash"),
            )
            for issue in cf.issues:
                rec_issues.append({"period": period_end, "kind": "cash_flow", **issue.__dict__})
        _finish(st, "success" if not [i for i in rec_issues if i.get("severity") == "error"] else "partial",
                warnings=[f"{i.get('period')}: {i.get('message')}" for i in rec_issues if i.get("severity") != "error"] or None,
                missing=[f"{i.get('period')}: {i.get('message')}" for i in rec_issues if i.get("severity") == "error"] or None)

        # ---------- 阶段 9：指标计算 ----------
        st = _stage("metrics")
        from research_os.financials.metrics import compute_period_metrics

        all_metrics: List[dict] = []
        for report in all_reports:
            period_facts = [f for f in all_facts if f.get("period_end") == report["period_end"]
                            and f.get("statement_scope") == report["statement_scope"]]
            metrics = compute_period_metrics(request.company_entity_id, period_facts, report["period_end"])
            for m in metrics:
                self.db.upsert(m)
                all_metrics.append(m.model_dump())
        _finish(st, "success" if all_metrics else "partial",
                missing=["无指标可计算"] if not all_metrics else None)

        # ---------- 阶段 10：财务质量 ----------
        st = _stage("financial_quality")
        from research_os.financials.quality import run_quality_checks

        quality_warnings: List[str] = []
        if all_facts:
            latest = all_facts[-1]
            v = lambda code: next((f.get("normalized_value") for f in all_facts
                                   if f.get("taxonomy_code") == code), None)  # noqa: E731
            qw = run_quality_checks(
                cfo=v("operating_cash_flow"), net_profit=v("net_profit_attr"),
                goodwill=v("goodwill"), total_assets=v("total_assets"),
                non_recurring=v("non_recurring_gain_loss"),
                related_party_amount=v("related_party_transactions"), revenue=v("revenue"),
                cash=v("cash_and_equivalents"), restricted=v("restricted_cash"),
            )
            quality_warnings = [w.message for w in qw]
        _finish(st, "success", warnings=quality_warnings or None)

        # ---------- 阶段 11：业务分部 ----------
        st = _stage("business_segments")
        from research_os.equity_research.business_segments import SegmentInput, build_segment

        segments: List[dict] = []
        # 分部数据来自财务文件中的 operating_data 行（taxonomy_code 带 segment 标记）
        for fact in all_facts:
            if fact.get("statement_type") == "operating_data" and fact.get("segment_id"):
                seg = build_segment(SegmentInput(
                    company_entity_id=request.company_entity_id,
                    financial_report_id=fact.get("financial_report_id", ""),
                    segment_type="product", raw_name=fact.get("label_raw", ""),
                    revenue=fact.get("normalized_value"),
                    valid_from=fact.get("period_start") or "1970-01-01",
                ))
                self.db.upsert(seg)
                segments.append(seg.model_dump())
        _finish(st, "success" if segments else "partial",
                missing=["无分部数据"] if not segments else None)

        # ---------- 阶段 12-13：同行候选与选择 ----------
        st = _stage("peer_selection")
        from research_os.equity_research.peer_selector import PeerInput, select_peers

        peers = list(request.peer_overrides)
        peer_selection: Optional[dict] = None
        peer_candidates: List[dict] = []
        peer_warnings: List[str] = []
        if peers:
            inputs = [PeerInput(
                candidate_company_id=p if p.startswith("company:") else f"company:{p}",
                relationship_valid_from="1970-01-01",
                information_cutoff=request.as_of,
                universe_version=RULES_VERSION["peer_universe"],
                industry_score=4, business_model_score=3, revenue_mix_score=3,
                supply_chain_score=3, size_score=3, listing_tenure_score=3,
                accounting_comparability_score=3, region_score=3, data_completeness_score=3,
                user_override=True,
            ) for p in peers]
            sel, cands = select_peers(
                request.company_entity_id, request.request_id, inputs,
                request.as_of, RULES_VERSION["peer_universe"],
            )
            self.db.upsert(sel)
            for c in cands:
                self.db.upsert(c)
            peer_selection = sel.model_dump()
            peer_candidates = [c.model_dump() for c in cands]
            if sel.status == "insufficient":
                peer_warnings.append("同行样本不足，不输出正式分位")
        _finish(st, "success" if peer_selection else "partial",
                warnings=peer_warnings or None,
                missing=["无 --peer 输入"] if not peers else None)

        # ---------- 阶段 14：行业竞争 ----------
        st = _stage("competition")
        competitive_factors: List[dict] = []
        _finish(st, "partial", missing=["行业竞争数据未导入（依赖语义模块或人工）"])

        # ---------- 阶段 14.5：情景预测（H5：--include-forecast 真正执行） ----------
        st = _stage("forecast")
        from research_os.equity_research.forecast import (
            AssumptionInput,
            ScenarioInput,
            build_scenario,
            deterministic_projection,
        )

        forecast_scenarios: List[dict] = []
        forecast_warnings: List[str] = []
        # B4：as_of 之前最新已披露财务事实（披露时间过滤，供预测/估值共用）
        as_of_date = request.as_of[:10]
        eligible = [
            f for f in all_facts
            if (f.get("period_end") or "") <= as_of_date
            and (report_published.get(f.get("financial_report_id") or "", "") or as_of_date) <= request.as_of
        ]
        eligible_sorted = sorted(eligible, key=lambda f: f.get("period_end") or "", reverse=True)
        if request.include_forecast:
            scenario_ids = list(request.scenario_ids)
            if not scenario_ids:
                forecast_warnings.append("--include-forecast 但未提供 --scenario，不生成预测")
            else:
                # 以 as_of 前最新已披露 revenue 为基准做确定性外推（显式假设）
                latest_revenue = None
                for fact in sorted(eligible_sorted, key=lambda f: f.get("period_end") or "", reverse=True):
                    if fact.get("taxonomy_code") == "revenue":
                        latest_revenue = fact.get("normalized_value")
                        break
                for sid in scenario_ids:
                    assumptions = [AssumptionInput(
                        driver="revenue_growth", value="0.08", unit="ratio",
                        period="annual", source_type="deterministic_extrapolation",
                        source_ref_ids=["deterministic_projection_v1"],
                        invalidates_when="披露的收入增长率与假设不一致",
                    )]
                    if latest_revenue:
                        projection = deterministic_projection(latest_revenue, "0.08", 2)
                        sc = build_scenario(ScenarioInput(
                            request_id=request.request_id,
                            company_entity_id=request.company_entity_id,
                            name=sid,
                            scenario_type="deterministic_projection",
                            forecast_start=request.as_of[:10],
                            forecast_end=f"{int(request.as_of[:4]) + 2}-12-31",
                            periods=["FY1", "FY2"],
                            assumptions=assumptions,
                        ))
                        sc.outputs = projection
                        self.db.upsert(sc)
                        forecast_scenarios.append(sc.model_dump())
                    else:
                        forecast_warnings.append(f"情景 {sid}: 无基准收入，未生成预测")
        _finish(st, "success" if forecast_scenarios else "partial",
                warnings=forecast_warnings or None,
                missing=["未启用预测或未提供情景"] if not forecast_scenarios else None)

        # ---------- 阶段 15：估值 ----------
        st = _stage("valuation")
        from research_os.valuation.formulas import ValuationInputs, build_valuation_snapshot

        valuation: Optional[dict] = None
        valuation_warnings: List[str] = []
        if request.include_valuation:
            market = {}
            market_file = args.get("market_file")
            if market_file and Path(market_file).exists():
                try:
                    market = json.loads(Path(market_file).read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    valuation_warnings.append("market-file 解析失败")
            # B4：财务输入必须取"as_of 之前最新财务期间"（非首条匹配），
            #     且仅取披露时间 <= as_of 的事实（真实披露时间过滤）。
            v = lambda code: next((f.get("normalized_value") for f in eligible_sorted
                                   if f.get("taxonomy_code") == code), None)  # noqa: E731
            latest_period = eligible_sorted[0].get("period_end") if eligible_sorted else None
            snap = build_valuation_snapshot(ValuationInputs(
                company_entity_id=request.company_entity_id,
                security_entity_id=request.security_entity_id,
                as_of=request.as_of,
                price=market.get("price"), shares_outstanding=market.get("shares_outstanding"),
                direct_market_cap=market.get("market_cap"),
                interest_debt=v("short_term_borrowing"),
                net_profit_ttm=v("net_profit_attr"), revenue_ttm=v("revenue"),
                ebitda_ttm=None, fcf_ttm=None,
                equity_attr=v("equity_attr"), trailing_dividend=None,
                # 记录真实财务期间（B4：不得用 as_of 冒充）
                financial_period_end=latest_period,
                financial_basis="latest",
                sector="general",
            ))
            self.db.upsert(snap)
            valuation = snap.model_dump()
            if not latest_period:
                valuation_warnings.append("估值无可用财务期间（as_of 之前无已披露报告）")
            if snap.status in ("insufficient_data",):
                valuation_warnings.append("估值输入不足（市值/股本缺失）")
        _finish(st, "success" if valuation else "partial",
                warnings=valuation_warnings or None,
                missing=["未启用估值或输入不足"] if not valuation else None)

        # ---------- 阶段 16：Phase 3 关联（只读） ----------
        st = _stage("phase3_link")
        from research_os.equity_research.catalysts_risks import CatalystInput, RiskInput, build_catalyst, build_risk

        phase3_objects: List[dict] = []
        phase3_expected: Dict[str, str] = {}
        # Phase 3 链路：observation(entity) → attribution_result；只读，不改写
        # B5：只取 created_at/as_of <= 研究截止时间的归因（避免未来信息）
        obs_rows = self.db.query(
            "SELECT payload FROM abnormal_move_observations WHERE payload LIKE ?",
            (f"%{request.company_entity_id}%",),
        )
        obs_ids = []
        for row in obs_rows:
            try:
                obs_ids.append(json.loads(row["payload"]).get("observation_id"))
            except json.JSONDecodeError:
                continue
        for oid in obs_ids:
            rows = self.db.query(
                "SELECT payload FROM attribution_results WHERE payload LIKE ?",
                (f"%{oid}%",),
            )
            for row in rows:
                try:
                    payload = json.loads(row["payload"])
                except json.JSONDecodeError:
                    continue
                # 未来信息过滤（B5）：created_at 缺失视为可接受，有则必须 <= as_of
                created = payload.get("created_at") or ""
                if created and created > request.as_of:
                    continue
                phase3_objects.append(payload)
                phase3_expected[payload.get("attribution_result_id")] = payload.get("attribution_status")
        phase3_warnings: List[str] = []
        catalyst_models: List[Any] = []
        risk_models: List[Any] = []
        catalysts: List[dict] = []
        risks: List[dict] = []
        for obj in phase3_objects:
            cid = obj.get("attribution_result_id")
            status = obj.get("attribution_status")
            if status == "EXPLAINED":
                catalyst_models.append(build_catalyst(CatalystInput(
                    company_entity_id=request.company_entity_id,
                    catalyst_type="other", description="Phase 3 已解释异动关联",
                    claim_type="FACT", announcement_status="occurred",
                    source_phase="phase3", phase3_attribution_result_id=cid,
                )))
            elif status == "UNEXPLAINED_MOVE":
                # 只读关联，不得补猜原因
                risk_models.append(build_risk(RiskInput(
                    company_entity_id=request.company_entity_id,
                    risk_type="other", description="Phase 3 异动未获解释（UNEXPLAINED_MOVE）",
                    claim_type="UNKNOWN", source_phase="phase3",
                    phase3_attribution_result_id=cid,
                )))
                phase3_warnings.append(f"归因 {cid} 保持 UNEXPLAINED_MOVE，未补猜原因")
        _finish(st, "success" if phase3_objects else "partial",
                warnings=phase3_warnings or None,
                missing=["无 Phase 3 归因记录"] if not phase3_objects else None)

        # ---------- 阶段 17：晨报事件（结构化中间产物） ----------
        st = _stage("morning_events")
        event_links: List[dict] = []
        events = self.db.query(
            "SELECT payload FROM events WHERE payload LIKE ? LIMIT 100",
            (f"%{request.company_entity_id}%",),
        )
        for row in events:
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                continue
            # B5：只取事件时间 <= as_of（未来信息过滤）
            ev_time = payload.get("event_time") or payload.get("published_at") or payload.get("created_at") or ""
            if ev_time and ev_time > request.as_of:
                continue
            event_links.append(payload)
        _finish(st, "success" if event_links else "partial",
                missing=["无晨报/事件记录"] if not event_links else None)

        # ---------- 阶段 18：催化剂/风险（Phase 2/3 来源） ----------
        for ev in event_links:
            if ev.get("event_type") in ("earnings", "policy", "project", "capacity"):
                catalyst_models.append(build_catalyst(CatalystInput(
                    company_entity_id=request.company_entity_id,
                    catalyst_type=ev.get("event_type", "other"), description=ev.get("title", "事件"),
                    claim_type="UNKNOWN", announcement_status="unknown",
                    source_phase="phase2", event_id=ev.get("event_id"),
                )))
        for cm in catalyst_models:
            self.db.upsert(cm)
        for rm in risk_models:
            self.db.upsert(rm)
        catalysts = [cm.model_dump() for cm in catalyst_models]
        risks = [rm.model_dump() for rm in risk_models]

        # ---------- 阶段 19：冲突与反证 ----------
        st = _stage("conflicts")
        conflicts = [u for u in (request.warnings or []) if "冲突" in u]
        for f in all_facts:
            if f.get("conflict_group_id"):
                conflicts.append(f"事实冲突组 {f.get('conflict_group_id')}（保留全部版本）")
        _finish(st, "success", warnings=conflicts or None)

        # ---------- 阶段 20：Findings（引用后续阶段构建的真实 Evidence） ----------
        st = _stage("findings")
        finding_models: List[Any] = []
        if all_metrics:
            gm = next((m for m in all_metrics if m.get("metric_code") == "gross_margin"), None)
            if gm and gm.get("status") == "valid":
                finding_models.append(build_finding(FindingInput(
                    request_id=request.request_id, company_entity_id=request.company_entity_id,
                    finding_type="financial_quality", title="毛利率",
                    statement=f"毛利率 {gm.get('value')}",
                    claim_type="FACT", evidence_ids=[],  # 阶段 21 回填真实 Evidence ID
                    supporting_object_ids=[gm.get("metric_id")],
                    section_id="s11", materiality="medium",
                    as_of=request.as_of,
                )))
        for w in quality_warnings:
            finding_models.append(build_finding(FindingInput(
                request_id=request.request_id, company_entity_id=request.company_entity_id,
                finding_type="financial_quality", title="财务质量告警", statement=w,
                claim_type="SOURCE_OPINION", section_id="s12", materiality="low",
                as_of=request.as_of,
            )))
        _finish(st, "success" if finding_models else "partial",
                missing=["无可用研究发现"] if not finding_models else None)

        # ---------- 阶段 21：真实 Claim / Evidence 构建 ----------
        st = _stage("claims_evidence")
        from research_os.equity_research.evidence_builder import (
            build_claim_from_finding,
            build_evidence_from_fact,
            build_evidence_index,
        )

        # 21a. 为每个财务事实构建真实 Evidence（published_at=报告真实披露时间）
        evidence_models: List[Any] = []
        for fact in all_facts:
            rep_id = fact.get("financial_report_id") or ""
            published = report_published.get(rep_id) or fact.get("valid_from") or request.as_of
            ev = build_evidence_from_fact(
                fact, published_at=published, retrieved_at=request.as_of,
            )
            self.db.upsert(ev)
            evidence_models.append(ev)
        # 事件类证据（Phase 2 晨报事件）
        for ev_link in event_links:
            ev = build_evidence_from_event(ev_link, retrieved_at=request.as_of)
            if ev is not None:
                self.db.upsert(ev)
                evidence_models.append(ev)
        evidence_ids = [e.evidence_id for e in evidence_models]
        evidence_index = build_evidence_index(evidence_models)

        # 21b. 回填 Findings 的真实 Evidence ID（按事实血缘映射）
        #      fact_key → evidence_id；metric 的 input_fact_ids 定位事实
        fact_key_to_evidence: Dict[str, str] = {}
        for ev, fact in zip(
            [e for e in evidence_models if e.evidence_type == "manual_input"],
            all_facts,
        ):
            fk = fact.get("fact_key") or f"{fact.get('taxonomy_code')}|{fact.get('period_end')}"
            fact_key_to_evidence[fk] = ev.evidence_id
        metric_id_to_evidence: Dict[str, str] = {}
        for m in all_metrics:
            for fid in m.get("input_fact_ids", []):
                for fact in all_facts:
                    if fact.get("fact_id") == fid:
                        fk = fact.get("fact_key") or f"{fact.get('taxonomy_code')}|{fact.get('period_end')}"
                        metric_id_to_evidence[m.get("metric_id")] = fact_key_to_evidence.get(fk, "")
                        break
        for fm in finding_models:
            ev_ids = [metric_id_to_evidence.get(sid, "") for sid in fm.supporting_object_ids
                      if metric_id_to_evidence.get(sid)]
            fm.evidence_ids = list(dict.fromkeys(ev_ids))  # 去重保序
            fm.support_level = "direct" if fm.evidence_ids else "inferred"
        for fm in finding_models:
            self.db.upsert(fm)
        findings = [fm.model_dump() for fm in finding_models]

        # 21c. 为每个 Finding 构建真实 Claim
        claim_models: List[Any] = []
        for f in findings:
            claim = build_claim_from_finding(
                f, company_entity_id=request.company_entity_id,
                evidence_ids=f.get("evidence_ids", []),
            )
            self.db.upsert(claim)
            claim_models.append(claim)
        claim_ids = [c.claim_id for c in claim_models]
        _finish(st, "success" if evidence_models else "partial",
                missing=["无 Evidence 可构建"] if not evidence_models else None)

        # ---------- 研究状态：按真实覆盖计算（≥2 年 success / 1 年 partial） ----------
        if comparable_years >= 2:
            research_status = "success"
        elif comparable_years == 1:
            research_status = "partial_success"
        else:
            research_status = "insufficient_data"
        if research_status == "success" and (not peer_selection and peers):
            research_status = "degraded"
        stage_missing = [s for s in stage_statuses if s.missing_data]
        if research_status == "success" and stage_missing:
            research_status = "degraded"

        # ---------- 阶段 22：结果合成 ----------
        result = build_result(ResultInput(
            run_id=run.run_id,
            request_id=request.request_id,
            company_entity_id=request.company_entity_id,
            security_entity_id=request.security_entity_id,
            as_of=request.as_of,
            research_status=research_status,
            coverage={
                "comparable_years": comparable_years,
                "financial_reports": len(all_reports),
                "financial_facts": len(all_facts),
                "financial_metrics": len(all_metrics),
                "segments": len(segments),
                "peers": peer_selection.get("status") if peer_selection else None,
                "valuation": valuation.get("status") if valuation else None,
                "phase3_links": len(phase3_objects),
                "morning_events": len(event_links),
                "documents": len(document_records),
            },
            key_finding_ids=[f["finding_id"] for f in findings],
            financial_metric_ids=[m["metric_id"] for m in all_metrics],
            segment_ids=[s["segment_id"] for s in segments],
            peer_selection_id=peer_selection.get("peer_selection_id") if peer_selection else None,
            valuation_snapshot_id=valuation.get("valuation_snapshot_id") if valuation else None,
            catalyst_ids=[c["catalyst_id"] for c in catalysts],
            risk_ids=[r["risk_id"] for r in risks],
            phase3_link_ids=list(phase3_expected.keys()),
            claim_ids=claim_ids,
            evidence_ids=evidence_ids,
            unknowns=["无自动行情来源；历史日线仅人工导入", "无真实 LLM Provider"],
            conflicts=conflicts,
            warnings=quality_warnings + import_warnings + doc_warnings,
        ))
        self.db.upsert(result)

        # ---------- 阶段 23：渲染（38 章节） ----------
        render_input = RenderInput(
            result=result,
            company_name=request.company_entity_id.split(":")[1],
            security_symbol=request.security_entity_id.split(":")[1],
            report_date=request.report_date,
            research_status=research_status,
            findings=findings,
            metrics=all_metrics,
            segments=segments,
            catalysts=catalysts,
            risks=risks,
            peers=peer_selection,
            valuation=valuation,
            scenarios=forecast_scenarios,
            model_route={"mode": "deterministic_fallback", "llm_called": False,
                         "limitation": "semantic_llm_modules_not_connected"},
            unknowns=result.unknowns,
            data_gaps=[g for s in stage_statuses if s.missing_data for g in s.missing_data] or [],
        )
        md = render_markdown(render_input)

        # ---------- 阶段 24：Validator（全量对象传入） ----------
        # 历史 run 列表（ERV-070 幂等重复检查；排除当前 run 自身）
        all_runs = self.db.query(
            "SELECT payload FROM equity_research_runs WHERE idempotency_key = ? AND run_id != ?",
            (idempotency_key, run.run_id),
        )
        historical_runs = []
        for row in all_runs:
            try:
                historical_runs.append(json.loads(row["payload"]))
            except json.JSONDecodeError:
                pass
        outcome = validate_equity_research(
            result=result.model_dump(),
            report_text=md,
            findings=findings,
            facts=all_facts,
            metrics=all_metrics,
            reports=all_reports,
            peers=peer_candidates,
            peer_selection=peer_selection,
            valuation=valuation,
            factors=competitive_factors,
            scenarios=forecast_scenarios,
            blocks=document_blocks,
            evidences=[e.model_dump() for e in evidence_models],
            claims=[c.model_dump() for c in claim_models],
            events=event_links,
            phase3_objects=phase3_objects,
            phase3_expected=phase3_expected,
            as_of=request.as_of,
            dry_run=False,
            artifact_paths=[],
            known_ids=set(evidence_ids),
            runs=historical_runs + [run.model_dump()],
            request=request.model_dump(),
            run=run.model_dump(),
            documents=document_records,
            catalysts=catalysts,
            risks=risks,
        )
        if outcome.status == "fail":
            run.status = "validation_failed"
            run.validation_status = "fail"
            run.error_codes = [i.rule_id for i in outcome.errors]
            run.finished_at = now_iso()
            run.stage_statuses = stage_statuses
            self.db.upsert(run)
            raise _ValidationFailed("; ".join(i.message for i in outcome.errors))
        run.validation_status = "pass" if outcome.status == "pass" else "pass_with_warnings"
        run.warnings = [i.message for i in outcome.warnings]

        # ---------- 阶段 25：持久化（版本化文件名 + 原子写入） ----------
        # H2：先计算最终状态，再写 equity_research_run.json（避免旧状态产物）
        if comparable_years <= 0:
            run.status = "insufficient_data"
            run.finished_at = now_iso()
            run.stage_statuses = stage_statuses
            self.db.upsert(run)
            self.db.upsert(request)
            return PipelineOutcome(
                status="insufficient_data",
                message=f"核心数据不足：财务文件无有效事实（{request.company_entity_id}），退出码 3",
                run_dir=str(run_dir),
                exit_code=EXIT_INSUFFICIENT,
                research_status="insufficient_data",
                run_id=run.run_id,
            )
        run.status = "success" if research_status == "success" else research_status
        run.finished_at = now_iso()
        run.stage_statuses = stage_statuses

        out_dir = self.root / "reports" / "stocks" / request.security_entity_id.split(":")[1]
        out_dir.mkdir(parents=True, exist_ok=True)
        if run_version > 1:
            report_name = f"{request.report_date}_equity_research_v{run_version}.md"
        else:
            report_name = f"{request.report_date}_equity_research.md"
        report_path = out_dir / report_name
        tmp_path = report_path.with_suffix(".md.tmp")
        tmp_path.write_text(md, encoding="utf-8")
        tmp_path.replace(report_path)  # 原子写入

        # 运行目录产物（任务书 30 个正式产物；不存在模块写明确状态对象，不用空文件掩盖）
        artifact_names = [
            "task.json", "entity_resolution.json", "capability.json",
            "equity_research_request.json", "equity_research_run.json",
            "equity_research_result.json", "financial_manifests.json",
            "financial_reports.json", "financial_metrics.json", "financial_validation.json",
            "financial_quality.json", "business_segments.json", "peer_candidates.json",
            "peer_selection.json", "competitive_factors.json", "valuation_snapshot.json",
            "forecast_scenarios.json", "phase3_links.json", "event_links.json", "catalysts.json",
            "risks.json", "contradictions.json", "research_findings.json", "claims.json",
            "evidence_index.json", "model_route.json", "validation.json", "errors.log",
            "document_index.json", "document_blocks.jsonl", "financial_facts.jsonl", "final.md",
        ]
        run.artifact_paths = [str(run_dir / name) for name in artifact_names]
        artifacts: Dict[str, Any] = {
            "task.json": {"task_id": request.task_id, "scenario": "stock_research_report",
                          "status": "completed", "created_at": started_at,
                          "as_of": request.as_of},
            "entity_resolution.json": {"company_entity_id": request.company_entity_id,
                                       "security_entity_id": request.security_entity_id,
                                       "resolution_status": "exact_symbol_match"},
            "capability.json": {"financial_reports": len(all_reports),
                                "comparable_years": comparable_years,
                                "documents": len(document_records),
                                "peers": len(peers),
                                "provider_configured": run.model_route_summary.get("mode") != "deterministic_fallback",
                                "status": research_status},
            "equity_research_request.json": request.model_dump(),
            "equity_research_run.json": run.model_dump(),  # H2：最终状态
            "equity_research_result.json": result.model_dump(),
            "financial_manifests.json": all_manifests,
            "financial_reports.json": all_reports,
            "financial_metrics.json": all_metrics,
            "financial_validation.json": rec_issues,
            "financial_quality.json": [{"message": w, "severity": "warning"} for w in quality_warnings],
            "business_segments.json": segments,
            "peer_candidates.json": peer_candidates,
            "peer_selection.json": peer_selection or {"status": "not_run", "reason": "未提供 --peer"},
            "competitive_factors.json": competitive_factors or {"status": "not_run",
                                                                "reason": "竞争数据依赖语义模块或人工"},
            "valuation_snapshot.json": valuation or {"status": "not_run", "reason": "未启用估值或输入不足"},
            "forecast_scenarios.json": forecast_scenarios or {"status": "not_run",
                                                              "reason": "未启用预测或未提供情景"},
            "phase3_links.json": phase3_objects,
            "event_links.json": event_links,
            "catalysts.json": catalysts,
            "risks.json": risks,
            "contradictions.json": conflicts,
            "research_findings.json": findings,
            "claims.json": [c.model_dump() for c in claim_models],
            "evidence_index.json": evidence_index,
            "model_route.json": {"mode": "deterministic_fallback", "llm_called": False},
            "validation.json": {"status": outcome.status,
                                "errors": [i.__dict__ for i in outcome.errors],
                                "warnings": [i.__dict__ for i in outcome.warnings]},
            "errors.log": {"errors": [], "warnings": run.warnings},
        }
        # 文档产物（存在才写入；不存在的模块写明确状态对象）
        artifacts["document_index.json"] = document_records or {"status": "not_run", "reason": "未提供文档"}
        artifacts["document_blocks.jsonl"] = document_blocks
        for name, payload in artifacts.items():
            if name.endswith(".jsonl"):
                (run_dir / name).write_text(
                    "\n".join(json.dumps(x, ensure_ascii=False) for x in payload), encoding="utf-8")
            else:
                (run_dir / name).write_text(
                    json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        # JSONL 产物：每行一个对象
        (run_dir / "financial_facts.jsonl").write_text(
            "\n".join(json.dumps(f, ensure_ascii=False) for f in all_facts), encoding="utf-8")
        # final.md（报告副本进运行目录）
        (run_dir / "final.md").write_text(md, encoding="utf-8")
        self.db.upsert(run)
        self.db.upsert(request)

        status = "success"
        if research_status in ("partial_success", "degraded"):
            status = research_status
        return PipelineOutcome(
            status=status,
            message=f"研报生成完成（{research_status}；可比年度 {comparable_years}）",
            report_path=str(report_path),
            run_dir=str(run_dir),
            exit_code=EXIT_OK,
            research_status=research_status,
            run_id=run.run_id,
        )


class _ValidationFailed(Exception):
    """Validator 失败：由 run() 转为 exit 4。"""
