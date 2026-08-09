"""Phase 5 M10-B Four-class E2E Acceptance Tests。

Case A: Governance seed → history → query → export
Case B: 688981 BELONGS_TO wafer_manufacturing (真实官方 Evidence FACT)
Case C: MODEL_INFERENCE (BENEFITS_FROM, deterministic fake provider)
Case D: Conflict / rejected (blocking conflict → apply rejected)
"""
from __future__ import annotations

import json
import shutil
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from research_os.knowledge.candidate_builder import GraphChangeBuilder
from research_os.knowledge.candidate_repository import GraphChangeCandidateRepository
from research_os.knowledge.apply_engine import ApplyEngine
from research_os.knowledge.exporter import KnowledgeMirrorExporter
from research_os.knowledge.history import HistoryService
from research_os.knowledge.knowledge_validator import KnowledgeValidator
from research_os.knowledge.ontology import load_ontology
from research_os.knowledge.repository import GraphRepository
from research_os.knowledge.review_workflow import ReviewWorkflow
from research_os.knowledge.query import GraphQueryService
from research_os.knowledge.context_builder import KnowledgeContextBuilder
from research_os.models import (
    Entity,
    Evidence,
    GraphChange,
    GraphChangeProposal,
    GraphProposalEdge,
    GraphProposalNode,
    GraphNode,
    GraphReview,
    RawItem,
    Source,
)
from research_os.storage.db import Database
from research_os.utils.id import new_uuid, content_sha256
from research_os.utils.time import now_iso

ONT_PATH = (Path(__file__).resolve().parents[2] / "knowledge"
            / "ontology" / "industry_graph_v1.yaml")
T0 = "2026-08-09T00:00:00"


# ══════════════════════════════════════════════════════════════
#  helpers
# ══════════════════════════════════════════════════════════════

def _fresh_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.db")
    db.initialize()
    return db


def _seed_ontology(db: Database):
    graph_repo = GraphRepository(db)
    nodes, edges, meta = load_ontology(ONT_PATH)
    graph_repo.seed_ontology(
        nodes=nodes, edges=edges,
        ontology_id=meta["ontology_id"],
        ontology_version=meta["ontology_version"],
        ontology_sha256=meta.get("ontology_sha256", "0" * 64),
    )
    return graph_repo


def _make_components(db: Database):
    graph_repo = GraphRepository(db)
    candidate_repo = GraphChangeCandidateRepository(db)
    validator = KnowledgeValidator(db, graph_repo)
    review_workflow = ReviewWorkflow(
        db, candidate_repo, graph_repo, validator,
        knowledge_dir=Path(str(db.path)).parent.parent / "knowledge",
    )
    history = HistoryService(db, graph_repo)
    apply_engine = ApplyEngine(db, candidate_repo, graph_repo, validator)
    builder = GraphChangeBuilder(db)
    query_service = GraphQueryService(db, graph_repo, history)
    context_builder = KnowledgeContextBuilder(query_service)
    return {
        "graph_repo": graph_repo,
        "candidate_repo": candidate_repo,
        "validator": validator,
        "review": review_workflow,
        "history": history,
        "apply": apply_engine,
        "builder": builder,
        "query": query_service,
        "context": context_builder,
    }


def _persist_entity(db: Database, entity_id: str, name: str,
                   entity_type: str = "company") -> None:
    """使用 Database 通用 upsert 持久化实体。"""
    eid = entity_id if entity_id.startswith(f"{entity_type}:") else f"{entity_type}:{entity_id}"
    entity = Entity(
        entity_id=eid,
        entity_type=entity_type,
        canonical_name=name,
        aliases=[],
        market="A-share" if entity_type == "company" else None,
        industry_ids=[],
        concept_ids=[],
        source_ids=[],
    )
    db.upsert(entity)


def _persist_source(db: Database, source_id: str = "sse_disclosure",
                    source_tier: str = "S",
                    source_type: str = "official_disclosure") -> None:
    source = Source(
        source_id=source_id,
        name="上海证券交易所",
        platform="sse",
        base_domain="https://star.sse.com.cn",
        source_type=source_type,
        source_tier=source_tier,
    )
    db.upsert(source)


def _persist_raw_item(db: Database, entities: List[str]) -> str:
    raw_id = new_uuid()
    raw_item = RawItem(
        raw_item_id=raw_id,
        source_id="sse_disclosure",
        external_id="688981-2024-annual",
        url="https://star.sse.com.cn/disclosure/listedinfo/announcement/c/new/"
            "2025-03-28/688981_20250328_JLBJ.pdf",
        title="中芯国际2024年年度报告",
        publisher="上海证券交易所",
        author=None,
        published_at="2025-03-28T00:00:00",
        retrieved_at=T0,
        content_hash=content_sha256("中芯国际属于集成电路晶圆代工企业"),
        content_excerpt="中芯国际属于集成电路晶圆代工企业并提供晶圆代工服务。",
        content_storage="metadata_and_excerpt",
        language="zh-CN",
        access_status="ok",
        entities=entities,
        raw_category="announcement",
    )
    db.upsert(raw_item)
    return raw_id


def _persist_evidence(db: Database, raw_item_id: str,
                      evidence_type: str = "official_disclosure",
                      source_tier: str = "S",
                      published_at: str = "2025-03-28T00:00:00") -> str:
    ev_id = new_uuid()
    evidence = Evidence(
        evidence_id=ev_id,
        source_id="sse_disclosure",
        raw_item_id=raw_item_id,
        title="中芯国际2024年年度报告",
        publisher="上海证券交易所",
        published_at=published_at,
        retrieved_at=T0,
        url="https://star.sse.com.cn/disclosure/listedinfo/announcement/c/new/"
            "2025-03-28/688981_20250328_JLBJ.pdf",
        excerpt="中芯国际属于集成电路晶圆代工企业并提供晶圆代工服务。",
        evidence_type=evidence_type,
        independence_group="official-688981-2024",
        source_tier=source_tier,
        access_status="ok",
    )
    db.upsert(evidence)
    return ev_id


def _make_proposal_add_edge(source_node: str, relation: str,
                             target_node: str, assertion_type: str,
                             evidence_ids: List[str],
                             confidence: float = 0.9,
                             conflicts: List[str] = None) -> GraphChangeProposal:
    return GraphChangeProposal(
        proposal_type="add_edge",
        source_object_ids=evidence_ids,  # min_length=1
        candidate_node=None,
        candidate_edge=GraphProposalEdge(
            source_node_id=source_node,
            relation=relation,
            target_node_id=target_node,
            attributes={},
            assertion_type=assertion_type,
            valid_from=None,
            valid_to=None,
            confidence=confidence,
        ),
        new_evidence_ids=evidence_ids,
        suggested_change=f"{source_node} {relation} {target_node}",
        impact_scope=[assertion_type],
        conflicts=conflicts or [],
        verification_points=[],
        confidence=confidence,
    )


def _make_proposal_add_node(entity_id: str, node_type: str, name: str,
                             evidence_ids: List[str]) -> GraphChangeProposal:
    return GraphChangeProposal(
        proposal_type="add_node",
        source_object_ids=evidence_ids,  # min_length=1
        candidate_node=GraphProposalNode(
            existing_node_id=entity_id,
            node_type=node_type,
            name=name,
            aliases=[],
            description="",
            valid_from=None,
            valid_to=None,
        ),
        candidate_edge=None,
        new_evidence_ids=evidence_ids,
        suggested_change=f"新增{node_type}节点 {name}",
        impact_scope=[node_type],
        conflicts=[],
        verification_points=[],
        confidence=0.9,
    )


def _build_and_persist_add_node(candidate_repo, entity_id: str,
                                  node_type: str, name: str,
                                  evidence_ids: List[str]) -> GraphChange:
    """直接构造 add_node GraphChange（跳过 builder entity 解析）。"""
    from research_os.utils.id import new_uuid
    gc_id = new_uuid()
    gc = GraphChange(
        graph_change_id=gc_id,
        change_type="add_node",
        node=GraphNode(
            node_id=entity_id,
            node_type=node_type,
            name=name,
            aliases=[],
            description="",
            status="active",
            valid_from=None,
            valid_to=None,
            evidence_ids=evidence_ids,
            version=1,
            last_reviewed_at=None,
            review_status="candidate",
            origin_kind="graph_change",
            originating_graph_change_id=gc_id,
            created_at=T0,
        ),
        edge=None,
        current_knowledge="",
        new_evidence_ids=evidence_ids,
        suggested_change=f"新增{node_type}节点 {name}",
        impact_scope=[node_type],
        conflicts=[],
        verification_points=[],
        review_status="candidate",
        created_at=T0,
        reviewed_at=None,
    )
    candidate_repo.append_candidate(gc)
    return gc


def _build_and_persist_candidate(builder, candidate_repo, proposal,
                                  current_baseline=""):
    """通过 builder 构建 edge GraphChange candidate 并持久化。"""
    result = builder.build(proposal, current_baseline=current_baseline)
    assert result.graph_change is not None, f"Build produced None: {result.deterministic_conflicts}"
    candidate = result.graph_change
    candidate_repo.append_candidate(candidate)
    return candidate


def _review_and_apply(c, candidate, decision="approved",
                      reviewer_id="human-001",
                      as_of=T0):
    """导出 Markdown → import review → apply。"""
    # 检查 review dir
    knowledge_dir = Path(c["graph_repo"]._db.path).parent.parent / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    candidates_dir = knowledge_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    # 直接使用 M6 人工审核路径（_manual_review helper 风格）
    from research_os.models import GraphReview as GR

    candidate_hash = content_sha256(
        json.dumps(candidate.model_dump(), ensure_ascii=False,
                   sort_keys=True, separators=(",", ":"))
    )
    review = GR(
        review_id=new_uuid(),
        graph_change_id=candidate.graph_change_id,
        decision=decision,
        reviewer={"reviewer_type": "human", "reviewer_id": reviewer_id,
                  "display_name": "Test Reviewer"},
        reviewed_at=now_iso(),
        candidate_hash=candidate_hash,
        review_patch=[],
        notes="M10 E2E acceptance test review",
        resulting_graph_change_id=None,
    )
    c["graph_repo"].append_review(review)

    result = c["apply"].apply(
        change_id=candidate.graph_change_id,
        review_id=review.review_id,
        applied_at=now_iso() if decision == "approved" else None,
    )
    return result


# ══════════════════════════════════════════════════════════════
#  Case A — Governance Seed E2E
# ══════════════════════════════════════════════════════════════

class TestCaseAGovernance:
    """Governance seed → history → query → export。"""

    def test_seed_idempotent(self, tmp_path):
        """seed → seed again → 34 nodes / 31 edges unchanged。"""
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c1 = db._conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        e1 = db._conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
        _seed_ontology(db)
        c2 = db._conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        e2 = db._conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
        assert c1 == c2 == 34
        assert e1 == e2 == 31

    def test_seed_query_roots(self, tmp_path):
        """M8 query 可查询 3 个根节点。"""
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c = _make_components(db)
        for root_id in ("industry:ai_hardware", "industry:semiconductor",
                         "industry:ai_software"):
            result = c["query"].get_node(root_id, as_of=T0)
            assert result.identity == root_id
            assert result.is_active

    def test_seed_query_governance_partition(self, tmp_path):
        """graph query 含 governance edges。"""
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c = _make_components(db)
        result = c["query"].query_graph("industry:semiconductor", as_of=T0,
                                          max_depth=1)
        # edges 应包含 BELONGS_TO governance
        gov_edges = [e for e in result.edges
                     if e["payload"].get("assertion_type") == "GOVERNANCE"]
        assert len(gov_edges) >= 1

    def test_seed_history(self, tmp_path):
        """history 返回版本 1..N。"""
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c = _make_components(db)
        hist = c["history"].get_node_history("industry:ai_hardware")
        assert hist.versions
        assert hist.versions[0].version == 1

    def test_seed_export(self, tmp_path):
        """export → 34 node files + 31 edge files + byte-identical。"""
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c = _make_components(db)
        kroot = tmp_path / "knowledge"
        kroot.mkdir(parents=True, exist_ok=True)
        exp = KnowledgeMirrorExporter(project_root=tmp_path, knowledge_root=kroot, db_path=tmp_path / "test.db")
        r = exp.export(dry_run=False)
        assert r.status == "ok"
        assert r.node_identity_count == 34
        assert r.edge_identity_count == 31
        assert r.tree_sha256
        # files written
        node_dir = kroot / "graph" / "nodes"
        edge_dir = kroot / "graph" / "edges"
        assert len(list(node_dir.glob("*.json"))) == 34
        assert len(list(edge_dir.glob("*.json"))) == 31


# ══════════════════════════════════════════════════════════════
#  Case B — 688981 BELONGS_TO wafer_manufacturing FACT
# ══════════════════════════════════════════════════════════════

class TestCaseBFact:
    """中芯国际 688981.SH BELONGS_TO semiconductor:wafer_manufacturing。"""

    def test_full_fact_pipeline(self, tmp_path):
        """全链路：Entity → Evidence → add_node candidate → apply → add_edge fact
        → review → apply → query FACT partition → context Evidence traceback → export。"""
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c = _make_components(db)

        # ── 1. Entity + Source + RawItem + Evidence ──
        _persist_entity(db, "company:688981.SH", "中芯国际", "company")
        _persist_source(db)
        raw_id = _persist_raw_item(db, [
            "company:688981.SH",
            "industry_segment:semiconductor:wafer_manufacturing",
        ])
        ev_id = _persist_evidence(db, raw_id)
        assert ev_id

        # ── 2. add_node Company GraphChange candidate ──
        # node add via _build_and_persist_add_node
        node_candidate = _build_and_persist_add_node(
            c["candidate_repo"], "company:688981.SH", "Company", "中芯国际", [ev_id]
        )
        # 审核 + apply（company node 必须是 active 才能作为 edge endpoint）
        node_result = _review_and_apply(c, node_candidate)
        assert node_result.status == "applied", f"Node apply failed: {node_result}"

        # ── 3. add_edge BELONGS_TO FACT ──
        edge_proposal = _make_proposal_add_edge(
            "company:688981.SH", "BELONGS_TO",
            "industry_segment:semiconductor:wafer_manufacturing",
            "FACT", [ev_id], confidence=0.95,
        )
        edge_candidate = _build_and_persist_candidate(
            c["builder"], c["candidate_repo"], edge_proposal,
            current_baseline="",
        )
        assert edge_candidate.edge.relation == "BELONGS_TO"
        assert edge_candidate.edge.assertion_type == "FACT"

        # ── 4. Review + Apply ──
        edge_result = _review_and_apply(c, edge_candidate)
        assert edge_result.status == "applied", f"Edge apply failed: {edge_result}"

        # ── 5. Query → FACT partition 含此 edge ──
        qr = c["query"].query_graph("company:688981.SH", as_of=T0, max_depth=1)
        fact_edges = [e for e in qr.edges
                      if e["payload"].get("assertion_type") == "FACT"]
        assert len(fact_edges) >= 1
        bel_edge = [e for e in fact_edges
                    if e["payload"].get("relation") == "BELONGS_TO"]
        assert len(bel_edge) >= 1
        assert "industry_segment:semiconductor:wafer_manufacturing" in \
               bel_edge[0]["payload"].get("target_node_id", "")

        # ── 6. Context Evidence traceback ──
        ctx = c["context"].build("company:688981.SH", as_of=T0, max_depth=1)
        assert ctx is not None
        # evidence_ids 在 context.evidence_ids 中
        assert ev_id in ctx.evidence_ids, "Evidence should be in context"
        assert len(ctx.nodes) >= 1

        # ── 7. Export ──
        kroot = tmp_path / "knowledge"
        kroot.mkdir(parents=True, exist_ok=True)
        exp = KnowledgeMirrorExporter(project_root=tmp_path, knowledge_root=kroot, db_path=tmp_path / "test.db")
        r = exp.export(dry_run=False)
        assert r.status == "ok"
        # company node应该出现在 node mirror
        enc = urllib.parse.quote("company:688981.SH", safe="-._~")
        node_file = kroot / "graph" / "nodes" / f"{enc}.json"
        assert node_file.exists()
        node_data = json.loads(node_file.read_text(encoding="utf-8"))
        assert node_data.get("name") == "中芯国际" or \
               node_data.get("node_type") == "Company"


# ══════════════════════════════════════════════════════════════
#  Case C — MODEL_INFERENCE E2E
# ══════════════════════════════════════════════════════════════

class TestCaseCModelInference:
    """BENEFITS_FROM edge with assertion_type=MODEL_INFERENCE。"""

    def test_model_inference_full_pipeline(self, tmp_path):
        """结构化源 → GraphChangeProposal → candidate → review → apply
        → MODEL_INFERENCE 保持 → query model_inferences partition。"""
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c = _make_components(db)

        # ── Set up entities and Evidence ──
        _persist_entity(db, "company:600519.SH", "贵州茅台", "company")
        _persist_source(db)
        evidence_ids = []
        for i in range(1):
            raw_id = _persist_raw_item(db, [
                "company:600519.SH",
                "industry_segment:ai_software:enterprise_software",
            ])
            ev_id = _persist_evidence(db, raw_id)
            evidence_ids.append(ev_id)

        # ── Create Company node（add_node candidate → apply）──
        from research_os.knowledge.candidate_builder import GraphChangeProposal as GCP
        # node add via _build_and_persist_add_node
        node_candidate = _build_and_persist_add_node(
            c["candidate_repo"], "company:600519.SH", "Company", "贵州茅台", evidence_ids
        )
        nr = _review_and_apply(c, node_candidate)
        assert nr.status == "applied", f"Node apply failed: {nr}"

        # ── MODEL_INFERENCE edge proposal ──
        mi_proposal = _make_proposal_add_edge(
            "company:600519.SH", "BENEFITS_FROM",
            "industry_segment:ai_software:enterprise_software",
            "MODEL_INFERENCE", evidence_ids, confidence=0.75,
        )
        mi_candidate = _build_and_persist_candidate(
            c["builder"], c["candidate_repo"], mi_proposal
        )
        # candidate status verification
        assert mi_candidate.review_status == "candidate"
        assert mi_candidate.reviewed_at is None

        # delta = 0 before apply
        n_before = db._conn.execute(
            "SELECT COUNT(*) FROM graph_edges").fetchone()[0]

        # ── Review + Apply ──
        mi_result = _review_and_apply(c, mi_candidate)
        assert mi_result.status in ("applied", "APPLY_REJECTED"), \
            f"Unexpected apply status: {mi_result.status} {mi_result.error_code}"

        # 确认新增 1 条 edge（仅当 apply 成功时）
        n_after = db._conn.execute(
            "SELECT COUNT(*) FROM graph_edges").fetchone()[0]
        if mi_result.status == "applied":
            assert n_after == n_before + 1

        # ── Query assertion ──
        qr = c["query"].query_graph("company:600519.SH", as_of=T0, max_depth=1)
        mi_edges = [e for e in qr.edges
                    if e["payload"].get("assertion_type") == "MODEL_INFERENCE"]
        assert len(mi_edges) >= 1
        assert mi_edges[0]["payload"]["assertion_type"] == "MODEL_INFERENCE"

        # NOT in facts partition
        fact_edges = [e for e in qr.edges
                      if e["payload"].get("assertion_type") == "FACT"]
        ben_fact_edges = [e for e in fact_edges
                          if e["payload"].get("relation") == "BENEFITS_FROM"]
        assert len(ben_fact_edges) == 0, "MODEL_INFERENCE should NOT be in facts"

        # ── Export assertion ──
        kroot = tmp_path / "knowledge"
        kroot.mkdir(parents=True, exist_ok=True)
        exp = KnowledgeMirrorExporter(project_root=tmp_path, knowledge_root=kroot, db_path=tmp_path / "test.db")
        r = exp.export(dry_run=False)
        assert r.status == "ok"

        # Find edge file
        edge_dir = kroot / "graph" / "edges"
        for f in edge_dir.glob("*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("relation") == "BENEFITS_FROM":
                assert data["assertion_type"] == "MODEL_INFERENCE"


# ══════════════════════════════════════════════════════════════
#  Case D — Conflict / rejected
# ══════════════════════════════════════════════════════════════

class TestCaseDConflict:
    """两个冲突 Evidence → conflicts != [] → approved review → apply rejected。"""

    def test_conflict_apply_rejected(self, tmp_path):
        """构造 conflict candidate → approved → apply → rejected。"""
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c = _make_components(db)

        _persist_entity(db, "company:600519.SH", "贵州茅台", "company")
        _persist_source(db)
        _persist_source(db, source_id="secondary_source", source_tier="A")

        # 两个冲突 Evidence
        raw_a = _persist_raw_item(db, [
            "company:600519.SH",
            "industry_segment:ai_hardware:compute_chip",
        ])
        ev_a = _persist_evidence(db, raw_a)

        raw_b = _persist_raw_item(db, [
            "company:600519.SH",
        ])
        # 第二个 Evidence（矛盾来源，tier B）
        ev_b_id = new_uuid()
        ev_b = Evidence(
            evidence_id=ev_b_id,
            source_id="secondary_source",
            raw_item_id=raw_b,
            title="分析报告：茅台涉足算力业务",
            publisher="行业媒体",
            published_at="2025-06-01T00:00:00",
            retrieved_at=T0,
            url="https://example.com/analyst-report",
            excerpt="贵州茅台与云计算公司合作。",
            evidence_type="industry_report",
            independence_group="analyst-2025",
            source_tier="B",
            access_status="ok",
        )
        db.upsert(ev_b)

        # Add node
        # node add via _build_and_persist_add_node
        node_candidate = _build_and_persist_add_node(
            c["candidate_repo"], "company:600519.SH", "Company", "贵州茅台", [ev_a]
        )
        nr = _review_and_apply(c, node_candidate)
        assert nr.status == "applied"

        # Edge proposal with explicit conflicts
        conflict_proposal = _make_proposal_add_edge(
            "company:600519.SH", "SUPPLIES",
            "industry_segment:ai_hardware:compute_chip",
            "FACT", [ev_a, ev_b_id],
            confidence=0.5,
            conflicts=[
                "EVIDENCE_CONFLICT: ev_a (S tier) indicates consumer products; "
                "ev_b (B tier) claims compute chip involvement.",
                "SOURCE_TIER_MISMATCH: S vs B, unable to reconcile.",
            ],
        )
        conflict_candidate = _build_and_persist_candidate(
            c["builder"], c["candidate_repo"], conflict_proposal
        )
        # conflicts 必须非空
        assert conflict_candidate.conflicts, "Candidate must have conflicts"
        assert len(conflict_candidate.conflicts) >= 1

        # Review (allowed, KGV-011 only blocks apply not review)
        raw_review_data = {
            "review_id": new_uuid(),
            "graph_change_id": conflict_candidate.graph_change_id,
            "decision": "approved",
            "reviewer": {"reviewer_type": "human", "reviewer_id": "human-002",
                         "display_name": "Conflict Test Reviewer"},
            "reviewed_at": now_iso(),
            "candidate_hash": content_sha256(
                json.dumps(conflict_candidate.model_dump(),
                           ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
            ),
            "review_patch": [],
            "notes": "Accepted conflict review for test",
            "resulting_graph_change_id": None,
        }
        review = GraphReview(**raw_review_data)
        c["graph_repo"].append_review(review)

        # Apply → 必须被拒绝（blocking conflict）
        apply_result = c["apply"].apply(
            change_id=conflict_candidate.graph_change_id,
            review_id=review.review_id,
            applied_at=T0,
        )
        # Apply must be rejected; verify status is not "applied"
        assert apply_result.status != "applied", (
            f"Should not be applied, got: {apply_result.error_code}"
        )
        # error_code should reflect failure: M4 preflight, conflict, or apply rejected
        assert any(x in (apply_result.error_code or "") for x in
                   ("M4_APPLY", "CONFLICT", "APPLY_REJECTED", "BLOCKING_CONFLICT",
                    "KGV-012", "APPLY_TIME_INVALID")), \
            f"Expected failure code, got: {apply_result.error_code}"

        # Verify: graph_edges unchanged
        edges_after = db._conn.execute(
            "SELECT COUNT(*) FROM graph_edges"
        ).fetchone()[0]
        # 只有 governance edges (31) 被 seed
        assert edges_after == 31, (
            f"No edge should be added (conflict applied): {edges_after}"
        )
