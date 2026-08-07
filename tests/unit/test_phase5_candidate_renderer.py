"""Phase 5 M3 Candidate Renderer 测试。

覆盖：
- Markdown 渲染包含全部固定分段
- 证据最小信息渲染
- 节点/边信息渲染
- 文件写入幂等性
- CANDIDATE_FILE_CONFLICT
- dry-run 零文件写入
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research_os.knowledge.candidate_renderer import (
    CandidateRenderer,
    render_candidate_markdown,
    EvidenceContext,
)
from research_os.models import (
    GraphChange,
    GraphNode,
    GraphEdge,
)

T0 = "2026-08-07T17:00:00+08:00"


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
    gc = _make_graph_change("11111111-1111-1111-1111-111111111111")
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


def test_render_includes_graph_change_id():
    """渲染包含 graph_change_id。"""
    gc = _make_graph_change("22222222-2222-2222-2222-222222222222")
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert "22222222-2222-2222-2222-222222222222" in md


def test_render_shows_suggested_change():
    """渲染包含建议变更。"""
    gc = _make_graph_change("33333333-3333-3333-3333-333333333333")
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert "测试建议变更描述" in md


def test_render_shows_impact():
    """渲染包含影响范围。"""
    gc = _make_graph_change("44444444-4444-4444-4444-444444444444")
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert "供应链" in md
    assert "竞品" in md


def test_render_shows_conflicts():
    """渲染包含冲突。"""
    gc = _make_graph_change("55555555-5555-5555-5555-555555555555")
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert "潜在冲突1" in md


def test_render_shows_evidence():
    """渲染包含证据信息。"""
    gc = _make_graph_change("66666666-6666-6666-6666-666666666666")
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert "测试证据" in md
    assert "反证证据" in md
    assert "ev:001" in md
    assert "ev:002" in md


def test_render_shows_review_checkboxes():
    """渲染包含审核清单复选框。"""
    gc = _make_graph_change("77777777-7777-7777-7777-777777777777")
    md = render_candidate_markdown(gc, _make_evidence_contexts())
    assert "- [ ]" in md


def test_render_empty_evidence():
    """无证据时显示占位文本。"""
    gc = _make_graph_change("88888888-8888-8888-8888-888888888888")
    md = render_candidate_markdown(gc, [])
    assert "无证据上下文" in md


def test_render_empty_current_knowledge():
    """无 current_knowledge 时显示占位文本。"""
    gc = _make_graph_change(
        "99999999-9999-9999-9999-999999999999",
        current_knowledge="",
    )
    md = render_candidate_markdown(gc, [])
    assert "无当前知识" in md


# ---- 文件写入 ----

def test_render_to_file(tmp_path):
    """渲染到文件并验证内容。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    gc = _make_graph_change("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    file_path = renderer.render_to_file(gc, _make_evidence_contexts())
    assert file_path != "dry-run"
    assert Path(file_path).exists()
    content = Path(file_path).read_text(encoding="utf-8")
    assert "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" in content


def test_render_to_file_idempotent(tmp_path):
    """同内容文件写入幂等。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    gc = _make_graph_change("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    p1 = renderer.render_to_file(gc, _make_evidence_contexts())
    p2 = renderer.render_to_file(gc, _make_evidence_contexts())
    assert p1 == p2  # 幂等，同路径


def test_render_to_file_conflict(tmp_path):
    """同 ID 异内容抛出 CANDIDATE_FILE_CONFLICT。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    gc1 = _make_graph_change("cccccccc-cccc-cccc-cccc-cccccccccccc")
    gc2 = _make_graph_change(
        "cccccccc-cccc-cccc-cccc-cccccccccccc",
        suggested_change="不同的变更",
    )

    renderer.render_to_file(gc1, _make_evidence_contexts())
    with pytest.raises(ValueError, match="CANDIDATE_FILE_CONFLICT"):
        renderer.render_to_file(gc2, _make_evidence_contexts())


def test_render_dry_run_no_file(tmp_path):
    """dry-run 不写文件。"""
    knowledge_dir = tmp_path / "knowledge"
    renderer = CandidateRenderer(knowledge_dir)
    gc = _make_graph_change("dddddddd-dddd-dddd-dddd-dddddddddddd")

    result = renderer.render_to_file(
        gc, _make_evidence_contexts(), dry_run=True
    )
    assert result == "dry-run"
    candidates_dir = knowledge_dir / "candidates"
    assert not (candidates_dir / f"{gc.graph_change_id}.md").exists()
