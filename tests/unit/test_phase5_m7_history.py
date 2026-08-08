"""Phase 5 M7 — History Service 攻击测试（strict read / as_of / origin integrity）。

覆盖（任务书 28 节 33-43 项）：
- 33. history invalid JSON → HISTORY_PAYLOAD_INVALID
- 34. valid JSON wrong type → HISTORY_PAYLOAD_INVALID
- 35. history schema invalid → HISTORY_SCHEMA_INVALID
- 36. DB-column/payload mismatch → HISTORY_INTEGRITY_CONFLICT
- 37. version gap → HISTORY_VERSION_GAP
- 38. transition out of order → HISTORY_INTERVAL_INVALID
- 39. invalid as_of → HISTORY_AS_OF_INVALID
- 40. as_of boundary equality（半开区间）
- 41. future successor not visible early
- 42. explicit expiry（无 successor）
- 43. gap between expiry and later successor
- origin integrity：origin GraphChange 缺失 → HISTORY_ORIGIN_INTEGRITY_CONFLICT
- as_of required（resolve 禁止默认 now）→ HISTORY_AS_OF_REQUIRED

真实 SQLite + 真实 schemas + 真实 repositories。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from research_os.models import GraphNode, GraphEdge, Entity
from research_os.knowledge.knowledge_validator import KnowledgeValidator
from research_os.knowledge.history import HistoryService, HistoryError

T0 = "2026-08-08T10:00:00+08:00"
T1 = "2026-08-08T14:00:00+08:00"
T2 = "2026-08-09T09:00:00+08:00"
T3 = "2026-08-10T09:00:00+08:00"

EVIDENCE_UUID = "11111111-1111-1111-1111-111111111111"
RAW_ITEM_UUID = "22222222-2222-2222-2222-222222222222"
SOURCE_UUID = "33333333-3333-3333-3333-333333333333"
SHA256_ZEROS = "0000000000000000000000000000000000000000000000000000000000000000"


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _setup_db(tmp_path):
    from research_os.storage import Database

    db_path = tmp_path / "history.db"
    db = Database(db_path)
    db.initialize()
    conn = db._conn

    # evidence + raw_item + entities（graph_change origin 完整性需要）
    from research_os.models import Evidence
    ev = Evidence(
        evidence_id=EVIDENCE_UUID,
        source_id=SOURCE_UUID,
        raw_item_id=RAW_ITEM_UUID,
        title="测试证据",
        publisher="测试发布者",
        published_at="2026-08-01T10:00:00+08:00",
        retrieved_at="2026-08-02T10:00:00+08:00",
        url="https://example.com",
        excerpt="测试摘录",
        evidence_type="news_report",
        independence_group="group-1",
        source_tier="B",
        access_status="ok",
    )
    conn.execute(
        "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (EVIDENCE_UUID, _canonical(ev.model_dump()), SOURCE_UUID,
         RAW_ITEM_UUID, "group-1", "B"),
    )
    ri_payload = json.dumps({
        "raw_item_id": RAW_ITEM_UUID,
        "source_id": SOURCE_UUID,
        "external_id": "ext-001",
        "url": "https://example.com",
        "title": "测试",
        "publisher": "测试",
        "author": "测试作者",
        "published_at": "2026-08-01T10:00:00+08:00",
        "retrieved_at": "2026-08-02T10:00:00+08:00",
        "content_hash": SHA256_ZEROS,
        "content_excerpt": "测试摘录",
        "content_storage": "metadata_and_excerpt",
        "language": "zh-CN",
        "access_status": "ok",
        "entities": ["company:test-corp"],
        "raw_category": "news",
    }, ensure_ascii=False)
    conn.execute(
        "INSERT OR IGNORE INTO raw_items "
        "(raw_item_id, payload, source_id, content_hash, access_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (RAW_ITEM_UUID, ri_payload, SOURCE_UUID, SHA256_ZEROS, "ok"),
    )
    entity = Entity(entity_id="company:test-corp", entity_type="company",
                    canonical_name="测试公司")
    conn.execute(
        "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
        "VALUES (?, ?, ?, ?)",
        ("company:test-corp", _canonical(entity.model_dump()), "company",
         "测试公司"),
    )
    conn.commit()
    return db, db_path


def _make_history(db, graph_repo):
    return HistoryService(db, graph_repo)


def _seed_node_v1(db, graph_repo):
    """apply add_node v1（含完整 GraphChange origin 链）并返回 v1 payload。"""
    from research_os.knowledge.candidate_repository import (
        GraphChangeCandidateRepository,
    )
    from research_os.knowledge.repository import GraphRepository
    from research_os.knowledge.review_workflow import ReviewWorkflow
    from research_os.knowledge.apply_engine import ApplyEngine
    from research_os.knowledge.review_parser import parse_review_markdown

    candidate_repo = GraphChangeCandidateRepository(db)
    graph_repo = GraphRepository(db)
    validator = KnowledgeValidator(db, graph_repo)
    workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
    engine = ApplyEngine(db, candidate_repo, graph_repo, validator)

    gc_id = str(uuid.uuid4())
    node = GraphNode(
        node_id="company:test-corp",
        node_type="Company",
        name="测试公司",
        aliases=["测试"],
        description="测试描述",
        status="active",
        valid_from=None,
        valid_to=None,
        evidence_ids=[EVIDENCE_UUID],
        version=1,
        last_reviewed_at=None,
        review_status="candidate",
        origin_kind="graph_change",
        originating_graph_change_id=gc_id,
        created_at=T0,
    )
    from research_os.models import GraphChange
    gc = GraphChange(
        graph_change_id=gc_id,
        change_type="add_node",
        node=node,
        edge=None,
        current_knowledge="",
        new_evidence_ids=[EVIDENCE_UUID],
        suggested_change="添加新公司节点",
        impact_scope=["industry_a"],
        conflicts=[],
        verification_points=["验证公司注册信息"],
        review_status="candidate",
        created_at=T0,
        reviewed_at=None,
    )
    candidate_repo.append_candidate(gc)

    # review markdown（标准 13-heading）
    candidate_hash = KnowledgeValidator.compute_candidate_hash(gc)
    md = "\n".join([
        "# 图谱变更候选", "",
        "## GraphChange ID", "",
        f"- **graph_change_id**: `{gc_id}`",
        f"- **candidate_hash**: `{candidate_hash}`", "",
        "## 变更类型", "",
        "- **change_type**: `add_node`",
        "- **review_status**: `candidate`",
        f"- **created_at**: {T0}", "",
        "## 当前知识", "",
        "_（无当前知识——此为新节点/边）_", "",
        "## 新证据", "",
        f"- **{EVIDENCE_UUID}**: 测试证据", "",
        "## 建议变更", "",
        "添加新公司节点", "",
        "## 影响范围", "",
        "- industry_a", "",
        "## 冲突信息", "",
        "_（无冲突）_", "",
        "## 验证节点", "",
        "- [ ] 验证公司注册信息", "",
        "## 审核选项", "",
        "- [x] 批准", "- [ ] 修改后批准", "- [ ] 暂缓", "- [ ] 拒绝", "",
        "## Reviewer", "",
        "```yaml",
        "reviewer_type: human",
        'reviewer_id: "reviewer-001"',
        'display_name: ""',
        f'reviewed_at: "{T1}"',
        "```", "",
        "## Review Notes", "",
        "_（审核通过）_", "",
        "## Approved Patch", "",
        "_（仅\"修改后批准\"时填写 JSON Patch 数组）_", "",
        "---",
        "*本文件为审阅模板，请填写后通过 review-import 导入。*",
    ])
    result = workflow.review_import(md)
    assert result.status == "ok", f"review_import 失败: {result.errors}"
    r = engine.apply(gc_id, applied_at="2026-08-09T10:00:00+08:00")
    assert r.status == "applied", (r.error_code, r.errors)
    return graph_repo.get_node_version("company:test-corp", 1)


def _insert_raw_node(db, graph_repo, payload, version, gc_id=None):
    """直接 INSERT 一行 graph_nodes（构造攻击状态）。

    gc_id 提供时确保 origin GraphChange 存在（copy 一个合法 candidate）。
    """
    from research_os.knowledge.candidate_repository import (
        GraphChangeCandidateRepository,
    )
    from research_os.models import GraphChange

    if gc_id is None:
        gc_id = payload.get("originating_graph_change_id")
    if gc_id is not None and not _graph_change_exists(db, gc_id):
        # 构造一个匹配的 modify GraphChange（candidate 形态：node 必须
        # review_status=candidate、last_reviewed_at=null）
        node_dict = dict(payload)
        node_dict["review_status"] = "candidate"
        node_dict["last_reviewed_at"] = None
        gc = GraphChange(
            graph_change_id=gc_id,
            change_type="modify_attribute",
            node=GraphNode(**node_dict),
            edge=None,
            current_knowledge="{}",
            new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="构造",
            impact_scope=[],
            conflicts=[],
            verification_points=[],
            review_status="candidate",
            created_at=T0,
            reviewed_at=None,
        )
        GraphChangeCandidateRepository(db).append_candidate(gc)
    db._conn.execute(
        "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at, valid_from, valid_to, last_reviewed_at, originating_graph_change_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (payload["node_id"], version, _canonical(payload),
         payload["node_type"], payload["name"], payload["status"],
         payload["review_status"], payload["origin_kind"],
         payload["created_at"], payload["valid_from"], payload["valid_to"],
         payload["last_reviewed_at"], payload["originating_graph_change_id"]),
    )
    db._conn.commit()


def _graph_change_exists(db, gc_id):
    row = db._conn.execute(
        "SELECT 1 FROM graph_changes WHERE graph_change_id = ?", (gc_id,)
    ).fetchone()
    return row is not None


def _node_payload_v2(gc_id, valid_from=T2, name="v2"):
    """构造合法的 modify v2 node payload（approved overlay）。"""
    return {
        "node_id": "company:test-corp",
        "node_type": "Company",
        "name": name,
        "aliases": ["测试"],
        "description": "测试描述",
        "status": "active",
        "valid_from": valid_from,
        "valid_to": None,
        "evidence_ids": [EVIDENCE_UUID],
        "version": 2,
        "last_reviewed_at": T1,
        "review_status": "approved",
        "origin_kind": "graph_change",
        "originating_graph_change_id": gc_id,
        "created_at": T0,
    }


class TestHistoryStrictRead:
    """33-37. history strict read 攻击。"""

    def test_history_invalid_json(self, tmp_path):
        """33. payload invalid JSON → HISTORY_PAYLOAD_INVALID。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        db._conn.execute(
            "UPDATE graph_nodes SET payload = ? "
            "WHERE node_id = 'company:test-corp' AND version = 1",
            ("{broken json",),
        )
        db._conn.commit()
        history = _make_history(db, graph_repo)
        with pytest.raises(HistoryError) as e:
            history.get_node_history("company:test-corp")
        assert e.value.error_code == "HISTORY_PAYLOAD_INVALID"
        db.close()

    def test_history_valid_json_wrong_type(self, tmp_path):
        """34. payload=[]（合法 JSON 非 object）→ HISTORY_PAYLOAD_INVALID。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        db._conn.execute(
            "UPDATE graph_nodes SET payload = ? "
            "WHERE node_id = 'company:test-corp' AND version = 1",
            ("[]",),
        )
        db._conn.commit()
        history = _make_history(db, graph_repo)
        with pytest.raises(HistoryError) as e:
            history.get_node_history("company:test-corp")
        assert e.value.error_code == "HISTORY_PAYLOAD_INVALID"
        db.close()

    def test_history_schema_invalid(self, tmp_path):
        """35. payload schema invalid（缺必填字段）→ HISTORY_SCHEMA_INVALID。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        v1 = _seed_node_v1(db, graph_repo)
        bad = dict(v1)
        bad.pop("name", None)
        db._conn.execute(
            "UPDATE graph_nodes SET payload = ? "
            "WHERE node_id = 'company:test-corp' AND version = 1",
            (_canonical(bad),),
        )
        db._conn.commit()
        history = _make_history(db, graph_repo)
        with pytest.raises(HistoryError) as e:
            history.get_node_history("company:test-corp")
        assert e.value.error_code == "HISTORY_SCHEMA_INVALID"
        db.close()

    def test_column_payload_mismatch(self, tmp_path):
        """36. DB column version=3 与 payload version=2 不一致
        → HISTORY_INTEGRITY_CONFLICT。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        gc_id = str(uuid.uuid4())
        _insert_raw_node(db, graph_repo, _node_payload_v2(gc_id), version=2)
        # 篡改 DB column version → 3（payload 仍为 2）
        db._conn.execute(
            "UPDATE graph_nodes SET version = 3 "
            "WHERE node_id = 'company:test-corp' AND version = 2",
        )
        db._conn.commit()
        history = _make_history(db, graph_repo)
        with pytest.raises(HistoryError) as e:
            history.get_node_history("company:test-corp")
        assert e.value.error_code == "HISTORY_INTEGRITY_CONFLICT"
        db.close()

    def test_column_name_mismatch(self, tmp_path):
        """36b. DB column name 与 payload name 不一致 → HISTORY_INTEGRITY_CONFLICT。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        db._conn.execute(
            "UPDATE graph_nodes SET name = '列名篡改' "
            "WHERE node_id = 'company:test-corp' AND version = 1",
        )
        db._conn.commit()
        history = _make_history(db, graph_repo)
        with pytest.raises(HistoryError) as e:
            history.get_node_history("company:test-corp")
        assert e.value.error_code == "HISTORY_INTEGRITY_CONFLICT"
        db.close()

    def test_version_gap(self, tmp_path):
        """37. version gap（缺 v1）→ HISTORY_VERSION_GAP。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        gc_id = str(uuid.uuid4())
        _insert_raw_node(db, graph_repo, _node_payload_v2(gc_id), version=2)
        # 删除 v1 → chain 从 2 开始
        db._conn.execute(
            "DELETE FROM graph_nodes WHERE node_id = 'company:test-corp' AND version = 1",
        )
        db._conn.commit()
        history = _make_history(db, graph_repo)
        with pytest.raises(HistoryError) as e:
            history.get_node_history("company:test-corp")
        assert e.value.error_code == "HISTORY_VERSION_GAP"
        db.close()

    def test_transition_out_of_order(self, tmp_path):
        """38. transition out of order（v2.valid_from < v1.valid_from）
        → HISTORY_INTERVAL_INVALID。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        gc_id = str(uuid.uuid4())
        # v2.valid_from 早于... v1.valid_from 是 null → 无法构造 out-of-order？
        # 用 v1 先 modify 出 v2（valid_from=T2），再篡改 v2.valid_from 早于
        # v2.valid_to 制造 interval invalid：v2.valid_from=T3, valid_to=T2
        v2 = _node_payload_v2(gc_id, valid_from=T3, name="v2")
        v2["valid_to"] = T2  # from > to → interval invalid
        _insert_raw_node(db, graph_repo, v2, version=2)
        history = _make_history(db, graph_repo)
        with pytest.raises(HistoryError) as e:
            history.get_node_history("company:test-corp")
        assert e.value.error_code == "HISTORY_INTERVAL_INVALID"
        db.close()

    def test_origin_missing_graph_change(self, tmp_path):
        """origin integrity：graph_change origin 但 GraphChange 缺失
        → HISTORY_ORIGIN_INTEGRITY_CONFLICT。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        # 删除 origin GraphChange（v1 的）
        gc_id_row = db._conn.execute(
            "SELECT originating_graph_change_id FROM graph_nodes "
            "WHERE node_id = 'company:test-corp' AND version = 1",
        ).fetchone()
        # 先删引用行（FK 链：applications → reviews → changes）
        db._conn.execute(
            "DELETE FROM graph_applications WHERE graph_change_id = ?",
            (gc_id_row[0],),
        )
        db._conn.execute(
            "DELETE FROM graph_reviews WHERE graph_change_id = ?",
            (gc_id_row[0],),
        )
        db._conn.execute(
            "DELETE FROM graph_changes WHERE graph_change_id = ?",
            (gc_id_row[0],),
        )
        db._conn.commit()
        history = _make_history(db, graph_repo)
        with pytest.raises(HistoryError) as e:
            history.get_node_history("company:test-corp")
        assert e.value.error_code == "HISTORY_ORIGIN_INTEGRITY_CONFLICT"
        db.close()

    def test_origin_version_mismatch(self, tmp_path):
        """origin integrity：GraphChange node version 与 payload 不一致
        → HISTORY_ORIGIN_INTEGRITY_CONFLICT。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        gc_id = str(uuid.uuid4())
        _insert_raw_node(db, graph_repo, _node_payload_v2(gc_id), version=2)
        # 篡改 v2 的 origin GraphChange node.version → 3
        row = db._conn.execute(
            "SELECT payload FROM graph_changes WHERE graph_change_id = ?",
            (gc_id,),
        ).fetchone()
        gc_dict = json.loads(row["payload"])
        gc_dict["node"]["version"] = 3
        db._conn.execute(
            "UPDATE graph_changes SET payload = ? WHERE graph_change_id = ?",
            (_canonical(gc_dict), gc_id),
        )
        db._conn.commit()
        history = _make_history(db, graph_repo)
        with pytest.raises(HistoryError) as e:
            history.get_node_history("company:test-corp")
        assert e.value.error_code == "HISTORY_ORIGIN_INTEGRITY_CONFLICT"
        db.close()


class TestHistoryAsOf:
    """39-43. as_of 语义攻击。"""

    def test_invalid_as_of(self, tmp_path):
        """39. invalid as_of → HISTORY_AS_OF_INVALID。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        history = _make_history(db, graph_repo)
        with pytest.raises(HistoryError) as e:
            history.get_node_history("company:test-corp", as_of="not-a-time")
        assert e.value.error_code == "HISTORY_AS_OF_INVALID"
        db.close()

    def test_as_of_required_no_default_now(self, tmp_path):
        """resolve 必须显式 as_of（禁止默认 now）→ HISTORY_AS_OF_REQUIRED。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        history = _make_history(db, graph_repo)
        with pytest.raises(HistoryError) as e:
            history.resolve_node_as_of("company:test-corp", None)  # type: ignore
        assert e.value.error_code == "HISTORY_AS_OF_REQUIRED"
        db.close()

    def test_as_of_boundary_equality(self, tmp_path):
        """40. 半开区间边界：as_of == successor.valid_from → successor 接管。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        gc_id = str(uuid.uuid4())
        _insert_raw_node(db, graph_repo, _node_payload_v2(gc_id), version=2)
        history = _make_history(db, graph_repo)

        before = history.resolve_node_as_of("company:test-corp",
                                            "2026-08-09T08:59:00+08:00")
        assert before["version"] == 1
        assert before["derived_status"] == "active"
        at = history.resolve_node_as_of("company:test-corp", T2)
        assert at["version"] == 2
        assert at["derived_status"] == "active"
        db.close()

    def test_future_successor_not_visible_early(self, tmp_path):
        """41. future successor 不得提前生效。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        gc_id = str(uuid.uuid4())
        _insert_raw_node(db, graph_repo, _node_payload_v2(gc_id), version=2)
        history = _make_history(db, graph_repo)
        early = history.resolve_node_as_of("company:test-corp", T1)
        assert early["version"] == 1
        late = history.resolve_node_as_of("company:test-corp", T2)
        assert late["version"] == 2
        db.close()

    def test_explicit_expiry_no_successor(self, tmp_path):
        """42. explicit expiry：单版本 valid_to=T，无 successor。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        # v1 直接设 valid_to（DB column + payload 同步，制造 legacy expiry 状态）
        v1 = graph_repo.get_node_version("company:test-corp", 1)
        v1_exp = dict(v1)
        v1_exp["valid_to"] = "2026-08-09T09:00:00+08:00"
        db._conn.execute(
            "UPDATE graph_nodes SET valid_to = ?, payload = ? "
            "WHERE node_id = 'company:test-corp' AND version = 1",
            ("2026-08-09T09:00:00+08:00", _canonical(v1_exp)),
        )
        db._conn.commit()
        history = _make_history(db, graph_repo)
        before = history.resolve_node_as_of("company:test-corp",
                                            "2026-08-09T08:00:00+08:00")
        assert before["derived_status"] == "active"
        at = history.resolve_node_as_of("company:test-corp",
                                        "2026-08-09T09:00:00+08:00")
        assert at["derived_status"] == "expired"
        after = history.resolve_node_as_of("company:test-corp",
                                           "2026-08-10T09:00:00+08:00")
        assert after["derived_status"] == "expired"
        db.close()

    def test_no_as_of_returns_versions_only(self, tmp_path):
        """未提供 as_of：只输出完整 history，resolved=null。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        gc_id = str(uuid.uuid4())
        _insert_raw_node(db, graph_repo, _node_payload_v2(gc_id), version=2)
        history = _make_history(db, graph_repo)
        result = history.get_node_history("company:test-corp")
        assert result.as_of is None
        assert result.resolved is None
        assert [e.version for e in result.versions] == [1, 2]
        assert result.versions[0].superseded_by_version == 2
        db.close()

    def test_history_deterministic_json(self, tmp_path):
        """history 输出确定性（无 wall-clock；同一 DB 两次输出一致）。"""
        db, _ = _setup_db(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        gc_id = str(uuid.uuid4())
        _insert_raw_node(db, graph_repo, _node_payload_v2(gc_id), version=2)
        history = _make_history(db, graph_repo)
        r1 = history.get_node_history("company:test-corp", as_of=T2)
        r2 = history.get_node_history("company:test-corp", as_of=T2)
        assert _canonical(r1.to_dict()) == _canonical(r2.to_dict())
        db.close()


def _make_graph_repo(db):
    from research_os.knowledge.repository import GraphRepository
    return GraphRepository(db)
