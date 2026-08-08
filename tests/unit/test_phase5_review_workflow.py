"""Phase 5 M5 Human Review Workflow 测试。

覆盖：
- review_renderer: 冻结 13-heading 格式、candidate_hash、evidence 展示
- review_parser: 解析、fenced-block 安全、标题验证、checkbox 精确一项、
  human reviewer only、explicit reviewed_at、candidate hash binding
- review_workflow: export/import、JSON Patch、原子持久化、幂等回放
- JSON Patch applier: add/replace/remove、路径白名单、系统字段阻止
- Deterministic IDs: UUID5 确定性
- Dry-run 零写
- review_eligible vs apply_eligible
- M4 integration
- All 4 decisions: approved / approved_with_changes / deferred / rejected
- Replacement GraphChange provenance
- Original immutability
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path

import pytest

from research_os.models import (
    GraphChange, GraphReview, GraphReviewer,
    GraphNode, GraphEdge,
    GraphPatchValueOperation, GraphPatchRemoveOperation,
    Evidence, Entity,
)
from research_os.knowledge.knowledge_validator import KnowledgeValidator
from research_os.knowledge.review_renderer import (
    review_export_markdown,
    _FROZEN_REVIEW_HEADINGS,
)
from research_os.knowledge.review_parser import (
    parse_review_markdown,
    ParsedReview,
    _strip_fenced_blocks,
)
from research_os.knowledge.review_workflow import (
    ReviewWorkflow,
    ExportResult,
    ImportResult,
    apply_json_patch,
    _make_review_id,
    _make_replacement_gc_id,
    compute_review_id,
    _ALLOWED_PATCH_PATHS,
    _BLOCKED_SYSTEM_FIELDS,
)

# candidate hash 唯一 authority（M4）——测试不得使用第二套实现
def _candidate_hash(gc: GraphChange) -> str:
    return KnowledgeValidator.compute_candidate_hash(gc)

# ── Fixtures ──────────────────────────────────────────────────

T0 = "2026-08-08T10:00:00+08:00"
T1 = "2026-08-08T14:00:00+08:00"

VALID_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
VALID_UUID2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2"
VALID_UUID3 = "cccccccc-cccc-cccc-cccc-ccccccccccc3"
VALID_UUID4 = "dddddddd-dddd-dddd-dddd-ddddddddddd4"
VALID_UUID5 = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeee5"

SHA256_ZEROS = "0000000000000000000000000000000000000000000000000000000000000000"

# UUID-format IDs for schema-compliant test fixtures
EVIDENCE_UUID  = "11111111-1111-1111-1111-111111111111"
RAW_ITEM_UUID  = "22222222-2222-2222-2222-222222222222"
SOURCE_UUID    = "33333333-3333-3333-3333-333333333333"


def _make_valid_uuid():
    return str(uuid.uuid4())


def _make_graph_change_node(change_id=VALID_UUID, change_type="add_node", **kw):
    """Create a valid GraphChange with node for testing."""
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
        originating_graph_change_id=VALID_UUID2,
        created_at=T0,
    )

    defaults = {
        "graph_change_id": change_id,
        "change_type": change_type,
        "node": node,
        "edge": None,
        "current_knowledge": "",
        "new_evidence_ids": [EVIDENCE_UUID],
        "suggested_change": "添加新公司节点",
        "impact_scope": ["industry_a"],
        "conflicts": [],
        "verification_points": ["验证公司注册信息"],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    defaults.update(kw)
    return GraphChange(**defaults)


def _make_graph_change_edge(change_id=VALID_UUID, change_type="add_edge", **kw):
    """Create a valid GraphChange with edge for testing."""
    edge = GraphEdge(
        edge_id="edge:test-1",
        source_node_id="company:src",
        relation="COMPETES_WITH",
        target_node_id="company:tgt",
        attributes={},
        assertion_type="FACT",
        valid_from=None,
        valid_to=None,
        confidence=0.8,
        evidence_ids=[EVIDENCE_UUID],
        review_status="candidate",
        version=1,
        originating_graph_change_id=VALID_UUID2,
        created_at=T0,
        last_reviewed_at=None,
    )

    defaults = {
        "graph_change_id": change_id,
        "change_type": change_type,
        "node": None,
        "edge": edge,
        "current_knowledge": json.dumps({"relation": "COMPETES_WITH"}),
        "new_evidence_ids": [EVIDENCE_UUID],
        "suggested_change": "添加竞争关系",
        "impact_scope": ["industry_a", "industry_b"],
        "conflicts": [],
        "verification_points": ["验证两家公司存在竞争关系"],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    defaults.update(kw)
    return GraphChange(**defaults)


def _build_review_markdown(
    gc,
    decision="批准",
    reviewer_id="reviewer-001",
    reviewed_at=T1,
    notes="",
    patch=None,
):
    """Build a filled review Markdown from a GraphChange."""
    candidate_hash = _candidate_hash(gc)
    gc_dump = gc.model_dump()

    sections = []
    # H1
    sections.append("# 图谱变更候选")
    sections.append("")
    # H2
    sections.append("## GraphChange ID")
    sections.append("")
    sections.append(f"- **graph_change_id**: `{gc_dump['graph_change_id']}`")
    sections.append(f"- **candidate_hash**: `{candidate_hash}`")
    sections.append("")
    # H3
    sections.append("## 变更类型")
    sections.append("")
    sections.append(f"- **change_type**: `{gc_dump['change_type']}`")
    sections.append(f"- **review_status**: `{gc_dump['review_status']}`")
    sections.append(f"- **created_at**: {gc_dump['created_at']}")
    sections.append("")
    # H4
    sections.append("## 当前知识")
    sections.append("")
    sections.append("```json")
    sections.append(gc_dump.get("current_knowledge", "{}"))
    sections.append("```")
    sections.append("")
    # H5
    sections.append("## 新证据")
    sections.append("")
    sections.append("_（无证据）_")
    sections.append("")
    # H6
    sections.append("## 建议变更")
    sections.append("")
    sections.append(gc_dump.get("suggested_change", ""))
    sections.append("")
    # H7
    sections.append("## 影响范围")
    sections.append("")
    for item in gc_dump.get("impact_scope", []):
        sections.append(f"- {item}")
    sections.append("")
    # H8
    sections.append("## 冲突信息")
    sections.append("")
    sections.append("_（无冲突）_")
    sections.append("")
    # H9
    sections.append("## 验证节点")
    sections.append("")
    for item in gc_dump.get("verification_points", []):
        sections.append(f"- [ ] {item}")
    sections.append("")
    # H10: Review options
    sections.append("## 审核选项")
    sections.append("")
    for label in ["批准", "修改后批准", "暂缓", "拒绝"]:
        mark = "x" if label == decision else " "
        sections.append(f"- [{mark}] {label}")
    sections.append("")
    # H11: Reviewer
    sections.append("## Reviewer")
    sections.append("")
    sections.append("```yaml")
    sections.append("reviewer_type: human")
    sections.append(f"reviewer_id: \"{reviewer_id}\"")
    sections.append("display_name: \"\"")
    sections.append(f"reviewed_at: \"{reviewed_at}\"")
    sections.append("```")
    sections.append("")
    # H12: Review Notes
    sections.append("## Review Notes")
    sections.append("")
    if notes:
        sections.append(notes)
    else:
        sections.append("_（请在此填写审核意见）_")
    sections.append("")
    # H13: Approved Patch
    sections.append("## Approved Patch")
    sections.append("")
    if patch and decision == "修改后批准":
        sections.append("```json")
        sections.append(json.dumps(patch, ensure_ascii=False))
        sections.append("```")
    else:
        sections.append("_（仅\"修改后批准\"时填写 JSON Patch 数组）_")
    sections.append("")
    sections.append("---")
    sections.append("*本文件为审阅模板，请填写后通过 review-import 导入。*")

    return "\n".join(sections), candidate_hash


# ═══════════════════════════════════════════════════════════════
# Tests: review_renderer
# ═══════════════════════════════════════════════════════════════

class TestReviewRenderer:
    """review_export_markdown 渲染测试。"""

    def test_all_13_frozen_headings_present(self):
        """冻结 13 标题全部出现在输出中。"""
        gc = _make_graph_change_node()
        md = review_export_markdown(gc)
        for h in _FROZEN_REVIEW_HEADINGS:
            assert h in md, f"Missing heading: {h}"

    def test_headings_in_correct_order(self):
        """标题按冻结顺序出现。"""
        gc = _make_graph_change_node()
        md = review_export_markdown(gc)
        positions = [md.index(h) for h in _FROZEN_REVIEW_HEADINGS]
        assert positions == sorted(positions), "Headings not in correct order"

    def test_graph_change_id_in_output(self):
        """输出包含 graph_change_id。"""
        gc = _make_graph_change_node(change_id=VALID_UUID)
        md = review_export_markdown(gc)
        assert f"`{VALID_UUID}`" in md

    def test_candidate_hash_in_output(self):
        """输出包含 candidate_hash（64 hex，M4 authority）。"""
        gc = _make_graph_change_node()
        md = review_export_markdown(gc)
        candidate_hash = _candidate_hash(gc)
        assert candidate_hash in md
        assert len(candidate_hash) == 64

    def test_change_type_in_output(self):
        """输出包含 change_type。"""
        gc = _make_graph_change_node(change_type="add_node")
        md = review_export_markdown(gc)
        assert "`add_node`" in md

    def test_four_review_checkboxes_present(self):
        """4 个审核 checkbox 全部出现且未选中。"""
        gc = _make_graph_change_node()
        md = review_export_markdown(gc)
        assert "- [ ] 批准" in md
        assert "- [ ] 修改后批准" in md
        assert "- [ ] 暂缓" in md
        assert "- [ ] 拒绝" in md

    def test_reviewer_template_present(self):
        """Reviewer 模板字段存在。"""
        gc = _make_graph_change_node()
        md = review_export_markdown(gc)
        assert "reviewer_type: human" in md
        assert "reviewer_id:" in md
        assert "reviewed_at:" in md

    def test_approved_patch_template_present(self):
        """Approved Patch 占位文本。"""
        gc = _make_graph_change_node()
        md = review_export_markdown(gc)
        assert "## Approved Patch" in md

    def test_current_knowledge_fenced(self):
        """当前知识在 fenced json block 中。"""
        gc = _make_graph_change_node()
        md = review_export_markdown(gc)
        assert "## 当前知识" in md
        assert "```" in md

    def test_node_info_in_output(self):
        """节点信息出现在输出中。"""
        gc = _make_graph_change_node()
        md = review_export_markdown(gc)
        assert "company:test-corp" in md

    def test_edge_info_in_output(self):
        """边信息出现在输出中。"""
        gc = _make_graph_change_edge()
        md = review_export_markdown(gc)
        assert "COMPETES_WITH" in md

    def test_evidence_list_empty(self):
        """无证据记录时显示占位符。"""
        gc = _make_graph_change_node()
        md = review_export_markdown(gc)
        assert "_（无证据）_" in md

    def test_deterministic_output(self):
        """相同输入产生相同输出。"""
        gc = _make_graph_change_node()
        md1 = review_export_markdown(gc)
        md2 = review_export_markdown(gc)
        assert md1 == md2

    def test_different_gc_different_hash(self):
        """不同 candidate 产生不同 hash（M4 authority）。"""
        gc1 = _make_graph_change_node(change_id=VALID_UUID)
        gc2 = _make_graph_change_node(
            change_id=VALID_UUID3,
            suggested_change="不同的变更",
        )
        h1 = _candidate_hash(gc1)
        h2 = _candidate_hash(gc2)
        assert h1 != h2

    def test_verification_points_as_checkboxes(self):
        """验证节点渲染为 checkbox 列表。"""
        gc = _make_graph_change_node(
            verification_points=["验证 A", "验证 B"]
        )
        md = review_export_markdown(gc)
        assert "- [ ] 验证 A" in md
        assert "- [ ] 验证 B" in md

    def test_impact_scope_list(self):
        """影响范围渲染为列表。"""
        gc = _make_graph_change_node(impact_scope=["行业 A", "行业 B"])
        md = review_export_markdown(gc)
        assert "- 行业 A" in md
        assert "- 行业 B" in md


# ═══════════════════════════════════════════════════════════════
# Tests: review_parser
# ═══════════════════════════════════════════════════════════════

class TestReviewParser:
    """parse_review_markdown 解析测试。"""

    def test_parse_approved_decision(self):
        """解析\"批准\"决策。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.decision == "approved"
        assert parsed.graph_change_id == gc.graph_change_id

    def test_parse_approved_with_changes(self):
        """解析\"修改后批准\"决策 + patch。"""
        gc = _make_graph_change_node()
        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新描述"}]
        md, _ = _build_review_markdown(gc, decision="修改后批准", patch=patch)
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.decision == "approved_with_changes"
        assert len(parsed.review_patch) == 1
        assert parsed.review_patch[0]["op"] == "replace"

    def test_parse_deferred(self):
        """解析\"暂缓\"决策。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="暂缓")
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.decision == "deferred"

    def test_parse_rejected(self):
        """解析\"拒绝\"决策。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="拒绝")
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.decision == "rejected"

    def test_no_checkbox_is_error(self):
        """未选中任何 checkbox 是错误。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        # 替换所有 [x] 为 [ ]
        md = md.replace("[x]", "[ ]")
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("未选中" in e for e in parsed.errors)

    def test_multiple_checkboxes_is_error(self):
        """选中多项 checkbox 是错误。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        # 额外选中一项
        md = md.replace("- [ ] 暂缓", "- [x] 暂缓")
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("多项" in e for e in parsed.errors)

    def test_missing_heading_is_error(self):
        """缺失标题是错误。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        # 删除"## Reviewer" heading
        md = md.replace("## Reviewer", "## DELETED_HEADING")
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("缺失标题" in e for e in parsed.errors)

    def test_duplicate_heading_is_error(self):
        """重复标题是错误。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        md = md.replace("## Review Notes", "## Reviewer")
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid

    def test_invalid_graph_change_id(self):
        """无效 UUID 是错误。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        md = md.replace(VALID_UUID, "not-a-valid-uuid")
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("格式非法" in e for e in parsed.errors)

    def test_invalid_candidate_hash(self):
        """无效 candidate_hash（非 64 hex）是错误。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        # Need a valid hash first
        h = _candidate_hash(gc)
        md = md.replace(h, "deadbeef")
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("candidate_hash" in e for e in parsed.errors)

    def test_missing_reviewer_id_is_error(self):
        """缺失 reviewer_id 是错误。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准", reviewer_id="")
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("reviewer_id" in e for e in parsed.errors)

    def test_missing_reviewed_at_is_error(self):
        """缺失 reviewed_at 是错误。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准", reviewed_at="")
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("reviewed_at" in e for e in parsed.errors)

    def test_invalid_reviewed_at_format(self):
        """无效 ISO 8601 的 reviewed_at 是错误。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准", reviewed_at="yesterday")
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("ISO 8601" in e for e in parsed.errors)

    def test_fenced_block_content_not_parsed(self):
        """fenced block 内的 heading 不会被解析。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        # Put a fake heading inside fenced block
        md_fenced = md.replace(
            "```json",
            "```json\n# 这是一个假标题\n## GraphChange ID",
        )
        parsed = parse_review_markdown(md_fenced)
        assert parsed.is_valid  # 真实标题仍存在

    def test_unclosed_fence_is_error(self):
        """未闭合的 fenced block 被真实拒绝。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        # 移除 current_knowledge 的关闭 ```（保留 opening），制造未闭合 fence
        md_unclosed = md.replace(
            "```json\n" + gc.model_dump().get("current_knowledge", "") + "\n```",
            "```json\n" + gc.model_dump().get("current_knowledge", ""),
        )
        # 确认确实构造出未闭合状态
        assert md_unclosed.count("```") % 2 == 1
        parsed = parse_review_markdown(md_unclosed)
        assert not parsed.is_valid
        assert any("未闭合" in e for e in parsed.errors)

    def test_fenced_fake_checkboxes_ignored(self):
        """fenced block 内的 fake checkbox 不计入审核选项。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="暂缓")
        # 在审核选项 section 中插入 fenced block，内含两个 checked fake 选项
        md_fenced = md.replace(
            "- [ ] 批准\n- [ ] 修改后批准\n- [ ] 暂缓\n- [ ] 拒绝",
            "```json\n- [x] 批准\n- [x] 拒绝\n```\n"
            "- [ ] 批准\n- [ ] 修改后批准\n- [x] 暂缓\n- [ ] 拒绝",
        )
        parsed = parse_review_markdown(md_fenced)
        assert parsed.is_valid
        assert parsed.decision == "deferred"  # fence 内 fake checked 均不计

    def test_approved_natural_language_patch_rejected(self):
        """approved + natural-language patch → INVALID_REVIEW。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        # 将 Approved Patch 占位符替换为自然语言
        md = md.replace(
            "_（仅\"修改后批准\"时填写 JSON Patch 数组）_",
            "这个 patch 建议把名称改成某某公司",
        )
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("Approved Patch" in e for e in parsed.errors)

    def test_deferred_malformed_json_rejected(self):
        """deferred + malformed JSON → INVALID_REVIEW。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="暂缓")
        md = md.replace(
            "_（仅\"修改后批准\"时填写 JSON Patch 数组）_",
            '{"op": "replace", "path": "/suggested_change", "value": "x"',
        )
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("Approved Patch" in e for e in parsed.errors)

    def test_rejected_empty_json_object_rejected(self):
        """rejected + {} → INVALID_REVIEW。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="拒绝")
        md = md.replace(
            "_（仅\"修改后批准\"时填写 JSON Patch 数组）_",
            "{}",
        )
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("Approved Patch" in e for e in parsed.errors)

    def test_rejected_empty_json_array_rejected(self):
        """rejected + [] → INVALID_REVIEW。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="拒绝")
        md = md.replace(
            "_（仅\"修改后批准\"时填写 JSON Patch 数组）_",
            "[]",
        )
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("Approved Patch" in e for e in parsed.errors)

    def test_approved_fenced_arbitrary_content_rejected(self):
        """approved + fenced arbitrary content → INVALID_REVIEW。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        md = md.replace(
            "_（仅\"修改后批准\"时填写 JSON Patch 数组）_",
            "```text\nhello arbitrary content\n```",
        )
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("Approved Patch" in e for e in parsed.errors)

    def test_display_name_empty_normalized_to_none(self):
        """display_name 为空字符串 → None。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准", reviewer_id="r1")
        md = md.replace('display_name: ""', 'display_name: ""')
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.display_name is None

    def test_display_name_null_normalized_to_none(self):
        """display_name 为 null → None。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准", reviewer_id="r1")
        md = md.replace('display_name: ""', "display_name: null")
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.display_name is None

    def test_display_name_placeholder_normalized_to_none(self):
        """display_name 为 <OPTIONAL_OR_NULL> → None。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准", reviewer_id="r1")
        md = md.replace('display_name: ""', "display_name: <OPTIONAL_OR_NULL>")
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.display_name is None

    def test_display_name_real_value_kept(self):
        """display_name 为实际文本 → 原样保留。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准", reviewer_id="r1")
        md = md.replace('display_name: ""', 'display_name: "张三"')
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.display_name == "张三"

    def test_approved_without_patch_is_error(self):
        """修改后批准但未提供 patch 是错误。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="修改后批准", patch=None)
        parsed = parse_review_markdown(md)
        assert not parsed.is_valid
        assert any("Approved Patch" in e for e in parsed.errors)

    def test_review_notes_extracted(self):
        """Review Notes 内容被正确提取。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(
            gc, decision="批准", notes="同意添加该节点，证据充分。"
        )
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert "同意添加该节点" in parsed.review_notes

    def test_extract_yaml_reviewer_fields(self):
        """Reviewer YAML 字段正确提取。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(
            gc,
            decision="批准",
            reviewer_id="zhangsan",
            reviewed_at="2026-08-08T15:00:00+08:00",
        )
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.reviewer_id == "zhangsan"
        assert parsed.reviewed_at == "2026-08-08T15:00:00+08:00"

    def test_strip_fenced_blocks(self):
        """_strip_fenced_blocks 替换 fenced 内容为空白。"""
        text = "before\n```\n# heading\n```\nafter"
        result = _strip_fenced_blocks(text)
        assert "# heading" not in result
        assert "before" in result
        assert "after" in result

    def test_fenced_fake_headings_before_real_rejected(self):
        """fence 内假标题（出现在真实标题之前）不干扰 section 定位。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        # current_knowledge 的 JSON fence 内包含整行假标题
        md_fenced = md.replace(
            "```json\n" + gc.model_dump().get("current_knowledge", "") + "\n```",
            "```json\n## 审核选项\n## Reviewer\n```",
        )
        parsed = parse_review_markdown(md_fenced)
        assert parsed.is_valid
        assert parsed.decision == "approved"

    def test_yaml_inline_comment_stripped(self):
        """YAML 行尾注释被剥离，不影响 reviewer_id。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准", reviewer_id="alice")
        md = md.replace(
            'reviewer_id: "alice"',
            'reviewer_id: "alice"  # 这是行尾注释',
        )
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.reviewer_id == "alice"

    def test_yaml_unquoted_value_with_comment(self):
        """无引号 YAML 值 + 行尾注释：值提取正确。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        md = md.replace(
            'reviewer_id: "reviewer-001"',
            "reviewer_id: reviewer-001  # comment",
        )
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.reviewer_id == "reviewer-001"

    def test_approved_with_changes_patch_json_array(self):
        """修改后批准的 patch 是合法 JSON 数组。"""
        gc = _make_graph_change_node()
        patch = [
            {"op": "replace", "path": "/suggested_change", "value": "new desc"},
            {"op": "add", "path": "/impact_scope/-", "value": "new_industry"},
        ]
        md, _ = _build_review_markdown(gc, decision="修改后批准", patch=patch)
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert len(parsed.review_patch) == 2

    def test_approved_decision_no_patch_ok(self):
        """批准决策不提供 patch 是合法的。"""
        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")
        parsed = parse_review_markdown(md)
        assert parsed.is_valid
        assert parsed.review_patch == []


# ═══════════════════════════════════════════════════════════════
# Tests: JSON Patch applier
# ═══════════════════════════════════════════════════════════════

class TestJSONPatchApplier:
    """apply_json_patch 测试。"""

    def test_replace_suggested_change(self):
        """替换 suggested_change 字段。"""
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        patch = [{"op": "replace", "path": "/suggested_change", "value": "新的建议"}]
        result = apply_json_patch(gc_dict, patch)
        assert result["suggested_change"] == "新的建议"

    def test_add_to_impact_scope(self):
        """添加影响范围项。"""
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        patch = [{"op": "add", "path": "/impact_scope/-", "value": "new_industry"}]
        result = apply_json_patch(gc_dict, patch)
        assert "new_industry" in result["impact_scope"]

    def test_remove_from_conflicts(self):
        """移除冲突项。"""
        gc = _make_graph_change_node(conflicts=["conflict_1", "conflict_2"])
        gc_dict = gc.model_dump()
        patch = [{"op": "remove", "path": "/conflicts/0"}]
        result = apply_json_patch(gc_dict, patch)
        assert "conflict_1" not in result["conflicts"]

    def test_replace_node_name(self):
        """替换节点名称（白名单路径）。"""
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        patch = [{"op": "replace", "path": "/node/name", "value": "新名称"}]
        result = apply_json_patch(gc_dict, patch)
        assert result["node"]["name"] == "新名称"

    def test_replace_edge_confidence(self):
        """替换边置信度（白名单路径）。"""
        gc = _make_graph_change_edge()
        gc_dict = gc.model_dump()
        patch = [{"op": "replace", "path": "/edge/confidence", "value": 0.95}]
        result = apply_json_patch(gc_dict, patch)
        assert result["edge"]["confidence"] == 0.95

    def test_block_system_field_graph_change_id(self):
        """阻止修改 graph_change_id。"""
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        patch = [{"op": "replace", "path": "/graph_change_id", "value": "new-id"}]
        with pytest.raises(ValueError, match="禁止修改系统字段"):
            apply_json_patch(gc_dict, patch)

    def test_block_system_field_change_type(self):
        """阻止修改 change_type。"""
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        patch = [{"op": "replace", "path": "/change_type", "value": "modify_attribute"}]
        with pytest.raises(ValueError, match="禁止修改系统字段"):
            apply_json_patch(gc_dict, patch)

    def test_block_system_field_review_status(self):
        """阻止修改 review_status。"""
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        patch = [{"op": "replace", "path": "/review_status", "value": "approved"}]
        with pytest.raises(ValueError, match="禁止修改系统字段"):
            apply_json_patch(gc_dict, patch)

    def test_block_non_whitelisted_path(self):
        """阻止不在白名单的路径。"""
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        patch = [{"op": "replace", "path": "/unknown_field", "value": "x"}]
        with pytest.raises(ValueError, match="路径不在白名单"):
            apply_json_patch(gc_dict, patch)

    def test_block_node_id(self):
        """阻止修改 node_id。"""
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        patch = [{"op": "replace", "path": "/node/node_id", "value": "new-id"}]
        with pytest.raises(ValueError, match="禁止修改系统字段"):
            apply_json_patch(gc_dict, patch)

    def test_block_edge_relation(self):
        """阻止修改 relation。"""
        gc = _make_graph_change_edge()
        gc_dict = gc.model_dump()
        patch = [{"op": "replace", "path": "/edge/relation", "value": "SUPPLIES"}]
        with pytest.raises(ValueError, match="禁止修改系统字段"):
            apply_json_patch(gc_dict, patch)

    def test_original_unchanged(self):
        """原始对象不被修改（深拷贝）。"""
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        original = copy.deepcopy(gc_dict)
        patch = [{"op": "replace", "path": "/suggested_change", "value": "新的"}]
        _ = apply_json_patch(gc_dict, patch)
        assert gc_dict["suggested_change"] == original["suggested_change"]

    def test_multiple_ops_in_order(self):
        """多个操作按顺序执行。"""
        gc = _make_graph_change_node(impact_scope=["a", "b"])
        gc_dict = gc.model_dump()
        patch = [
            {"op": "remove", "path": "/impact_scope/0"},
            {"op": "add", "path": "/impact_scope/-", "value": "c"},
        ]
        result = apply_json_patch(gc_dict, patch)
        assert result["impact_scope"] == ["b", "c"]

    def test_unsupported_op_rejected(self):
        """不支持的操作被拒绝。"""
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        patch = [{"op": "copy", "path": "/suggested_change", "from": "/impact_scope"}]
        with pytest.raises(ValueError, match="不支持的操作"):
            apply_json_patch(gc_dict, patch)

    def test_whitelist_covers_all_schema_paths(self):
        """白名单覆盖 Schema 中定义的所有允许路径。"""
        schema_paths = {
            "/suggested_change", "/impact_scope", "/conflicts", "/verification_points",
            "/new_evidence_ids",
            "/node/name", "/node/aliases", "/node/description", "/node/status",
            "/node/valid_from", "/node/valid_to", "/node/evidence_ids",
            "/edge/attributes", "/edge/valid_from", "/edge/valid_to",
            "/edge/confidence", "/edge/evidence_ids",
        }
        assert _ALLOWED_PATCH_PATHS == schema_paths

    def test_replace_node_evidence_ids(self):
        """替换节点 evidence_ids。"""
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        patch = [{"op": "replace", "path": "/node/evidence_ids", "value": ["ev:002"]}]
        result = apply_json_patch(gc_dict, patch)
        assert result["node"]["evidence_ids"] == ["ev:002"]


# ═══════════════════════════════════════════════════════════════
# Tests: Deterministic IDs (review-intent 绑定)
# ═══════════════════════════════════════════════════════════════

def _review_intent(
    gc,
    decision="approved",
    reviewer_id="reviewer-001",
    display_name=None,
    reviewed_at=T1,
    notes="",
    patch=None,
):
    """构造规范 review intent（reviewer 使用完整 deterministic representation）。"""
    return {
        "graph_change_id": gc.graph_change_id,
        "decision": decision,
        "reviewer": {
            "reviewer_type": "human",
            "reviewer_id": reviewer_id,
            "display_name": display_name,
        },
        "reviewed_at": reviewed_at,
        "candidate_hash": _candidate_hash(gc),
        "review_patch": patch or [],
        "notes": notes,
    }


class TestDeterministicIDs:
    """UUID5 确定性 ID 测试（review-intent 绑定）。"""

    def test_review_id_deterministic(self):
        """相同 exact review 产生相同 review_id。"""
        gc1 = _make_graph_change_node()
        gc2 = _make_graph_change_node()  # 相同参数
        id1 = _make_review_id(_review_intent(gc1))
        id2 = _make_review_id(_review_intent(gc2))
        assert id1 == id2

    def test_review_id_different_candidates(self):
        """不同 candidate（不同 graph_change_id）产生不同 review_id。"""
        gc1 = _make_graph_change_node(change_id=VALID_UUID)
        gc2 = _make_graph_change_node(
            change_id=VALID_UUID3, suggested_change="不同"
        )
        id1 = _make_review_id(_review_intent(gc1))
        id2 = _make_review_id(_review_intent(gc2))
        assert id1 != id2

    def test_review_id_different_decision(self):
        """same candidate + different decision → different review_id。"""
        gc = _make_graph_change_node()
        id1 = _make_review_id(_review_intent(gc, decision="approved"))
        id2 = _make_review_id(_review_intent(gc, decision="rejected"))
        assert id1 != id2

    def test_review_id_different_reviewer(self):
        """same candidate + different reviewer → different review_id。"""
        gc = _make_graph_change_node()
        id1 = _make_review_id(_review_intent(gc, reviewer_id="reviewer-A"))
        id2 = _make_review_id(_review_intent(gc, reviewer_id="reviewer-B"))
        assert id1 != id2

    def test_review_id_different_display_name(self):
        """same candidate + different reviewer display_name → different review_id。"""
        gc = _make_graph_change_node()
        id1 = _make_review_id(_review_intent(gc, display_name="张三"))
        id2 = _make_review_id(_review_intent(gc, display_name="李四"))
        assert id1 != id2

    def test_review_id_different_reviewed_at(self):
        """same candidate + different reviewed_at → different review_id。"""
        gc = _make_graph_change_node()
        id1 = _make_review_id(_review_intent(gc, reviewed_at=T1))
        id2 = _make_review_id(_review_intent(gc, reviewed_at="2026-08-09T10:00:00+08:00"))
        assert id1 != id2

    def test_review_id_different_notes(self):
        """same candidate + different notes → different review_id。"""
        gc = _make_graph_change_node()
        id1 = _make_review_id(_review_intent(gc, notes="同意"))
        id2 = _make_review_id(_review_intent(gc, notes="有疑问"))
        assert id1 != id2

    def test_review_id_different_patch(self):
        """same candidate + different patch → different review_id。"""
        gc = _make_graph_change_node()
        p1 = [{"op": "replace", "path": "/suggested_change", "value": "A"}]
        p2 = [{"op": "replace", "path": "/suggested_change", "value": "B"}]
        id1 = _make_review_id(_review_intent(
            gc, decision="approved_with_changes", patch=p1))
        id2 = _make_review_id(_review_intent(
            gc, decision="approved_with_changes", patch=p2))
        assert id1 != id2

    def test_review_id_protocol_exact(self):
        """review_id 协议：UUID5(DNS, "graph-review:" + sha256(canonical intent))。"""
        gc = _make_graph_change_node()
        intent = _review_intent(gc)
        canonical = json.dumps(intent, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        intent_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, "graph-review:" + intent_sha))
        assert _make_review_id(intent) == expected
        assert compute_review_id(intent) == expected

    def test_replacement_gc_id_deterministic(self):
        """相同 review_id 产生相同 replacement ID。"""
        rid = "11111111-1111-1111-1111-111111111111"
        id1 = _make_replacement_gc_id(rid)
        id2 = _make_replacement_gc_id(rid)
        assert id1 == id2

    def test_replacement_gc_id_different_reviews(self):
        """不同 review_id 产生不同 replacement ID。"""
        id1 = _make_replacement_gc_id(
            "11111111-1111-1111-1111-111111111111"
        )
        id2 = _make_replacement_gc_id(
            "22222222-2222-2222-2222-222222222222"
        )
        assert id1 != id2

    def test_replacement_id_protocol_exact(self):
        """replacement 协议：UUID5(DNS, "graph-review-result:" + review_id)。"""
        rid = "11111111-1111-1111-1111-111111111111"
        expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, "graph-review-result:" + rid))
        assert _make_replacement_gc_id(rid) == expected

    def test_review_id_is_uuid_format(self):
        """review_id 是合法 UUID 格式。"""
        gc = _make_graph_change_node()
        rid = _make_review_id(_review_intent(gc))
        assert len(rid) == 36
        assert rid.count("-") == 4

    def test_replacement_id_is_uuid_format(self):
        """replacement ID 是合法 UUID 格式。"""
        rid = _make_review_id(_review_intent(_make_graph_change_node()))
        rep_id = _make_replacement_gc_id(rid)
        assert len(rep_id) == 36
        assert rep_id.count("-") == 4


# ═══════════════════════════════════════════════════════════════
# Tests: ReviewWorkflow (export/import integration)
# ═══════════════════════════════════════════════════════════════

class TestReviewWorkflowExport:
    """review_export 测试。"""

    def test_export_ok(self, tmp_path):
        """正常导出 candidate。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()

        # Set up minimal DB state
        _ensure_graph_tables(db)

        # Insert evidence
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
        _insert_evidence(db, ev)

        # Insert entity
        entity = Entity(
            entity_id="company:test-corp",
            entity_type="company",
            canonical_name="测试公司",
        )
        _insert_entity(db, entity)

        # Also insert source/target entities for edge tests
        entity2 = Entity(
            entity_id="company:src",
            entity_type="company",
            canonical_name="源公司",
        )
        entity3 = Entity(
            entity_id="company:tgt",
            entity_type="company",
            canonical_name="目标公司",
        )
        _insert_entity(db, entity2)
        _insert_entity(db, entity3)

        # Insert raw_item for evidence chain
        conn = db._conn
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
        conn.commit()

        gc = _make_graph_change_node()
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)

        # Insert candidate
        candidate_repo.append_candidate(gc)

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        result = workflow.review_export(gc.graph_change_id)

        assert result.status == "ok"
        assert result.graph_change_id == gc.graph_change_id
        assert len(result.candidate_hash) == 64
        assert "# 图谱变更候选" in result.markdown
        assert "## 审核选项" in result.markdown

        db.close()

    def test_export_not_found(self, tmp_path):
        """导出不存在的 candidate 返回错误。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        result = workflow.review_export("nonexistent-uuid-00000000000000")

        assert result.status == "error"
        assert "not found" in result.error.lower()

        db.close()

    def test_export_not_candidate_status(self, tmp_path):
        """导出 review_status 非 candidate 返回错误。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        # Insert evidence
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
        _insert_evidence(db, ev)

        entity = Entity(
            entity_id="company:test-corp",
            entity_type="company",
            canonical_name="测试公司",
        )
        _insert_entity(db, entity)

        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)

        # Insert an already-approved candidate (bypass the candidate-only gate)
        gc_dict = _make_graph_change_node().model_dump()
        gc_dict["review_status"] = "approved"
        gc_dict["reviewed_at"] = T1
        _insert_candidate_raw(db, gc_dict)

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        result = workflow.review_export(gc_dict["graph_change_id"])

        assert result.status == "error"
        assert "candidate" in result.error.lower()

        db.close()


class TestReviewWorkflowImport:
    """review_import 测试。"""

    def test_import_approved(self, tmp_path):
        """导入批准决策。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)
        candidate_repo.append_candidate(gc)

        md, _ = _build_review_markdown(gc, decision="批准")

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        result = workflow.review_import(md)

        assert result.status == "ok"
        assert result.decision == "approved"
        assert result.resulting_graph_change_id is None

        # Verify GraphReview persisted
        saved_review = graph_repo.get_review(result.review_id)
        assert saved_review is not None
        assert saved_review["decision"] == "approved"

        db.close()

    def test_import_approved_with_changes(self, tmp_path):
        """导入修改后批准决策（有 patch 和 replacement）。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)
        candidate_repo.append_candidate(gc)

        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新后的描述"}]
        md, _ = _build_review_markdown(gc, decision="修改后批准", patch=patch)

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        result = workflow.review_import(md)

        assert result.status == "ok"
        assert result.decision == "approved_with_changes"
        assert result.resulting_graph_change_id is not None

        # Verify GraphReview persisted
        saved_review = graph_repo.get_review(result.review_id)
        assert saved_review is not None
        assert saved_review["decision"] == "approved_with_changes"

        # Verify replacement GraphChange persisted
        repl = candidate_repo.get_candidate(result.resulting_graph_change_id)
        assert repl is not None
        assert repl["suggested_change"] == "更新后的描述"
        assert repl["review_status"] == "candidate"

        db.close()

    def test_import_deferred(self, tmp_path):
        """导入暂缓决策。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)
        candidate_repo.append_candidate(gc)

        md, _ = _build_review_markdown(gc, decision="暂缓")

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        result = workflow.review_import(md)

        assert result.status == "ok"
        assert result.decision == "deferred"
        assert result.resulting_graph_change_id is None

        saved_review = graph_repo.get_review(result.review_id)
        assert saved_review is not None
        assert saved_review["decision"] == "deferred"

        db.close()

    def test_import_rejected(self, tmp_path):
        """导入拒绝决策。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)
        candidate_repo.append_candidate(gc)

        md, _ = _build_review_markdown(gc, decision="拒绝")

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        result = workflow.review_import(md)

        assert result.status == "ok"
        assert result.decision == "rejected"

        saved_review = graph_repo.get_review(result.review_id)
        assert saved_review is not None
        assert saved_review["decision"] == "rejected"

        db.close()

    def test_idempotent_import(self, tmp_path):
        """重复导入相同 review 文件是幂等的。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)
        candidate_repo.append_candidate(gc)

        md, _ = _build_review_markdown(gc, decision="批准")

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)

        # First import
        result1 = workflow.review_import(md)
        assert result1.status == "ok"

        # Second import (same input)
        result2 = workflow.review_import(md)
        assert result2.status == "idempotent_noop"
        assert result2.review_id == result1.review_id

        db.close()

    def test_dry_run_no_write(self, tmp_path):
        """dry-run 不产生任何 DB 写入。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)
        candidate_repo.append_candidate(gc)

        md, _ = _build_review_markdown(gc, decision="批准")

        # Count before
        review_count_before = _count_table(db, "graph_reviews")

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        result = workflow.review_import(md, dry_run=True)

        assert result.status == "dry_run"
        assert result.dry_run is True

        # Verify zero writes
        review_count_after = _count_table(db, "graph_reviews")
        assert review_count_after == review_count_before

        db.close()

    def test_hash_mismatch_blocked(self, tmp_path):
        """candidate hash 不匹配被阻止。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)
        candidate_repo.append_candidate(gc)

        # Generate markdown with WRONG hash
        md, correct_hash = _build_review_markdown(gc, decision="批准")
        wrong_hash = "a" * 64
        md = md.replace(correct_hash, wrong_hash)

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        result = workflow.review_import(md)

        assert result.status == "error"
        assert any("hash" in e.lower() for e in result.errors)

        db.close()

    def test_original_candidate_unchanged_after_approved(self, tmp_path):
        """批准后原始 candidate 不被修改。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)
        candidate_repo.append_candidate(gc)

        original = candidate_repo.get_candidate(gc.graph_change_id)

        md, _ = _build_review_markdown(gc, decision="批准")
        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        workflow.review_import(md)

        after = candidate_repo.get_candidate(gc.graph_change_id)
        assert after == original  # 原始不变

        db.close()

    def test_replacement_provenance(self, tmp_path):
        """Replacement GraphChange 的溯源链正确。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)
        candidate_repo.append_candidate(gc)

        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        md, _ = _build_review_markdown(gc, decision="修改后批准", patch=patch)

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        result = workflow.review_import(md)

        assert result.status == "ok"

        # Verify replacement exists
        repl = candidate_repo.get_candidate(result.resulting_graph_change_id)
        assert repl is not None
        assert repl["review_status"] == "candidate"  # M5-R1 spec
        assert repl["reviewed_at"] is None  # M5-R1: replacement reviewed_at is null

        # Verify GraphReview links to replacement
        saved_review = graph_repo.get_review(result.review_id)
        assert saved_review["resulting_graph_change_id"] == result.resulting_graph_change_id

        db.close()

    def test_candidate_not_found_error(self, tmp_path):
        """导入指向不存在 candidate 返回错误。"""
        from research_os.storage import Database
        from research_os.knowledge.knowledge_validator import KnowledgeValidator

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _ensure_graph_tables(db)

        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)

        gc = _make_graph_change_node()
        md, _ = _build_review_markdown(gc, decision="批准")

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
        result = workflow.review_import(md)

        assert result.status == "error"
        assert any("not found" in e.lower() for e in result.errors)

        db.close()


# ═══════════════════════════════════════════════════════════════
# Tests: ImportResult eligibility + replay integrity
# ═══════════════════════════════════════════════════════════════

def _setup_import_components(db):
    """构造 import 所需的 repos/validator/workflow。"""
    from research_os.knowledge.candidate_repository import (
        GraphChangeCandidateRepository,
    )
    from research_os.knowledge.repository import GraphRepository

    candidate_repo = GraphChangeCandidateRepository(db)
    graph_repo = GraphRepository(db)
    validator = KnowledgeValidator(db, graph_repo)
    workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
    return candidate_repo, graph_repo, validator, workflow


class TestImportEligibilityAndReplay:
    """ImportResult 真实 eligibility + approved_with_changes replay 完整性。"""

    def test_import_ok_reports_real_eligibility(self, tmp_path):
        """正常 approved：review_eligible=true, apply_eligible=true。"""
        from research_os.storage import Database

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        candidate_repo, graph_repo, validator, workflow = _setup_import_components(db)
        candidate_repo.append_candidate(gc)

        md, _ = _build_review_markdown(gc, decision="批准")
        result = workflow.review_import(md)

        assert result.status == "ok"
        assert result.candidate_hash == _candidate_hash(gc)
        assert result.review_eligible is True
        assert result.apply_eligible is True

        db.close()

    def test_dry_run_reports_real_eligibility(self, tmp_path):
        """dry-run：review_eligible=true, apply_eligible=true。"""
        from research_os.storage import Database

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        candidate_repo, graph_repo, validator, workflow = _setup_import_components(db)
        candidate_repo.append_candidate(gc)

        md, _ = _build_review_markdown(gc, decision="批准")
        result = workflow.review_import(md, dry_run=True)

        assert result.status == "dry_run"
        assert result.candidate_hash == _candidate_hash(gc)
        assert result.review_eligible is True
        assert result.apply_eligible is True

        db.close()

    def test_idempotent_reports_real_eligibility(self, tmp_path):
        """幂等回放：review_eligible=true, apply_eligible=true。"""
        from research_os.storage import Database

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        candidate_repo, graph_repo, validator, workflow = _setup_import_components(db)
        candidate_repo.append_candidate(gc)

        md, _ = _build_review_markdown(gc, decision="批准")
        r1 = workflow.review_import(md)
        assert r1.status == "ok"
        r2 = workflow.review_import(md)

        assert r2.status == "idempotent_noop"
        assert r2.review_id == r1.review_id
        assert r2.candidate_hash == _candidate_hash(gc)
        assert r2.review_eligible is True
        assert r2.apply_eligible is True

        db.close()

    def test_approved_conflict_review_persists_apply_ineligible(self, tmp_path):
        """approved + conflict：review 持久化，apply_eligible=false。"""
        from research_os.storage import Database

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node(conflicts=["冲突数据源：源A vs 源B"])
        candidate_repo, graph_repo, validator, workflow = _setup_import_components(db)
        candidate_repo.append_candidate(gc)

        md, _ = _build_review_markdown(gc, decision="批准")
        result = workflow.review_import(md)

        assert result.status == "ok"
        assert result.review_eligible is True
        assert result.apply_eligible is False

        # 合法人工审核历史保留
        saved = graph_repo.get_review(result.review_id)
        assert saved is not None
        assert saved["decision"] == "approved"

        db.close()

    def test_deferred_apply_ineligible_review_eligible(self, tmp_path):
        """deferred：review 持久化，review_eligible=true, apply_eligible=false。"""
        from research_os.storage import Database

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        candidate_repo, graph_repo, validator, workflow = _setup_import_components(db)
        candidate_repo.append_candidate(gc)

        md, _ = _build_review_markdown(gc, decision="暂缓")
        result = workflow.review_import(md)

        assert result.status == "ok"
        assert result.review_eligible is True
        assert result.apply_eligible is False

        db.close()

    def test_same_candidate_two_reviews_coexist(self, tmp_path):
        """same candidate 两个不同审核 → 两条 audit records。"""
        from research_os.storage import Database

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        candidate_repo, graph_repo, validator, workflow = _setup_import_components(db)
        candidate_repo.append_candidate(gc)

        md_a, _ = _build_review_markdown(gc, decision="批准", reviewer_id="reviewer-A")
        ra = workflow.review_import(md_a)
        assert ra.status == "ok"

        md_b, _ = _build_review_markdown(gc, decision="拒绝", reviewer_id="reviewer-B")
        rb = workflow.review_import(md_b)
        assert rb.status == "ok"

        assert ra.review_id != rb.review_id

        rows = db._conn.execute(
            "SELECT review_id, decision FROM graph_reviews WHERE graph_change_id = ?",
            (gc.graph_change_id,),
        ).fetchall()
        assert len(rows) == 2
        assert {r["decision"] for r in rows} == {"approved", "rejected"}

        db.close()

    def test_exact_review_replay_idempotent(self, tmp_path):
        """exact review replay → idempotent，不产生重复记录。"""
        from research_os.storage import Database

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        candidate_repo, graph_repo, validator, workflow = _setup_import_components(db)
        candidate_repo.append_candidate(gc)

        md, _ = _build_review_markdown(gc, decision="批准")
        r1 = workflow.review_import(md)
        assert r1.status == "ok"
        r2 = workflow.review_import(md)
        assert r2.status == "idempotent_noop"

        count = _count_table(db, "graph_reviews")
        assert count == 1

        db.close()

    def test_replay_missing_replacement_rejected(self, tmp_path):
        """approved_with_changes replay + replacement 缺失 → REPLACEMENT_MISSING。"""
        from research_os.storage import Database

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        candidate_repo, graph_repo, validator, workflow = _setup_import_components(db)
        candidate_repo.append_candidate(gc)

        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        md, _ = _build_review_markdown(gc, decision="修改后批准", patch=patch)

        r1 = workflow.review_import(md)
        assert r1.status == "ok"

        # 攻击：删除 replacement
        db._conn.execute(
            "DELETE FROM graph_changes WHERE graph_change_id = ?",
            (r1.resulting_graph_change_id,),
        )
        db._conn.commit()

        r2 = workflow.review_import(md)
        assert r2.status == "error"
        assert any("REPLACEMENT_MISSING" in e for e in r2.errors)

        db.close()

    def test_replay_conflicting_replacement_rejected(self, tmp_path):
        """approved_with_changes replay + replacement payload 不同 → IMMUTABLE_CANDIDATE_CONFLICT。"""
        from research_os.storage import Database

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _setup_minimal_db_for_import(db)

        gc = _make_graph_change_node()
        candidate_repo, graph_repo, validator, workflow = _setup_import_components(db)
        candidate_repo.append_candidate(gc)

        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        md, _ = _build_review_markdown(gc, decision="修改后批准", patch=patch)

        r1 = workflow.review_import(md)
        assert r1.status == "ok"

        # 攻击：篡改 replacement payload
        repl = candidate_repo.get_candidate(r1.resulting_graph_change_id)
        assert repl is not None
        repl["suggested_change"] = "被篡改的内容"
        tampered = json.dumps(repl, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
        db._conn.execute(
            "UPDATE graph_changes SET payload = ? WHERE graph_change_id = ?",
            (tampered, r1.resulting_graph_change_id),
        )
        db._conn.commit()

        r2 = workflow.review_import(md)
        assert r2.status == "error"
        assert any("IMMUTABLE_CANDIDATE_CONFLICT" in e for e in r2.errors)

        db.close()


# ═══════════════════════════════════════════════════════════════
# Tests: review-export artifact file
# ═══════════════════════════════════════════════════════════════

class TestReviewExportFile:
    """review-export 真实写入 knowledge/candidates/{id}.md。"""

    def _make_workflow(self, tmp_path, knowledge_dir=None):
        from research_os.storage import Database
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        _setup_minimal_db_for_import(db)
        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)
        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator,
                                  knowledge_dir=knowledge_dir)
        return db, candidate_repo, workflow, db_path

    def test_export_creates_file(self, tmp_path):
        """review-export 创建 artifact 文件。"""
        knowledge_dir = tmp_path / "knowledge"
        db, candidate_repo, workflow, _ = self._make_workflow(
            tmp_path, knowledge_dir=knowledge_dir
        )
        gc = _make_graph_change_node()
        candidate_repo.append_candidate(gc)

        result = workflow.review_export(gc.graph_change_id)

        assert result.status == "ok"
        assert result.candidate_hash == _candidate_hash(gc)
        path = Path(result.markdown_path)
        assert path.exists()
        assert path.name == f"{gc.graph_change_id}.md"
        assert path.read_text(encoding="utf-8") == result.markdown
        assert "- **candidate_hash**:" in result.markdown

        db.close()

    def test_export_idempotent(self, tmp_path):
        """相同 export 幂等（idempotent_noop，文件 bytes 不变）。"""
        knowledge_dir = tmp_path / "knowledge"
        db, candidate_repo, workflow, _ = self._make_workflow(
            tmp_path, knowledge_dir=knowledge_dir
        )
        gc = _make_graph_change_node()
        candidate_repo.append_candidate(gc)

        r1 = workflow.review_export(gc.graph_change_id)
        assert r1.status == "ok"
        path = Path(r1.markdown_path)
        before = path.read_bytes()

        r2 = workflow.review_export(gc.graph_change_id)
        assert r2.status == "idempotent_noop"
        assert r2.markdown_path == r1.markdown_path
        assert path.read_bytes() == before

        db.close()

    def test_export_dry_run_zero_file(self, tmp_path):
        """dry-run：0 file writes / 0 mkdir，target 路径正确。"""
        knowledge_dir = tmp_path / "knowledge"
        db, candidate_repo, workflow, _ = self._make_workflow(
            tmp_path, knowledge_dir=knowledge_dir
        )
        gc = _make_graph_change_node()
        candidate_repo.append_candidate(gc)

        result = workflow.review_export(gc.graph_change_id, dry_run=True)

        assert result.status == "dry_run"
        assert result.candidate_hash == _candidate_hash(gc)
        target = Path(result.markdown_path)
        assert target == knowledge_dir / "candidates" / f"{gc.graph_change_id}.md"
        assert not target.exists()
        assert not (knowledge_dir / "candidates").exists()

        db.close()

    def test_export_m3_template_upgrade(self, tmp_path):
        """已存在 M3 untouched candidate template → deterministic upgrade。"""
        knowledge_dir = tmp_path / "knowledge"
        db, candidate_repo, workflow, _ = self._make_workflow(
            tmp_path, knowledge_dir=knowledge_dir
        )
        gc = _make_graph_change_node()
        candidate_repo.append_candidate(gc)

        target = knowledge_dir / "candidates" / f"{gc.graph_change_id}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        # M3 candidate template：无 candidate_hash、Reviewer=_（待审核）_
        m3_content = (
            "# 图谱变更候选\n\n"
            "## GraphChange ID\n\n"
            f"- **graph_change_id**: `{gc.graph_change_id}`\n\n"
            "## 变更类型\n\n"
            f"- **change_type**: `{gc.change_type}`\n\n"
            "## 当前知识\n\n_（无当前知识——此为新节点/边）_\n\n"
            "## 新证据\n\n_（无证据上下文）_\n\n"
            "## 建议变更\n\n"
            f"{gc.suggested_change}\n\n"
            "## 影响范围\n\n- industry_a\n\n"
            "## 冲突信息\n\n_（无冲突）_\n\n"
            "## 验证节点\n\n- [ ] 验证公司注册信息\n\n"
            "## 审核选项\n\n- [ ] 批准\n- [ ] 修改后批准\n- [ ] 暂缓\n- [ ] 拒绝\n\n"
            "## Reviewer\n\n_（待审核）_\n\n"
            "## Review Notes\n\n_（待填写）_\n\n"
            "## Approved Patch\n\n_（审核通过后在此填写 JSON Patch）_\n\n"
            "---\n*渲染时间: --*"
        )
        target.write_text(m3_content, encoding="utf-8")

        result = workflow.review_export(gc.graph_change_id)

        assert result.status == "ok"
        upgraded = target.read_text(encoding="utf-8")
        assert upgraded == result.markdown
        assert "- **candidate_hash**:" in upgraded  # 升级为 M5 review artifact

        db.close()

    def test_export_human_edit_conflict(self, tmp_path):
        """已有人类 edit → REVIEW_EXPORT_FILE_CONFLICT，不得覆盖。"""
        knowledge_dir = tmp_path / "knowledge"
        db, candidate_repo, workflow, _ = self._make_workflow(
            tmp_path, knowledge_dir=knowledge_dir
        )
        gc = _make_graph_change_node()
        candidate_repo.append_candidate(gc)

        target = knowledge_dir / "candidates" / f"{gc.graph_change_id}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        # 人类已勾选审核选项
        human_content = (
            "# 图谱变更候选\n\n"
            "## GraphChange ID\n\n"
            f"- **graph_change_id**: `{gc.graph_change_id}`\n\n"
            "## 审核选项\n\n"
            "- [x] 批准\n- [ ] 修改后批准\n- [ ] 暂缓\n- [ ] 拒绝\n\n"
            "## Reviewer\n\n```yaml\nreviewer_type: human\n"
            'reviewer_id: "reviewer-001"\n'
            'reviewed_at: "2026-08-08T15:00:00+08:00"\n```\n\n'
            "## Approved Patch\n\n_（仅\"修改后批准\"时填写 JSON Patch 数组）_\n"
        )
        target.write_text(human_content, encoding="utf-8")

        result = workflow.review_export(gc.graph_change_id)

        assert result.status == "REVIEW_EXPORT_FILE_CONFLICT"
        assert target.read_text(encoding="utf-8") == human_content  # 未被覆盖

        db.close()

    def test_export_human_edit_notes_only_conflict(self, tmp_path):
        """人工仅填写 Review Notes（未勾 checkbox）→ 同样不得覆盖。"""
        knowledge_dir = tmp_path / "knowledge"
        db, candidate_repo, workflow, _ = self._make_workflow(
            tmp_path, knowledge_dir=knowledge_dir
        )
        gc = _make_graph_change_node()
        candidate_repo.append_candidate(gc)

        target = knowledge_dir / "candidates" / f"{gc.graph_change_id}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        notes_content = (
            "# 图谱变更候选\n\n"
            "## GraphChange ID\n\n"
            f"- **graph_change_id**: `{gc.graph_change_id}`\n\n"
            "## 审核选项\n\n"
            "- [ ] 批准\n- [ ] 修改后批准\n- [ ] 暂缓\n- [ ] 拒绝\n\n"
            "## Review Notes\n\n"
            "我认真核对了证据，认为该节点描述需要再补充。\n\n"
            "## Approved Patch\n\n_（仅\"修改后批准\"时填写 JSON Patch 数组）_\n"
        )
        target.write_text(notes_content, encoding="utf-8")

        result = workflow.review_export(gc.graph_change_id)

        assert result.status == "REVIEW_EXPORT_FILE_CONFLICT"
        assert target.read_text(encoding="utf-8") == notes_content  # 未被覆盖

        db.close()

    def test_export_evidence_missing_fails(self, tmp_path):
        """Evidence missing → review-export ERROR（fail-closed）。"""
        knowledge_dir = tmp_path / "knowledge"
        db, candidate_repo, workflow, _ = self._make_workflow(
            tmp_path, knowledge_dir=knowledge_dir
        )
        # candidate 引用不存在的 evidence
        gc = _make_graph_change_node()
        gc_dict = gc.model_dump()
        gc_dict["new_evidence_ids"] = ["missing-evidence-id-00000000"]
        gc_dict["node"]["evidence_ids"] = ["missing-evidence-id-00000000"]
        candidate_repo.append_candidate(GraphChange(**gc_dict))

        result = workflow.review_export(gc.graph_change_id)

        assert result.status == "error"
        assert "Evidence missing" in result.error

        db.close()

    def test_export_evidence_invalid_json_fails(self, tmp_path):
        """Evidence invalid JSON → review-export ERROR（fail-closed）。"""
        knowledge_dir = tmp_path / "knowledge"
        db, candidate_repo, workflow, _ = self._make_workflow(
            tmp_path, knowledge_dir=knowledge_dir
        )
        gc = _make_graph_change_node()
        candidate_repo.append_candidate(gc)

        # 攻击：损坏 evidence payload
        db._conn.execute(
            "UPDATE evidence SET payload = ? WHERE evidence_id = ?",
            ("{this is not json", EVIDENCE_UUID),
        )
        db._conn.commit()

        result = workflow.review_export(gc.graph_change_id)

        assert result.status == "error"
        assert "invalid JSON" in result.error

        db.close()


# ═══════════════════════════════════════════════════════════════
# Tests: review_eligible vs apply_eligible
# ═══════════════════════════════════════════════════════════════

class TestEligibilitySeparation:
    """review_eligible 与 apply_eligible 分离测试。"""

    def test_conflicts_block_apply_not_review(self):
        """有冲突阻止 apply 但不阻止 review。"""
        gc = _make_graph_change_node(
            conflicts=["冲突数据源：源A vs 源B"]
        )
        # 有冲突的 candidate 仍然可以被审核
        assert gc.review_status == "candidate"


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _ensure_graph_tables(db):
    """确保 graph 相关表存在。"""
    conn = db._conn
    conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_nodes (
            node_id TEXT, version INTEGER, payload TEXT,
            node_type TEXT, name TEXT, status TEXT,
            review_status TEXT, origin_kind TEXT, created_at TEXT,
            valid_from TEXT, valid_to TEXT, last_reviewed_at TEXT,
            originating_graph_change_id TEXT,
            PRIMARY KEY (node_id, version)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_edges (
            edge_id TEXT, version INTEGER, payload TEXT,
            source_node_id TEXT, relation TEXT, target_node_id TEXT,
            assertion_type TEXT, review_status TEXT, created_at TEXT,
            valid_from TEXT, valid_to TEXT, confidence REAL,
            last_reviewed_at TEXT, originating_graph_change_id TEXT,
            PRIMARY KEY (edge_id, version)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_reviews (
            review_id TEXT PRIMARY KEY, payload TEXT,
            graph_change_id TEXT, decision TEXT,
            reviewer_id TEXT, reviewed_at TEXT,
            candidate_hash TEXT, resulting_graph_change_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_changes (
            graph_change_id TEXT PRIMARY KEY, payload TEXT,
            change_type TEXT, review_status TEXT, created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY, payload TEXT,
            source_id TEXT, raw_item_id TEXT,
            independence_group TEXT, source_tier TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            entity_id TEXT PRIMARY KEY, payload TEXT,
            entity_type TEXT, canonical_name TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_items (
            raw_item_id TEXT PRIMARY KEY, payload TEXT
        )
    """)
    conn.commit()


def _setup_minimal_db_for_import(db):
    """为 import 测试设置最小 DB 状态。"""
    _ensure_graph_tables(db)

    conn = db._conn

    # Insert evidence
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
    ev_payload = json.dumps(
        ev.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    conn.execute(
        "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            ev.evidence_id, ev_payload, ev.source_id, ev.raw_item_id,
            ev.independence_group, ev.source_tier,
        ),
    )

    # Insert raw_item
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

    # Insert entities
    for eid, ename in [
        ("company:test-corp", "测试公司"),
        ("company:src", "源公司"),
        ("company:tgt", "目标公司"),
    ]:
        entity = Entity(
            entity_id=eid,
            entity_type="company",
            canonical_name=ename,
        )
        ent_payload = json.dumps(
            entity.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        conn.execute(
            "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
            "VALUES (?, ?, ?, ?)",
            (eid, ent_payload, "company", ename),
        )

    # Insert graph nodes for source/target (needed by KGV-004)
    for nid, nname in [
        ("company:src", "源公司"),
        ("company:tgt", "目标公司"),
    ]:
        node_payload = json.dumps({
            "node_id": nid,
            "node_type": "Company",
            "name": nname,
            "status": "active",
            "version": 1,
            "origin_kind": "governance_seed",
            "review_status": "approved",
            "created_at": T0,
            "evidence_ids": [],
        }, ensure_ascii=False)
        conn.execute(
            "INSERT OR IGNORE INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at) "
            "VALUES (?, 1, ?, 'Company', ?, 'active', 'approved', 'governance_seed', ?)",
            (nid, node_payload, nname, T0),
        )

    conn.commit()


def _insert_evidence(db, ev):
    """向 evidence 表插入一条记录。"""
    conn = db._conn
    ev_payload = json.dumps(
        ev.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    conn.execute(
        "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            ev.evidence_id, ev_payload, ev.source_id, ev.raw_item_id,
            ev.independence_group, ev.source_tier,
        ),
    )
    conn.commit()


def _insert_entity(db, entity):
    """向 entities 表插入一条记录。"""
    conn = db._conn
    ent_payload = json.dumps(
        entity.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    conn.execute(
        "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
        "VALUES (?, ?, ?, ?)",
        (entity.entity_id, ent_payload, entity.entity_type, entity.canonical_name),
    )
    conn.commit()


def _insert_candidate_raw(db, gc_dict):
    """直接将 candidate dict 插入 graph_changes 表（绕过 append_candidate 门禁）。"""
    conn = db._conn
    payload = json.dumps(
        gc_dict, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    conn.execute(
        "INSERT OR IGNORE INTO graph_changes (graph_change_id, payload, change_type, review_status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            gc_dict["graph_change_id"], payload,
            gc_dict.get("change_type", "add_node"),
            gc_dict.get("review_status", "candidate"),
            gc_dict.get("created_at", T0),
        ),
    )
    conn.commit()


def _count_table(db, table_name):
    """统计表中行数。"""
    conn = db._conn
    row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table_name}").fetchone()
    return row["cnt"] if row else 0
