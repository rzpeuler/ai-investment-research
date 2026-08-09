"""Phase 5 M10-R3 No-Fallback Full-Lineage Closure。

R3: CompanyProfile identity source + mandatory ReviewWorkflow import + genuinely
incompatible Evidence + no manual GraphChange/GraphReview fallback anywhere.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from research_os.knowledge.apply_engine import ApplyEngine
from research_os.knowledge.candidate_pipeline import CandidatePipeline
from research_os.knowledge.candidate_repository import GraphChangeCandidateRepository
from research_os.knowledge.context_builder import KnowledgeContextBuilder
from research_os.knowledge.exporter import KnowledgeMirrorExporter
from research_os.knowledge.history import HistoryService
from research_os.knowledge.knowledge_validator import KnowledgeValidator
from research_os.knowledge.ontology import load_ontology
from research_os.knowledge.query import GraphQueryService
from research_os.knowledge.repository import GraphRepository
from research_os.knowledge.review_workflow import ReviewWorkflow
from research_os.llm.provider import FakeLlmProvider
from research_os.models import Entity, Evidence, RawItem, Source
from research_os.storage.db import Database
from research_os.utils.id import new_uuid, content_sha256

ONT_PATH = (Path(__file__).resolve().parents[2] / "knowledge"
            / "ontology" / "industry_graph_v1.yaml")
M10_SSE_688981_URL = (
    "https://star.sse.com.cn/disclosure/listedinfo/announcement/c/new/"
    "2025-03-28/688981_20250328_JLBJ.pdf"
)


# ══════════════════════════════════════════════════════════════
#  helpers
# ══════════════════════════════════════════════════════════════

def _fresh_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.db")
    db.initialize()
    return db


def _seed_ontology(db: Database) -> GraphRepository:
    graph_repo = GraphRepository(db)
    nodes, edges, meta = load_ontology(ONT_PATH)
    graph_repo.seed_ontology(
        nodes=nodes, edges=edges,
        ontology_id=meta["ontology_id"],
        ontology_version=meta["ontology_version"],
        ontology_sha256=meta.get("ontology_sha256", "0" * 64),
    )
    return graph_repo


def _make_components(db: Database) -> Dict[str, Any]:
    graph_repo = GraphRepository(db)
    candidate_repo = GraphChangeCandidateRepository(db)
    validator = KnowledgeValidator(db, graph_repo)
    knowledge_dir = (Path(db.path).parent.parent / "knowledge")
    review_wf = ReviewWorkflow(db, candidate_repo, graph_repo, validator,
                               knowledge_dir=knowledge_dir)
    history = HistoryService(db, graph_repo)
    apply_engine = ApplyEngine(db, candidate_repo, graph_repo, validator)
    query = GraphQueryService(db, graph_repo, history)
    context = KnowledgeContextBuilder(query)
    return {
        "graph_repo": graph_repo, "candidate_repo": candidate_repo,
        "review": review_wf, "history": history,
        "apply": apply_engine, "query": query, "context": context,
    }


def _persist_entity(db: Database, entity_id: str, name: str) -> None:
    entity = Entity(
        entity_id=entity_id, entity_type="company",
        canonical_name=name, aliases=[],
        market="A-share", industry_ids=[], concept_ids=[], source_ids=[],
    )
    db.upsert(entity)


def _persist_source(db: Database,
                    source_id: str = "sse_disclosure",
                    source_tier: str = "S",
                    name: str = "上海证券交易所",
                    platform: str = "sse",
                    base_domain: str = "https://star.sse.com.cn",
                    source_type: str = "official_disclosure") -> None:
    source = Source(
        source_id=source_id, name=name,
        platform=platform, base_domain=base_domain,
        source_type=source_type, source_tier=source_tier,
    )
    db.upsert(source)


def _persist_raw_item(db: Database, entities: List[str],
                      title: str = "中芯国际2024年年度报告",
                      excerpt: str = "中芯国际属于集成电路晶圆代工企业。",
                      source_id: str = "sse_disclosure",
                      url: str = None) -> str:
    if url is None:
        url = "https://sse.example.com/test"
    raw_id = new_uuid()
    raw_item = RawItem(
        raw_item_id=raw_id, source_id=source_id,
        external_id=new_uuid(), url=url, title=title,
        publisher="上海证券交易所", author=None,
        published_at="2025-03-28T00:00:00",
        retrieved_at="2026-08-09T00:00:00",
        content_hash=content_sha256(title),
        content_excerpt=excerpt, content_storage="metadata_and_excerpt",
        language="zh-CN", access_status="ok",
        entities=entities, raw_category="announcement",
    )
    db.upsert(raw_item)
    return raw_id


def _persist_evidence(db: Database, raw_item_id: str,
                      title: str = "中芯国际2024年年度报告",
                      excerpt: str = "",
                      source_tier: str = "S",
                      source_id: str = "sse_disclosure",
                      published_at: str = "2025-03-28T00:00:00",
                      url: str = None,
                      independence_group: str = "") -> str:
    ev_id = new_uuid()
    evidence = Evidence(
        evidence_id=ev_id, source_id=source_id,
        raw_item_id=raw_item_id,
        title=title, publisher="上海证券交易所",
        published_at=published_at,
        retrieved_at="2026-08-09T00:00:00", url=url,
        excerpt=excerpt or "中芯国际属于集成电路晶圆代工企业。",
        evidence_type="official_disclosure",
        independence_group=independence_group or f"grp-{ev_id[:8]}",
        source_tier=source_tier, access_status="ok",
    )
    db.upsert(evidence)
    return ev_id


def _persist_synthetic_source(db: Database, source_id: str,
                               source_tier: str,
                               name: str,
                               platform: str = "synthetic_fixture",
                               base_domain: str = "https://synthetic.example.com") -> None:
    """Synthetic source for M10 acceptance testing (NOT real data)."""
    _persist_source(db, source_id=source_id, source_tier=source_tier,
                    name=name, platform=platform,
                    base_domain=base_domain,
                    source_type="test_fixture")


def _persist_company_profile(db: Database, entity_id: str, name: str,
                              evidence_ids: List[str],
                              source_ids: List[str] = None) -> str:
    """通过正常持久化 API 创建 CompanyProfile（M3 正式 structured source）。"""
    from research_os.models.companies import CompanyProfile
    cp = CompanyProfile(
        company_profile_id=new_uuid(),
        entity_id=entity_id,
        canonical_name=name,
        fiscal_year_end="12-31",
        reporting_currency="CNY",
        ownership_type="state_owned",
        business_description="",
        valid_from="2025-01-01",
        created_at="2026-08-09T00:00:00",
        updated_at="2026-08-09T00:00:00",
        source_ids=source_ids or ["sse_disclosure"],
        evidence_ids=evidence_ids,
    )
    db.upsert(cp)
    return cp.company_profile_id


def _run_candidate_pipeline(db: Database, c: Dict[str, Any],
                             sources: List[Tuple[str, str]],
                             provider_behavior) -> Dict[str, Any]:
    """CandidatePipeline + FakeLlmProvider。"""
    import research_os.knowledge.candidate_pipeline as cp_module
    wrapped = lambda req, schema: {
        "ok": True, "output": provider_behavior(req, schema),
        "error": None, "model_id": "fake-r3",
    }
    fake = FakeLlmProvider(behavior=wrapped)
    cp_module.is_provider_configured = lambda: True
    knowledge_dir = (Path(db.path).parent.parent / "knowledge")
    pipeline = CandidatePipeline(
        db=db, provider=fake, live=True, dry_run=False,
    )
    pipeline._llm_client.configured = True
    return pipeline.run(sources, knowledge_dir=knowledge_dir)


# ══════════════════════════════════════════════════════════════
#  R3: mandatory ReviewWorkflow helper — no fallback
# ══════════════════════════════════════════════════════════════

def _review_and_apply(c: Dict[str, Any], candidate_gc_id: str,
                       reviewer_id: str = "test-human-r3") -> Dict[str, Any]:
    """M5 ReviewWorkflow: export Markdown → fill Reviewer YAML →
    review_import(STATUS MUST BE ok) → apply。

    TEST HUMAN REVIEW FIXTURE — NOT PRODUCTION HUMAN APPROVAL.
    NO FALLBACK to manual GraphReview or append_review.
    """
    # 1. Export Markdown
    export_r = c["review"].review_export(graph_change_id=candidate_gc_id)
    assert export_r.status == "ok", f"Export: {export_r}"
    assert export_r.markdown_path
    md_path = Path(export_r.markdown_path)
    assert md_path.exists()

    # 2. Load candidate to get created_at (for valid KGV-012 timeline)
    gc_raw = c["candidate_repo"].get_candidate(candidate_gc_id)
    assert gc_raw is not None
    if gc_raw.get("canonical_json"):
        gc_payload = json.loads(gc_raw["canonical_json"])
    else:
        gc_payload = gc_raw
    created_at = gc_payload.get("created_at", "2026-08-09T00:00:00")

    # 3. Read Markdown and fill review fields
    md_text = md_path.read_text(encoding="utf-8")
    md_text = md_text.replace("- [ ] 批准", "- [x] 批准")
    # Insert Reviewer YAML between ## Reviewer and ## Review Notes
    reviewer_yaml = (
        f"\nreviewer_type: human\n"
        f"reviewer_id: {reviewer_id}\n"
        f"display_name: M10 TEST HUMAN FIXTURE\n"
        f"reviewed_at: \"{created_at}\"\n"
    )
    # Find ## Reviewer and ## Review Notes, insert YAML between them
    start_marker = "## Reviewer\n"
    end_marker = "\n## Review Notes"
    start_pos = md_text.index(start_marker) + len(start_marker)
    end_pos = md_text.index(end_marker, start_pos)
    before = md_text[:start_pos]
    after = md_text[end_pos:]
    md_text = before + reviewer_yaml + after

    # Also fill Review Notes
    md_text = md_text.replace(
        "_（请在此填写审核意见）_",
        "TEST HUMAN REVIEW FIXTURE — NOT PRODUCTION HUMAN APPROVAL."
    )

    # 4. Import review — MUST succeed
    import_r = c["review"].review_import(md_text=md_text)
    assert import_r.status == "ok", (
        f"Review import failed: status={import_r.status} "
        f"errors={import_r.errors} warnings={import_r.warnings}"
    )
    assert import_r.review_id
    # Verify Review Notes contains TEST HUMAN REVIEW FIXTURE
    stored_review = c["graph_repo"].get_review(import_r.review_id)
    assert stored_review is not None, "Review must be persisted"
    assert "TEST HUMAN REVIEW FIXTURE" in str(stored_review.get("notes", "")),         f"Review notes must contain fixture marker: {stored_review.get('notes')}"

    # 5. Apply — applied_at = reviewed_at (= created_at, KGV-012 equality OK)
    apply_r = c["apply"].apply(
        change_id=candidate_gc_id,
        review_id=import_r.review_id,
        applied_at=created_at,
    )
    return {"export": export_r, "import": import_r, "apply": apply_r}


# ══════════════════════════════════════════════════════════════
#  Case A — Governance
# ══════════════════════════════════════════════════════════════

class TestCaseAGovernance:

    def test_seed_idempotent(self, tmp_path):
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c1 = db._conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        _seed_ontology(db)
        c2 = db._conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        assert c1 == c2 == 34

    def test_seed_export(self, tmp_path):
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        kroot = tmp_path / "knowledge"
        kroot.mkdir(parents=True, exist_ok=True)
        with KnowledgeMirrorExporter(
            project_root=tmp_path, knowledge_root=kroot,
            db_path=tmp_path / "test.db",
        ) as exp:
            r = exp.export(dry_run=False)
            assert r.status == "ok"
            assert r.node_identity_count == 34


# ══════════════════════════════════════════════════════════════
#  Case B — 688981 BELONGS_TO wafer_manufacturing FACT
# ══════════════════════════════════════════════════════════════

class TestCaseBFact:

    def test_full_fact_pipeline(self, tmp_path):
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c = _make_components(db)

        _persist_entity(db, "company:688981.SH", "中芯国际")
        _persist_source(db)
        raw_id = _persist_raw_item(db, [
            "company:688981.SH",
            "industry_segment:semiconductor:wafer_manufacturing",
        ], url=M10_SSE_688981_URL)
        ev_id = _persist_evidence(db, raw_id, url=M10_SSE_688981_URL)
        assert ev_id
        # URL lineage: load Evidence from SQLite payload
        ev_rows = db.query(
            "SELECT payload FROM evidence WHERE evidence_id=?", (ev_id,)
        )
        assert ev_rows, "Evidence must be persisted"
        # CompanyProfile 提供 company_entity_id（builder identity resolution）
        cp_id = _persist_company_profile(
            db, "company:688981.SH", "中芯国际", [ev_id]
        )

        # ── add_node via CandidatePipeline(CompanyProfile) ──
        def _node_behavior(req, schema):
            return {
                "proposal_type": "add_node",
                "source_object_ids": [f"CompanyProfile:{cp_id}"],
                "candidate_node": {
                    "existing_node_id": None,
                    "node_type": "Company",
                    "name": "中芯国际",
                    "aliases": [], "description": "",
                    "valid_from": None, "valid_to": None,
                },
                "candidate_edge": None,
                "new_evidence_ids": [ev_id],
                "suggested_change": "新增公司 中芯国际",
                "impact_scope": ["Company"],
                "conflicts": [], "verification_points": [],
                "confidence": 0.95,
            }

        node_r = _run_candidate_pipeline(
            db, c, [("CompanyProfile", cp_id)], _node_behavior
        )
        assert node_r["status"] == "ok", (
            f"Node pipeline: status={node_r['status']} "
            f"errors={node_r.get('errors', [])}"
        )
        assert node_r["candidates_persisted"] >= 1
        node_gc_id = node_r["candidates"][0]["graph_change_id"]

        # ── ReviewWorkflow + Apply ──
        nrwa = _review_and_apply(c, node_gc_id, reviewer_id="human-b-node")
        assert nrwa["apply"].status == "applied", (
            nrwa["apply"].error_code, nrwa["apply"].errors
        )

        # ── add_edge BELONGS_TO FACT via CandidatePipeline ──
        def _edge_behavior(req, schema):
            return {
                "proposal_type": "add_edge",
                "source_object_ids": [f"Evidence:{ev_id}"],
                "candidate_node": None,
                "candidate_edge": {
                    "source_node_id": "company:688981.SH",
                    "relation": "BELONGS_TO",
                    "target_node_id":
                        "industry_segment:semiconductor:wafer_manufacturing",
                    "attributes": {},
                    "assertion_type": "FACT",
                    "valid_from": None, "valid_to": None,
                    "confidence": 0.95,
                },
                "new_evidence_ids": [ev_id],
                "suggested_change": "688981 BELONGS_TO wafer_manufacturing",
                "impact_scope": ["FACT"],
                "conflicts": [], "verification_points": [],
                "confidence": 0.95,
            }

        edge_r = _run_candidate_pipeline(
            db, c, [("Evidence", ev_id)], _edge_behavior
        )
        assert edge_r["status"] == "ok"
        assert edge_r["candidates_persisted"] >= 1
        edge_gc_id = edge_r["candidates"][0]["graph_change_id"]

        erwa = _review_and_apply(c, edge_gc_id, reviewer_id="human-b-edge")
        assert erwa["apply"].status == "applied", (
            erwa["apply"].error_code, erwa["apply"].errors
        )

        # ── Query FACT partition ──
        qr = c["query"].query_graph("company:688981.SH",
                                     as_of="2026-08-09T12:00:00", max_depth=1)
        fact_edges = [e for e in qr.edges
                      if e["payload"].get("assertion_type") == "FACT"]
        assert len(fact_edges) >= 1
        bel = [e for e in fact_edges
               if e["payload"].get("relation") == "BELONGS_TO"]
        assert len(bel) >= 1

        # ── Export ──
        kroot = tmp_path / "knowledge"
        with KnowledgeMirrorExporter(
            project_root=tmp_path, knowledge_root=kroot,
            db_path=tmp_path / "test.db",
        ) as exp:
            r = exp.export(dry_run=False)
            assert r.status == "ok"


# ══════════════════════════════════════════════════════════════
#  Case C — MODEL_INFERENCE
# ══════════════════════════════════════════════════════════════

class TestCaseCModelInference:

    def test_model_inference_full_pipeline(self, tmp_path):
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c = _make_components(db)

        _persist_entity(db, "company:600519.SH", "贵州茅台")
        _persist_synthetic_source(db, source_id="m10_synthetic_mi",
                                  source_tier="B",
                                  name="M10 Synthetic Model Inference Source")
        raw_id = _persist_raw_item(db, [
            "company:600519.SH",
            "industry_segment:ai_software:enterprise_software",
        ], title="TEST SYNTHETIC MODEL INFERENCE INPUT",
           excerpt="company:600519.SH is modeled as adopting enterprise AI software.",
           source_id="m10_synthetic_mi",
           url="https://synthetic.example.com/model-inference")
        ev_id = _persist_evidence(db, raw_id,
            title="TEST SYNTHETIC MODEL INFERENCE INPUT",
            excerpt="company:600519.SH is modeled as adopting enterprise AI software.",
            source_id="m10_synthetic_mi", source_tier="B",
            url="https://synthetic.example.com/model-inference")
        cp_id = _persist_company_profile(
            db, "company:600519.SH", "贵州茅台", [ev_id],
            source_ids=["m10_synthetic_mi"]
        )

        # ── add_node ──
        def _node_behavior(req, schema):
            return {
                "proposal_type": "add_node",
                "source_object_ids": [f"CompanyProfile:{cp_id}"],
                "candidate_node": {
                    "existing_node_id": None,
                    "node_type": "Company", "name": "贵州茅台",
                    "aliases": [], "description": "",
                    "valid_from": None, "valid_to": None,
                },
                "candidate_edge": None,
                "new_evidence_ids": [ev_id],
                "suggested_change": "新增公司 贵州茅台",
                "impact_scope": ["Company"],
                "conflicts": [], "verification_points": [],
                "confidence": 0.9,
            }

        node_r = _run_candidate_pipeline(
            db, c, [("CompanyProfile", cp_id)], _node_behavior
        )
        assert node_r["status"] == "ok"
        node_gc = node_r["candidates"][0]["graph_change_id"]
        nrwa = _review_and_apply(c, node_gc, reviewer_id="human-c-node")
        assert nrwa["apply"].status == "applied", (
            nrwa["apply"].error_code, nrwa["apply"].errors
        )

        # ── MODEL_INFERENCE edge ──
        n_before = db._conn.execute(
            "SELECT COUNT(*) FROM graph_edges").fetchone()[0]

        def _mi_behavior(req, schema):
            return {
                "proposal_type": "add_edge",
                "source_object_ids": [f"Evidence:{ev_id}"],
                "candidate_node": None,
                "candidate_edge": {
                    "source_node_id": "company:600519.SH",
                    "relation": "BENEFITS_FROM",
                    "target_node_id":
                        "industry_segment:ai_software:enterprise_software",
                    "attributes": {},
                    "assertion_type": "MODEL_INFERENCE",
                    "valid_from": None, "valid_to": None,
                    "confidence": 0.75,
                },
                "new_evidence_ids": [ev_id],
                "suggested_change": "茅台 BENEFITS_FROM AI软件",
                "impact_scope": ["MODEL_INFERENCE"],
                "conflicts": [], "verification_points": [],
                "confidence": 0.75,
            }

        mi_r = _run_candidate_pipeline(
            db, c, [("Evidence", ev_id)], _mi_behavior
        )
        assert mi_r["status"] == "ok"
        mi_gc = mi_r["candidates"][0]["graph_change_id"]

        # graph_edges delta == 0 before review
        e_mid = db._conn.execute(
            "SELECT COUNT(*) FROM graph_edges").fetchone()[0]
        assert e_mid == n_before

        mi_rwa = _review_and_apply(c, mi_gc, reviewer_id="human-c-mi")
        assert mi_rwa["apply"].status == "applied", (
            mi_rwa["apply"].error_code, mi_rwa["apply"].errors
        )

        # ── Query MODEL_INFERENCE partition ──
        qr = c["query"].query_graph("company:600519.SH",
                                     as_of="2026-08-09T12:00:00", max_depth=1)
        mi_edges = [e for e in qr.edges
                    if e["payload"].get("assertion_type") == "MODEL_INFERENCE"]
        assert len(mi_edges) >= 1
        assert mi_edges[0]["payload"]["assertion_type"] == "MODEL_INFERENCE"

        # NOT in facts
        fact_edges = [e for e in qr.edges
                      if e["payload"].get("assertion_type") == "FACT"]
        ben_fact = [e for e in fact_edges
                    if e["payload"].get("relation") == "BENEFITS_FROM"]
        assert len(ben_fact) == 0

        # ── Export ──
        kroot = tmp_path / "knowledge"
        with KnowledgeMirrorExporter(
            project_root=tmp_path, knowledge_root=kroot,
            db_path=tmp_path / "test.db",
        ) as exp:
            r = exp.export(dry_run=False)
            assert r.status == "ok"


# ══════════════════════════════════════════════════════════════
#  Case D — Conflict via CandidatePipeline
# ══════════════════════════════════════════════════════════════

class TestCaseDConflict:

    def test_conflict_apply_rejected(self, tmp_path):
        """Genuinely incompatible Evidence → CandidatePipeline →
        provider proposal with conflicts → ReviewWorkflow → approved
        → apply rejected。"""
        db = _fresh_db(tmp_path)
        _seed_ontology(db)
        c = _make_components(db)

        _persist_entity(db, "company:600519.SH", "贵州茅台")
        # Synthetic sources for conflict test (NOT SSE)
        _persist_source(db, source_id="m10_synthetic_a", source_tier="A", name="M10 Synthetic Source A")
        _persist_source(db, source_id="m10_synthetic_b", source_tier="B", name="M10 Synthetic Source B")

        # Evidence A: official S-tier — explicitly states X
        raw_a = _persist_raw_item(db, [
            "company:600519.SH",
            "industry_segment:ai_hardware:compute_chip",
        ], title="TEST SYNTHETIC RAW A",
          excerpt="TEST FIXTURE — consumer products, no compute chip.",
          source_id="m10_synthetic_a",
          url="https://source-a.example.com/evidence-a")
        ev_a = _persist_evidence(db, raw_a,
            title="TEST SYNTHETIC CONFLICT EVIDENCE A",
            excerpt="TEST FIXTURE — 600519 does NOT supply compute chips. Consumer products only.",
            source_id="m10_synthetic_a",
            independence_group="m10-synthetic-a",
            url="https://source-a.example.com/evidence-a")

        # Evidence B: B-tier — contradicts, claims compute chip
        raw_b = _persist_raw_item(db, ["company:600519.SH"],
            title="TEST SYNTHETIC RAW B",
            excerpt="TEST FIXTURE — company IS involved in AI compute chips.",
            source_id="m10_synthetic_b",
            url="https://source-b.example.com/evidence-b")
        ev_b = _persist_evidence(db, raw_b,
            title="TEST SYNTHETIC CONFLICT EVIDENCE B",
            excerpt="TEST FIXTURE — 600519 IS involved in compute chip via cloud partnership.",
            source_tier="B", source_id="m10_synthetic_b",
            independence_group="m10-synthetic-b",
            url="https://source-b.example.com/evidence-b")

        cp_id = _persist_company_profile(
            db, "company:600519.SH", "贵州茅台", [ev_a],
            source_ids=["m10_synthetic_a"]
        )

        # ── add_node via CompanyProfile ──
        def _node_behavior(req, schema):
            return {
                "proposal_type": "add_node",
                "source_object_ids": [f"CompanyProfile:{cp_id}"],
                "candidate_node": {
                    "existing_node_id": None,
                    "node_type": "Company", "name": "贵州茅台",
                    "aliases": [], "description": "",
                    "valid_from": None, "valid_to": None,
                },
                "candidate_edge": None,
                "new_evidence_ids": [ev_a],
                "suggested_change": "新增公司 贵州茅台",
                "impact_scope": ["Company"],
                "conflicts": [], "verification_points": [],
                "confidence": 0.9,
            }

        node_r = _run_candidate_pipeline(
            db, c, [("CompanyProfile", cp_id)], _node_behavior
        )
        assert node_r["status"] == "ok"
        node_gc = node_r["candidates"][0]["graph_change_id"]
        nrwa = _review_and_apply(c, node_gc, reviewer_id="human-d-node")
        assert nrwa["apply"].status == "applied", (
            nrwa["apply"].error_code, nrwa["apply"].errors
        )

        # ── Conflict edge via CandidatePipeline with two incompatible Evidence ──
        provider_was_called = {"count": 0}

        def _conflict_behavior(req, schema):
            provider_was_called["count"] += 1
            # Prove provider receives both Evidence contexts from CandidatePipeline
            req_dump = json.dumps(
                req.model_dump() if hasattr(req, "model_dump") else str(req),
                ensure_ascii=False, sort_keys=True,
            )
            assert ev_a in req_dump, f"Provider must receive ev_a: {ev_a} not in request"
            assert ev_b in req_dump, f"Provider must receive ev_b: {ev_b} not in request"
            # Unique distinctive excerpts per evidence (NOT shared tokens)
            req_lower = req_dump.lower()
            assert "does not supply compute chips" in req_lower,                 "Evidence A unique excerpt missing"
            assert "cloud partnership" in req_lower,                 "Evidence B unique excerpt missing"
            return {
                "proposal_type": "add_edge",
                "source_object_ids": [
                    f"Evidence:{ev_a}", f"Evidence:{ev_b}"
                ],
                "candidate_node": None,
                "candidate_edge": {
                    "source_node_id": "company:600519.SH",
                    "relation": "SUPPLIES",
                    "target_node_id":
                        "industry_segment:ai_hardware:compute_chip",
                    "attributes": {},
                    "assertion_type": "FACT",
                    "valid_from": None, "valid_to": None,
                    "confidence": 0.5,
                },
                "new_evidence_ids": [ev_a, ev_b],
                "suggested_change":
                    "茅台 SUPPLIES compute_chip (conflicting evidence)",
                "impact_scope": ["FACT"],
                "conflicts": [
                    "EVIDENCE_CONFLICT: source_a (S tier) states 白酒消费品; "
                    "source_b (B tier) claims AI算力芯片 involvement.",
                    "SOURCE_TIER_MISMATCH: Two sources present "
                    "incompatible information.",
                ],
                "verification_points": [],
                "confidence": 0.5,
            }

        edges_before = db._conn.execute(
            "SELECT COUNT(*) FROM graph_edges").fetchone()[0]

        conflict_r = _run_candidate_pipeline(
            db, c,
            [("Evidence", ev_a), ("Evidence", ev_b)],
            _conflict_behavior,
        )
        assert conflict_r["status"] == "ok", (
            f"Conflict pipeline: {conflict_r['status']} "
            f"{conflict_r.get('errors', [])}"
        )
        assert provider_was_called["count"] == 1
        conflict_gc = conflict_r["candidates"][0]["graph_change_id"]

        # Verify conflicts persisted (from validated Proposal, not handwritten)
        stored = c["candidate_repo"].get_candidate(conflict_gc)
        assert stored is not None
        if stored.get("canonical_json"):
            gc_payload = json.loads(stored["canonical_json"])
            assert gc_payload.get("conflicts"), "Conflicts must come from Proposal"
            assert len(gc_payload["conflicts"]) >= 1

        # ── ReviewWorkflow → approved → apply rejected ──
        crwa = _review_and_apply(c, conflict_gc,
                                  reviewer_id="human-d-conflict")
        assert crwa["apply"].status != "applied", (
            f"Should be rejected: {crwa['apply'].error_code} "
            f"{crwa['apply'].errors}"
        )
        assert any(x in (crwa["apply"].error_code or "") for x in
                   ("M4_APPLY", "CONFLICT", "APPLY_REJECTED",
                    "BLOCKING_CONFLICT", "KGV", "APPLY_TIME")), \
            f"Expected failure code, got: {crwa['apply'].error_code}"

        edges_after = db._conn.execute(
            "SELECT COUNT(*) FROM graph_edges").fetchone()[0]
        assert edges_after == edges_before

        # Both evidence IDs still present
        for eid in (ev_a, ev_b):
            row = db._conn.execute(
                "SELECT COUNT(*) FROM evidence WHERE evidence_id=?",
                (eid,)
            ).fetchone()[0]
            assert row == 1, f"Evidence {eid} should still exist"
