"""M5 Review Renderer：确定性 Markdown 审阅导出器。

生成 knowledge/candidates/{graph_change_id}.md 人工审阅文件。
冻结 13-heading 格式，包含 candidate_hash、Reviewer 模板、4 个审核选项 checkbox。
Evidence 以中性格式展示（来自 persisted Evidence）。

确定性要求：
- 不使用 datetime.now()
- 相同输入 → 相同输出，跨时间不变
- 冻结标题格式，永不改变

candidate hash 唯一 authority = KnowledgeValidator.compute_candidate_hash()。
本模块不实现第二套 candidate hash 算法。
"""
from __future__ import annotations

from typing import List, Optional

from research_os.models import GraphChange
from research_os.knowledge.knowledge_validator import KnowledgeValidator

# ── 冻结 13 标题 ────────────────────────────────────────────────
_FROZEN_REVIEW_HEADINGS = [
    "# 图谱变更候选",
    "## GraphChange ID",
    "## 变更类型",
    "## 当前知识",
    "## 新证据",
    "## 建议变更",
    "## 影响范围",
    "## 冲突信息",
    "## 验证节点",
    "## 审核选项",
    "## Reviewer",
    "## Review Notes",
    "## Approved Patch",
]


def _render_evidence_list(evidence_records: List[dict]) -> str:
    """从 persisted Evidence dict 渲染证据列表（中性格式）。"""
    if not evidence_records:
        return "_（无证据）_\n"

    lines = []
    for i, ev in enumerate(evidence_records, 1):
        ev_id = ev.get("evidence_id", "N/A")
        title = ev.get("title", "N/A")
        publisher = ev.get("publisher", "N/A")
        published_at = ev.get("published_at", "N/A")
        source_tier = ev.get("source_tier", "N/A")
        evidence_type = ev.get("evidence_type", "N/A")
        url = ev.get("url", "")
        excerpt = ev.get("excerpt", "")

        lines.append(f"**{i}. {title}**")
        lines.append(f"  - ID: `{ev_id}`")
        lines.append(f"  - 发布者: {publisher}")
        lines.append(f"  - 发布时间: {published_at}")
        lines.append(f"  - 来源等级: `{source_tier}`")
        lines.append(f"  - 类型: {evidence_type}")
        if url:
            lines.append(f"  - URL: {url}")
        if excerpt:
            lines.append(f"  - 摘录: {excerpt}")
        lines.append("")
    return "\n".join(lines)


def _render_node_info(node) -> str:
    """渲染节点信息（中性格式）。"""
    if node is None:
        return "_（无节点信息）_\n"
    lines = [
        f"- **node_id**: `{getattr(node, 'node_id', 'N/A')}`",
        f"- **node_type**: `{getattr(node, 'node_type', 'N/A')}`",
        f"- **name**: {getattr(node, 'name', 'N/A')}",
        f"- **version**: {getattr(node, 'version', 'N/A')}",
        f"- **status**: `{getattr(node, 'status', 'N/A')}`",
    ]
    return "\n".join(lines) + "\n"


def _render_edge_info(edge) -> str:
    """渲染边信息（中性格式）。"""
    if edge is None:
        return "_（无边信息）_\n"
    lines = [
        f"- **edge_id**: `{getattr(edge, 'edge_id', 'N/A')}`",
        f"- **source_node_id**: `{getattr(edge, 'source_node_id', 'N/A')}`",
        f"- **relation**: `{getattr(edge, 'relation', 'N/A')}`",
        f"- **target_node_id**: `{getattr(edge, 'target_node_id', 'N/A')}`",
        f"- **version**: {getattr(edge, 'version', 'N/A')}",
        f"- **confidence**: {getattr(edge, 'confidence', 'N/A')}",
        f"- **assertion_type**: `{getattr(edge, 'assertion_type', 'N/A')}`",
    ]
    return "\n".join(lines) + "\n"


def review_export_markdown(
    graph_change: GraphChange,
    evidence_records: Optional[List[dict]] = None,
    candidate_hash: Optional[str] = None,
) -> str:
    """将 GraphChange candidate 渲染为审阅 Markdown（冻结 13-heading 格式）。

    Args:
        graph_change: 完整 GraphChange 对象。
        evidence_records: persisted Evidence dict 列表（中性格式展示）。
        candidate_hash: 由调用方（ReviewWorkflow）通过
            KnowledgeValidator.compute_candidate_hash() 计算后传入；
            为 None 时退回唯一 authority 计算，保证本模块不持有第二套算法。

    Returns:
        Markdown 字符串。
    """
    gc_dump = graph_change.model_dump()
    if candidate_hash is None:
        candidate_hash = KnowledgeValidator.compute_candidate_hash(graph_change)
    ev_list = evidence_records or []

    sections = []
    headings = iter(_FROZEN_REVIEW_HEADINGS)

    # H1: # 图谱变更候选
    sections.append(next(headings))
    sections.append("")

    # H2: ## GraphChange ID
    sections.append(next(headings))
    sections.append("")
    sections.append(f"- **graph_change_id**: `{gc_dump['graph_change_id']}`")
    sections.append(f"- **candidate_hash**: `{candidate_hash}`")
    sections.append("")

    # H3: ## 变更类型
    sections.append(next(headings))
    sections.append("")
    sections.append(f"- **change_type**: `{gc_dump['change_type']}`")
    sections.append(f"- **review_status**: `{gc_dump['review_status']}`")
    sections.append(f"- **created_at**: {gc_dump['created_at']}")
    sections.append("")

    # H4: ## 当前知识
    sections.append(next(headings))
    sections.append("")
    current = gc_dump.get("current_knowledge", "")
    if current:
        sections.append("```json")
        sections.append(current)
        sections.append("```")
    else:
        sections.append("_（无当前知识——此为新节点/边）_")
    sections.append("")

    # H5: ## 新证据
    sections.append(next(headings))
    sections.append("")
    sections.append(_render_evidence_list(ev_list))
    sections.append("")

    # Node/Edge details (inline after evidence)
    if graph_change.node is not None:
        sections.append("### 节点")
        sections.append("")
        sections.append(_render_node_info(graph_change.node))
    if graph_change.edge is not None:
        sections.append("### 边")
        sections.append("")
        sections.append(_render_edge_info(graph_change.edge))

    # H6: ## 建议变更
    sections.append(next(headings))
    sections.append("")
    sections.append(gc_dump.get("suggested_change", "_（无）_"))
    sections.append("")

    # H7: ## 影响范围
    sections.append(next(headings))
    sections.append("")
    impact = gc_dump.get("impact_scope", [])
    if impact:
        for item in impact:
            sections.append(f"- {item}")
    else:
        sections.append("_（无）_")
    sections.append("")

    # H8: ## 冲突信息
    sections.append(next(headings))
    sections.append("")
    conflicts = gc_dump.get("conflicts", [])
    if conflicts:
        for item in conflicts:
            sections.append(f"- {item}")
    else:
        sections.append("_（无冲突）_")
    sections.append("")

    # H9: ## 验证节点
    sections.append(next(headings))
    sections.append("")
    vps = gc_dump.get("verification_points", [])
    if vps:
        for item in vps:
            sections.append(f"- [ ] {item}")
    else:
        sections.append("_（无验证点）_")
    sections.append("")

    # H10: ## 审核选项（4 checkboxes）
    sections.append(next(headings))
    sections.append("")
    sections.append("- [ ] 批准")
    sections.append("- [ ] 修改后批准")
    sections.append("- [ ] 暂缓")
    sections.append("- [ ] 拒绝")
    sections.append("")

    # H11: ## Reviewer（template）
    sections.append(next(headings))
    sections.append("")
    sections.append("```yaml")
    sections.append("# 请填写以下字段：")
    sections.append("reviewer_type: human")
    sections.append("reviewer_id: \"\"      # 必填，非空")
    sections.append("display_name: \"\"     # 可选")
    sections.append("reviewed_at: \"\"      # ISO 8601 datetime，必填")
    sections.append("```")
    sections.append("")

    # H12: ## Review Notes
    sections.append(next(headings))
    sections.append("")
    sections.append("_（请在此填写审核意见）_")
    sections.append("")

    # H13: ## Approved Patch
    sections.append(next(headings))
    sections.append("")
    sections.append("_（仅\"修改后批准\"时填写 JSON Patch 数组）_")
    sections.append("")

    # Footer
    sections.append("---")
    sections.append("*本文件为审阅模板，请填写后通过 review-import 导入。*")

    return "\n".join(sections)
