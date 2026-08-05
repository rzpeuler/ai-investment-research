"""异动分析流水线编排（Phase 3 任务书 4 节标准工作流、17 节）。

CLI / Hermes Skill
-> 参数和实体解析 -> 交易日与窗口校验 -> 市场数据路由和质量检查
-> 异动事实检测 -> 基准候选生成与选择 -> 板块和同类公司联动
-> 分层事件检索 -> 原因候选生成 -> 时间因果检查 -> 确定性评分
-> 叙事与反证分析 -> AttributionResult 合成 -> Markdown 渲染
-> Validator -> 持久化和输出

幂等键：scenario+entity_id+entity_type+window_start+window_end+granularity+
depth+market_data_version+anomaly_rules_version+benchmark_rules_version+
cause_score_version。--force 产生新 run_version，不覆盖旧报告/旧产物。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_os.abnormal_move.anomaly_detector import AnomalyDetector
from research_os.abnormal_move.attribution_synthesizer import AttributionSynthesizer
from research_os.abnormal_move.benchmark_selector import BenchmarkSelector, MarketBenchmarkRegistry
from research_os.abnormal_move.cause_candidate_generator import CauseCandidateGenerator
from research_os.abnormal_move.cause_candidate_scorer import CauseCandidateScorer
from research_os.abnormal_move.contradiction_checker import ContradictionChecker
from research_os.abnormal_move.event_window_retriever import EventWindowRetriever
from research_os.abnormal_move.market_data_loader import MarketDataLoader, TradingCalendar
from research_os.abnormal_move.narrative_analyzer import NarrativeAnalyzer
from research_os.abnormal_move.peer_linkage_analyzer import PeerLinkageAnalyzer
from research_os.abnormal_move.renderer import AbnormalMoveRenderer, RenderContext
from research_os.abnormal_move.validator import AbnormalMoveValidator, ValidationContext
from research_os.abnormal_move.window import WindowError, resolve_window
from research_os.abnormal_move.config import (
    ANOMALY_RULES_VERSION,
    BENCHMARK_RULES_VERSION,
    CAUSE_SCORE_VERSION,
)
from research_os.llm import LlmClient, ModelRouter
from research_os.models import (
    AbnormalMoveObservation,
    AbnormalMoveRequest,
    AbnormalMoveRun,
    AttributionResult,
    BenchmarkSelection,
    CauseCandidate,
    CauseEvidenceLink,
)
from research_os.storage import Database
from research_os.utils.id import new_uuid

EXIT_OK = 0
EXIT_PARAM = 2
EXIT_INSUFFICIENT = 3
EXIT_VALIDATION = 4
EXIT_INTERNAL = 5


@dataclass
class PipelineOutcome:
    status: str                       # created / idempotent_skipped / failed / insufficient_data
    exit_code: int
    request: Optional[AbnormalMoveRequest] = None
    run: Optional[AbnormalMoveRun] = None
    attribution: Optional[AttributionResult] = None
    run_dir: Optional[Path] = None
    report_path: Optional[Path] = None
    message: str = ""


class AbnormalMovePipeline:
    """异动分析流水线。"""

    def __init__(self, root: Path, db: Database,
                 llm_client: Optional[LlmClient] = None,
                 calendar: Optional[TradingCalendar] = None):
        self.root = root
        self.db = db
        self.llm_client = llm_client
        self.calendar = calendar or TradingCalendar()
        self.loader = MarketDataLoader(db)
        self.router = ModelRouter()

    # ---------- 主入口 ----------

    def run(self, entity_id: str, entity_type: str,
            analysis_date: Optional[str] = None,
            depth: str = "standard",
            granularity: str = "daily",
            force: bool = False,
            dry_run: bool = False,
            as_of: Optional[str] = None,
            window_start: Optional[str] = None,
            window_end: Optional[str] = None,
            peers: Optional[List[str]] = None,
            benchmark_inputs: Optional[List[Dict[str, Any]]] = None,
            entity_name: str = "",
            ) -> PipelineOutcome:
        """执行完整流水线。"""
        try:
            return self._run_inner(
                entity_id=entity_id, entity_type=entity_type,
                analysis_date=analysis_date, depth=depth,
                granularity=granularity, force=force, dry_run=dry_run,
                as_of=as_of, window_start=window_start, window_end=window_end,
                peers=peers or [], benchmark_inputs=benchmark_inputs or [],
                entity_name=entity_name,
            )
        except WindowError as exc:
            return PipelineOutcome(status="failed", exit_code=EXIT_PARAM, message=str(exc))
        except Exception as exc:  # noqa: BLE001 —— 内部异常不向用户显示 traceback
            return PipelineOutcome(status="failed", exit_code=EXIT_INTERNAL,
                                   message=f"内部错误: {type(exc).__name__}: {exc}")

    def _run_inner(self, entity_id, entity_type, analysis_date, depth,
                   granularity, force, dry_run, as_of, window_start, window_end,
                   peers, benchmark_inputs, entity_name) -> PipelineOutcome:
        # 1. 窗口校验（显式非交易日 -> WindowError -> exit 2）
        resolved = resolve_window(analysis_date, self.calendar,
                                  loader=self.loader if entity_type == "company" else None,
                                  symbol=entity_id if entity_type == "company" else None,
                                  as_of=as_of)
        ws = window_start or resolved.window_start.isoformat()
        we = window_end or resolved.window_end.isoformat()
        task_id = new_uuid()
        request = AbnormalMoveRequest(
            request_id=new_uuid(), task_id=task_id, entity_id=entity_id,
            entity_type=entity_type,  # type: ignore[arg-type]
            analysis_date=resolved.analysis_date.isoformat(),
            window_start=ws, window_end=we,
            granularity=granularity,  # type: ignore[arg-type]
            depth=depth,  # type: ignore[arg-type]
            force=force, dry_run=dry_run,
            as_of=resolved.as_of,
        )

        # 2. 幂等键
        idem = self._idempotency_key(request)
        existing = self._find_run(idem)
        if existing and not force:
            return PipelineOutcome(
                status="idempotent_skipped", exit_code=EXIT_OK,
                message=f"[IDEMPOTENT] 已有通过验证的运行 {existing}",
            )

        # 3. 市场数据（公司用自身日线；行业/概念用成分股聚合合成序列）
        peer_bars = {p: self.loader.load_daily(p) for p in peers}
        if entity_type == "company":
            bars = self.loader.load_daily(entity_id)
            if not bars:
                return PipelineOutcome(
                    status="insufficient_data", exit_code=EXIT_INSUFFICIENT,
                    message="数据不足：无该股票的日线数据（请先 research market-data import-daily）",
                )
        else:
            from research_os.abnormal_move.market_data_loader import aggregate_peer_bars

            bars = aggregate_peer_bars(peer_bars)
            if not bars:
                return PipelineOutcome(
                    status="insufficient_data", exit_code=EXIT_INSUFFICIENT,
                    message="数据不足：行业/概念分析需要至少 2 只成分股的日线数据（--peer）",
                )
            # 合成板块序列：标记 provisional，不得与个股日线混淆
            entity_name = entity_name or entity_id

        # 按 analysis_date 截断：只分析该日及之前的数据（--date 语义）
        analysis_date = resolved.analysis_date.isoformat()
        bars = [b for b in bars if b.trade_date <= analysis_date]
        if not bars:
            return PipelineOutcome(
                status="insufficient_data", exit_code=EXIT_INSUFFICIENT,
                message=f"数据不足：{analysis_date} 及之前无日线数据",
            )

        # 4. 异动检测（先于 run 构造：observation_id 用于 run 落库）
        detector = AnomalyDetector(request, calendar_id=self.calendar.calendar_id)
        detect = detector.detect(bars, benchmarks={}, flags={})
        observation = detect.observation

        run = AbnormalMoveRun(
            run_id=new_uuid(), task_id=task_id, request_id=request.request_id,
            observation_id=observation.observation_id,
            idempotency_key=idem, run_version=1,
            started_at=datetime.now().isoformat(timespec="seconds"),
            finished_at=datetime.now().isoformat(timespec="seconds"),
            status="running",
            rules_versions={
                "market_data": self._market_data_version(),
                "anomaly": ANOMALY_RULES_VERSION,
                "benchmark": BENCHMARK_RULES_VERSION,
                "cause_score": CAUSE_SCORE_VERSION,
                "depth": depth,
            },
        )
        # 幂等键冲突且 force -> 新 run_version（不覆盖旧产物）
        run.run_version = self._next_run_version(idem)

        # 5. 基准选择（行业/概念候选来自调用方；市场基准按板块）
        sel_registry = MarketBenchmarkRegistry(self.root / "registry" / "market_benchmarks.yaml")
        selector = BenchmarkSelector(sel_registry)
        sel_result = selector.select(
            request, entity_id, benchmark_inputs, bars, {},
            observation_id=observation.observation_id)

        # 6. 板块联动（公司：同行个股；行业/概念：成分股即为 peer）
        linkage = PeerLinkageAnalyzer().analyze(observation, peer_bars,
                                                {m.metric_type: m for m in detect.metrics})
        observation.peer_moves = linkage.peer_moves
        observation.metric_ids = [m.metric_id for m in detect.metrics + linkage.metrics]

        # 7. 分层事件检索
        retriever = EventWindowRetriever(self.db, reports_root=self.root / "reports")
        retrieval = retriever.retrieve(
            entity_id, f"{ws}T00:00:00", f"{we}T23:59:59",
            depth=depth, expand_window=(depth == "deep"))

        # 8. 叙事（反证检查在原因候选评分后进行）
        narrative = NarrativeAnalyzer().analyze(retrieval.items)

        # 9. 原因候选 + 评分
        gen = CauseCandidateGenerator()
        generated = gen.build(request, observation, retrieval, linkage, entity_id=entity_id)
        scored = CauseCandidateScorer().score(generated.candidates, generated.links)
        contradictions = ContradictionChecker().check(
            scored.candidates, scored.links, observation)

        # 10. 模型路由（无 LLM 配置则诚实回退）
        model_route = self.router.build_route(
            llm_called=False,
            limitation="semantic_llm_modules_not_connected",
        )

        # 11. 归因合成
        synth = AttributionSynthesizer()
        synthesized = synth.synthesize(
            request, observation, scored, sel_result.selection,
            contradictions, narrative, model_route,
            sample_insufficient=detect.sample_size < 20,
        )
        attribution = synthesized.attribution

        # 12. 渲染
        ctx = RenderContext(
            run=run, attribution=attribution, observation=observation,
            selection=sel_result.selection, candidates=scored.candidates,
            metrics=detect.metrics + linkage.metrics,
            peer_info={
                "effective_peers": linkage.effective_peers,
                "advancing_ratio": linkage.advancing_ratio,
                "declining_ratio": linkage.declining_ratio,
                "peer_median_return": linkage.peer_median_return,
                "subject_cross_sectional_percentile": linkage.subject_cross_sectional_percentile,
                "idiosyncratic": linkage.idiosyncratic,
                "same_direction_abnormal_count": linkage.same_direction_abnormal_count,
            },
            narrative=narrative,
            contradictions=[c.description for c in contradictions.contradictions],
            entity_name=entity_name,
        )
        report_text = AbnormalMoveRenderer().render(ctx)

        # 13. Validator
        vctx = ValidationContext(
            request=request, observation=observation, attribution=attribution,
            run=run, candidates=scored.candidates, links=scored.links,
            selection=sel_result.selection, bars=bars,
            metrics=detect.metrics + linkage.metrics, report_text=report_text,
            narrative=narrative, contradictions=attribution.contradictions,
            snapshot_ids=[], dry_run=dry_run,
        )
        validation = AbnormalMoveValidator(self.calendar).validate(vctx)

        run.observation_id = observation.observation_id
        run.attribution_result_id = attribution.attribution_result_id
        run.module_results = [f"{m.__class__.__name__}" for m in
                              (detect, scored)]
        run.data_routes = []
        run.artifact_paths = []
        run.report_path = ""
        run.validation_status = "passed" if validation.ok else "failed"
        run.status = "completed"
        run.finished_at = datetime.now().isoformat(timespec="seconds")
        run.warnings = validation.warnings

        if dry_run:
            return PipelineOutcome(
                status="created", exit_code=EXIT_OK, request=request, run=run,
                message=f"[DRY-RUN] 归因状态={attribution.attribution_status}，未写入任何产物",
            )

        # 14. 持久化
        run_dir, report_path = self._persist(
            request, observation, detect, linkage, sel_result, retrieval,
            scored, contradictions, attribution, run, report_text, validation)

        # Validator 失败 -> exit 4（产物已留痕，报告不标记 PASS）
        if not validation.ok:
            return PipelineOutcome(
                status="failed", exit_code=EXIT_VALIDATION, request=request,
                run=run, attribution=attribution, run_dir=run_dir,
                report_path=report_path,
                message=f"Validator 失败（{len(validation.errors)} 项）：{validation.errors[0]}",
            )
        return PipelineOutcome(
            status="created", exit_code=EXIT_OK, request=request, run=run,
            attribution=attribution, run_dir=run_dir, report_path=report_path,
            message=f"归因状态={attribution.attribution_status}，置信度={attribution.overall_confidence}",
        )

    # ---------- 幂等 ----------

    def _idempotency_key(self, request: AbnormalMoveRequest) -> str:
        return "|".join([
            "abnormal_move", request.entity_id, request.entity_type,
            request.window_start, request.window_end, request.granularity,
            request.depth, self._market_data_version(),
            ANOMALY_RULES_VERSION, BENCHMARK_RULES_VERSION, CAUSE_SCORE_VERSION,
        ])

    def _market_data_version(self) -> str:
        row = self.db.query(
            "SELECT data_version FROM market_daily_series_manifests "
            "ORDER BY imported_at DESC LIMIT 1")
        return row[0]["data_version"] if row else "none"

    def _find_run(self, idem: str) -> Optional[str]:
        rows = self.db.query(
            "SELECT run_id FROM abnormal_move_runs WHERE idempotency_key = ? "
            "AND validation_status = 'passed' ORDER BY run_version DESC LIMIT 1",
            (idem,))
        return rows[0]["run_id"] if rows else None

    def _next_run_version(self, idem: str) -> int:
        rows = self.db.query(
            "SELECT MAX(run_version) AS v FROM abnormal_move_runs "
            "WHERE idempotency_key = ?", (idem,))
        return int(rows[0]["v"] or 0) + 1 if rows else 1

    # ---------- 持久化 ----------

    def _persist(self, request, observation, detect, linkage, sel_result,
                 retrieval, scored, contradictions, attribution, run,
                 report_text, validation) -> tuple:
        year = observation.trade_date[:4]
        month = observation.trade_date[:7]
        report_dir = self.root / "reports" / "abnormal_moves" / year / month
        report_dir.mkdir(parents=True, exist_ok=True)
        safe_entity = request.entity_id.replace(":", "_").replace(".", "_")
        report_path = report_dir / f"{observation.trade_date}_{safe_entity}_abnormal_move.md"
        report_path.write_text(report_text, encoding="utf-8")

        run_dir = self.root / "reports" / "runs" / run.task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "abnormal_move_request.json": request.model_dump(),
            "abnormal_move_observation.json": observation.model_dump(),
            "anomaly_metrics.json": [m.model_dump() for m in detect.metrics + linkage.metrics],
            "benchmark_candidates.json": [c.model_dump() for c in sel_result.candidates],
            "benchmark_selection.json": sel_result.selection.model_dump(),
            "retrieved_events.json": [{"item_id": i.item_id, "layer": i.layer,
                                       "source_id": i.source_id, "title": i.title,
                                       "published_at": i.published_at} for i in retrieval.items],
            "cause_candidates.json": [c.model_dump() for c in scored.candidates],
            "cause_evidence_links.json": [l.model_dump() for l in scored.links],
            "contradictions.json": [c.__dict__ for c in contradictions.contradictions],
            "attribution_result.json": attribution.model_dump(),
            "model_route.json": attribution.model_route.model_dump(),
            "validation.json": {"ok": validation.ok, "errors": validation.errors,
                                "warnings": validation.warnings},
        }
        for fname, payload in artifacts.items():
            (run_dir / fname).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8")

        # DB 持久化
        self.db.upsert(request)
        self.db.upsert(observation)
        for m in detect.metrics + linkage.metrics:
            self.db.upsert(m)
        for c in sel_result.candidates:
            self.db.upsert(c)
        self.db.upsert(sel_result.selection)
        for c in scored.candidates:
            self.db.upsert(c)
        for l in scored.links:
            self.db.upsert(l)
        self.db.upsert(attribution)

        run.report_path = str(report_path)
        run.artifact_paths = [str(run_dir / f) for f in artifacts]
        self.db.upsert(run)
        return run_dir, report_path
