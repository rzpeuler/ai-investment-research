"""Phase 5 M3 Candidate Renderer 测试。

覆盖：
- Markdown 渲染包含全部固定分段（frozen headings）
- 证据最小信息渲染
- 节点/边信息渲染
- 文件写入幂等性
- CANDIDATE_FILE_CONFLICT
- dry-run 零文件写入
- 文件冲突预检（preflight_file_conflict）
- 标题确定性：严格冻结格式
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from research_os.knowledge.candidate_renderer import (
    CandidateRenderer,
    render_candidate_markdown,
    EvidenceContext,
    _FROZEN_HEADINGS,
)
from research_os.models import (
    GraphChange,
    GraphNode,
    GraphEdge,
)

T0 = "2026-08-07T17:00:00+08:00"


def _make_valid_uuid_id(prefix=""):
    """生成合法 UUID 格式的 graph_change_id。"""
    return str(uuid.uuid4())


VALID_ID_1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
VALID_ID_2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2"
VALID_ID_3 = "cccccccc-cccc-cccc-cccc-ccccccccccc3"
VALID_ID_4 = "dddddddd-dddd-dddd-dddd-ddddddddddd4"
VALID_ID_5 = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeee5"
VALID_ID_6 = "ffffffff-ffff-ffff-ffff-fffffffffff6"
VALID_ID_7 = "11111111-1111-1111-1111-111111111111"
VALID_ID_8 = "22222222-2222-2222-2222-222222222222"
VALID_ID_9 = "33333333-3333-3333-3333-333333333333"
VALID_ID_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
VALID_ID_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
VALID_ID_C = "cccccccc-cccc-cccc-cccc-cccccccccccc"
VALID_ID_D = "dddddddd-dddd-dddd-dddd-dddddddddddd"
VALID_ID_E = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
VALID_ID_F = "ffffffff-ffff-ffff-ffff-ffffffffffff"
VALID_ID_G = "00000000-0000-0000-0000-000000000000"  # hex-only UUID
VALID_ID_DET = "d1111111-1111-1111-1111-111111111111"


def _make_graph_change(change_id, **kw):
    node = GraphNode(
        node_id="company:test-node",
        node_type="Company",
        name="测试节点",
        aliases=["测试"],
        description="测试描述",
        status="active",
        valid_from=None,
        valid_to=None,
        evidence_ids=["ev:001"],
        version=1,
        last_reviewed_at=None,
        review_status="candidate",
        origin_kind="graph_change",
        originating_graph_change_id="11111111-1111-1111-1111-111111111111",
        created_at=T0,
    )

    defaults = {
        "graph_change_id": change_id,
        "change_type": "add_node",
        "node": node,
        "edge": None,
        "current_knowledge": '{"test": "knowledge"}',
        "new_evidence_ids": ["ev:001"],
        "suggested_change": "测试建议变更描述",
        "impact_scope": ["供应链", "竞品"],
        "conflicts": ["潜在冲突1"],
        "verification_points": ["验证点1", "验证点2"],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    defaults.update(kw)
    return GraphChange(**defaults)


def _make_evidence_contexts():
    return [
        EvidenceContext(
            evidence_id="ev:001",
            title="测试证据",
            publisher="测试发布者",
            published_at=T0,
            source_tier="A",
            evidence_type="official_disclosure",
            excerpt="测试摘录内容，不超过200字",
            url="https://example.com/evidence/1",
            role="supporting",
        ),
        EvidenceContext(
            evidence_id="ev:002",
            title="反证证据",
            publisher="反方发布者",
            published_at=T0,
            source_tier="B",
            evidence_type="media_report",
            excerpt="反证摘录内容",
            url="https://example.com/evidence/2",
            role="counter",
        ),
    ]


# ---- Markdown 渲染 ----

def test_render_has_all_sections():
    """渲染输出包含全部固定分段。"""
    gc = _make_graph_change(VALID_ID_1)
    md = render_candidate_markdown(gc, _make_evidence_contexts())

    assert "## 1. 变更标识" in md
    assert "## 2. 当前图谱知识" in md
    assert "## 3. 新证据" in md
    assert "## 4. 建议变更" in md
    assert "## 5. 影响范围" in md
    assert "## 6. 冲突" in md
    assert "## 7. 验证点" in md
    assert "## 8. 变更载体" in md
    assert "## 9. 审核清单" in md
    assert "## 10. 审核决定" in md
    assert "## 11. 批准补丁" in md


def test_render_frozen_headings_unmodified():
    """标题格式为严格冻结格式。"""
    assert "## 1. 变更标识" in _FROZEN_HEADINGS
    assert "## 11. 批准补丁" in _FROZEN_HEADINGS
    assert len(_FROZEN_HEADINGS) == 11


def test_render_includes_graph_change_id():
    """渲染包含 graph_change_id。"""
    gc = _make_graph_change(VALID_ID_2)
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert VALID_ID_2 in md


def test_render_shows_suggested_change():
    """渲染包含建议变更。"""
    gc = _make_graph_change(VALID_ID_3)
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert "测试建议变更描述" in md


def test_render_shows_impact():
    """渲染包含影响范围。"""
    gc = _make_graph_change(VALID_ID_4)
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert "供应链" in md
    assert "竞品" in md


def test_render_shows_conflicts():
    """渲染包含冲突。"""
    gc = _make_graph_change(VALID_ID_5)
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert "潜在冲突1" in md


def test_render_shows_evidence():
    """渲染包含证据信息。"""
    gc = _make_graph_change(VALID_ID_6)
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert "测试证据" in md
    assert "反证证据" in md
    assert "ev:001" in md
    assert "ev:002" in md


def test_render_shows_review_checkboxes():
    """渲染包含审核清单复选框。"""
    gc = _make_graph_change(VALID_ID_7)
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert "- [ ]" in md


def test_render_empty_evidence():
    """无证据时显示占位文本。"""
    gc = _make_graph_change(VALID_ID_8)
    md = render_candidate_markdown(gc, [])
    assert "无证据上下文" in md


def test_render_empty_current_knowledge():
    """无 current_knowledge 时显示占位文本。"""
    gc = _make_graph_change(VALID_ID_9, current_knowledge="")
    md = render_candidate_markdown(gc, [])
    assert "无当前知识" in md


# ---- 渲染确定性 ----

def test_render_deterministic():
    """相同输入 → 相同输出（跨调用字节确定性）。"""
    gc = _make_graph_change(VALID_ID_DET)
    md1 = render_candidate_markdown(gc, _make_evidence_contexts())
    md2 = render_candidate_markdown(gc, _make_evidence_contexts())
    assert md1 == md2
    # 哈希也应相同
    assert hashlib.sha256(md1.encode("utf-8")).hexdigest() == hashlib.sha256(md2.encode("utf-8")).hexdigest()


# ---- 文件写入 ----

def test_render_to_file(tmp_path):
    """渲染到文件并验证内容。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    gc = _make_graph_change(VALID_ID_A)

    file_path = renderer.render_to_file(gc, _make_evidence_contexts())
    assert file_path != "dry-run"
    assert Path(file_path).exists()
    content = Path(file_path).read_text(encoding="utf-8")
    assert VALID_ID_A in content


def test_render_to_file_idempotent(tmp_path):
    """同内容文件写入幂等。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    gc = _make_graph_change(VALID_ID_B)

    p1 = renderer.render_to_file(gc, _make_evidence_contexts())
    p2 = renderer.render_to_file(gc, _make_evidence_contexts())
    assert p1 == p2  # 幂等，同路径


def test_render_to_file_conflict(tmp_path):
    """同 ID 异内容抛出 CANDIDATE_FILE_CONFLICT。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    gc1 = _make_graph_change(VALID_ID_C)
    gc2 = _make_graph_change(VALID_ID_C, suggested_change="不同的变更")

    renderer.render_to_file(gc1, _make_evidence_contexts())
    with pytest.raises(ValueError, match="CANDIDATE_FILE_CONFLICT"):
        renderer.render_to_file(gc2, _make_evidence_contexts())


def test_render_dry_run_no_file(tmp_path):
    """dry-run 不写文件。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    gc = _make_graph_change(VALID_ID_D)

    result = renderer.render_to_file(
        gc, _make_evidence_contexts(), dry_run=True
    )
    assert result == "dry-run"
    candidates_dir = knowledge_dir / "candidates"
    assert not (candidates_dir / f"{gc.graph_change_id}.md").exists()


# ---- 文件冲突预检（preflight_file_conflict）----

def test_preflight_file_conflict_new_file(tmp_path):
    """新文件预检通过。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    gc = _make_graph_change(VALID_ID_E)

    result = renderer.preflight_file_conflict(gc)
    assert result is True  # OK


def test_preflight_file_conflict_idempotent(tmp_path):
    """已有文件且同内容 → 幂等通过。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    gc = _make_graph_change(VALID_ID_F)

    # 先写入（用空 evidence 匹配 preflight 的内容）
    renderer.render_to_file(gc, [])
    # 预检幂等通过
    result = renderer.preflight_file_conflict(gc)
    assert result is True


def test_preflight_file_conflict_rejected(tmp_path):
    """已有文件但内容不同 → CANDIDATE_FILE_CONFLICT。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    gc1 = _make_graph_change(VALID_ID_G)
    gc2 = _make_graph_change(VALID_ID_G, suggested_change="不同的变更内容")

    # 写入 gc1 (preflight content 匹配 gc1)
    renderer.render_to_file(gc1, [])
    # gc2 preflight 会生成不同内容 → conflict
    with pytest.raises(ValueError, match="CANDIDATE_FILE_CONFLICT"):
        renderer.preflight_file_conflict(gc2)


def test_init_no_mkdir(tmp_path):
    """__init__ 不创建目录。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    # __init__ should not create candidates dir
    candidates_dir = knowledge_dir / "candidates"
    assert not candidates_dir.exists()
