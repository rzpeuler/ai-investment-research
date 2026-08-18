#!/usr/bin/env python
"""P7-D4 在线验收 harness（acceptance-only，taskbook P7-D4 §53）。

对 600519.SH / 300750.SZ 执行真实 CNINFO 年报闭环：
公告发现 → official PDF URL → transient download → SHA256 → DocumentRecord/Block/Evidence
→ FinancialStatementExtractor → FinancialReport/FinancialFact → readiness recheck → 幂等。

显式标记：ACCEPTANCE ONLY，不是 normal production authorization；
只接受 --live-data（D3 冻结门）；离线 CI 永不走此路径。

用法（真实联网）：
    python scripts/acceptance/run_d4_financial_acceptance.py \
        --entity company:maotai --security security:600519.SH \
        --scenario stock_research_report --as-of 2026-05-01T00:00:00+08:00 \
        --live-data
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P7-D4 Source Acceptance Harness (acceptance only)")
    parser.add_argument("--entity", required=True, help="company: 前缀 subject entity")
    parser.add_argument("--security", default=None, help="security: 前缀（可选）")
    parser.add_argument("--scenario", default="stock_research_report")
    parser.add_argument("--as-of", required=True, help="ISO-8601 验收截止时间")
    parser.add_argument("--live-data", action="store_true", required=True,
                        help="显式真实数据授权（D3 冻结门；缺省拒绝）")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--task-id", default=None)
    args = parser.parse_args(argv)

    if not args.live_data:
        print(json.dumps({"status": "failed", "error": "LIVE_DATA_GATE_DISABLED"},
                         ensure_ascii=False))
        return 2

    project_root = Path(args.project_root) if args.project_root else _REPO_ROOT
    task_id = args.task_id or str(uuid.uuid4())
    summary = {
        "acceptance": True, "acceptance_only": True, "online": True,
        "network_attempted": True, "live_data_authorized": True,
        "entity": args.entity, "scenario": args.scenario,
        "task_id": task_id, "as_of": args.as_of,
    }
    db = None
    try:
        from research_os.storage.db import Database

        db = Database(project_root / "data" / "sqlite" / "research.db")
        db.initialize()

        # 1) CNINFO 年报发现（官方公告查询，标题/类别 cross-check）
        from research_os.collectors.official.cninfo import CninfoCollector
        from research_os.data_layer.source_query_projector import (
            SourceQueryProjector,
            _default_security_resolver,
        )

        resolver = _default_security_resolver(db)
        symbol = resolver(args.entity)
        if not symbol:
            print(json.dumps({**summary, "status": "failed",
                              "error": "entity 无 security 映射"}, ensure_ascii=False))
            return 1
        projector = SourceQueryProjector(security_resolver=resolver)
        query = projector.project(
            source_id="cninfo", data_type="company_announcement",
            canonical_query={"entity_ids": [args.entity]},
            time_window={"start": "2026-01-01T00:00:00+08:00", "end": args.as_of},
        )
        collector = CninfoCollector()
        refs = collector.discover(query, {"start": "2026-01-01T00:00:00+08:00",
                                          "end": args.as_of})
        # 年报筛选：标题含"年度报告"且非"摘要/更正/补充/英文"
        annual_refs = [
            r for r in refs
            if "年度报告" in (r.title or "")
            and not any(k in (r.title or "") for k in
                        ("摘要", "更正", "补充", "英文", "取消"))
        ]
        summary["annual_report_candidates"] = [
            {"external_id": r.external_id, "title": (r.title or "")[:80],
             "url": r.url, "published_at": r.published_at}
            for r in annual_refs
        ]
        if not annual_refs:
            print(json.dumps({**summary, "status": "EMPTY_RESULT",
                              "note": "窗口内无合格年报（合法 EMPTY，不得解释为无年报）"},
                             ensure_ascii=False))
            return 0

        # 2) materialize 最新年报（transient download）
        from research_os.documents.disclosure_materializer import (
            TransientDisclosureMaterializer,
        )

        materializer = TransientDisclosureMaterializer(db)
        latest = max(annual_refs, key=lambda r: r.published_at or "")
        doc = materializer.materialize(
            project_root, company_entity_id=args.entity,
            security_entity_id=args.security, source_id="cninfo",
            source_url=latest.url, title=latest.title,
            published_at=latest.published_at, document_type="annual_report",
            external_id=latest.external_id,
            report_period_end=latest.title[:4] + "-12-31"
            if (latest.title or "")[:4].isdigit() else "2025-12-31",
            fiscal_year=int(latest.title[:4]) if (latest.title or "")[:4].isdigit() else 2025,
        )
        summary["document"] = {
            "document_id": doc.document_id, "inserted": doc.inserted,
            "block_count": len(doc.block_ids), "evidence_ids": doc.evidence_ids,
            "warnings": doc.warnings,
        }

        # 3) derive financial facts（ZERO NETWORK）
        from research_os.data_layer.derivation import (
            DerivationPrerequisiteResolver,
            FinancialDerivationExecutor,
            FinancialDerivationService,
        )

        executor = FinancialDerivationExecutor(
            db, resolver=DerivationPrerequisiteResolver(db),
            service=FinancialDerivationService(db),
        )
        from research_os.data_layer.execution import RouteExecutionInput
        from research_os.models import AcquisitionStep

        step = AcquisitionStep(
            step_id=str(uuid.uuid4()), requirement_id="financial_statement_data",
            data_type="financial_statement_data", action="derive_existing",
            dependencies=[], status="pending", warnings=[])
        outcome = executor.execute(
            step=step, task_id=task_id, as_of=args.as_of,
            route_input=RouteExecutionInput(
                query={"entity_ids": [args.entity]},
                time_window={"start": None, "end": args.as_of}),
        )
        summary["derivation"] = {
            "status": outcome.status, "reason_codes": list(outcome.reason_codes),
            "produced_record_refs": list(outcome.produced_record_refs),
            "reused_record_refs": list(outcome.reused_record_refs),
            "warnings": list(outcome.warnings),
        }

        # 4) readiness recheck（权威 DataPreflight）
        from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
        from research_os.data_layer.preflight import DataPreflightService
        from research_os.routing.scenario_requirements import (
            ScenarioDataRequirementRegistry,
        )

        req = ScenarioDataRequirementRegistry(
            project_root / "registry" / "scenario_data_requirements.yaml")
        cap = AcquisitionCapabilityRegistry(
            project_root / "registry" / "data_acquisition_capabilities.yaml",
            scenario_requirements=req, repo_root=project_root,
        )
        preflight = DataPreflightService(
            req, cap,
            derivation_prerequisites={"financial_statement_data": "company_document"})
        bundle = preflight.run(
            scenario=args.scenario, task_id=task_id, task_as_of=args.as_of,
            normalized_request={"entity": args.entity, "as_of": args.as_of},
            project_root=project_root, db=db, runs_root=project_root / "reports" / "runs",
            graph_repo=None, dry_run=False,
        )
        summary["readiness"] = [
            {"requirement_id": r.requirement_id, "data_type": r.data_type,
             "status": r.status, "eligible": r.eligible_record_count,
             "available_fields": list(r.available_fields),
             "missing_fields": list(r.missing_fields)}
            for r in bundle.readiness
            if r.data_type in ("financial_statement_data", "company_document")
        ]

        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 -- 脱敏
        print(json.dumps({
            **summary, "status": "failed",
            "error_type": type(exc).__name__,
            "message": "D4 acceptance run failed (sanitized)",
        }, ensure_ascii=False, indent=2))
        return 1
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    raise SystemExit(main())
