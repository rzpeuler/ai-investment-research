"""M3 Candidate Renderer：确定性 Markdown 渲染器。

生成 knowledge/candidates/{id}.md 候选审阅文件。
固定分段结构，证据仅最小信息，幂等回放。
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from research_os.models import GraphChange, Evidence
from research_os.knowledge.candidate_sources import EvidenceContext


def _render_evidence_info(contexts: List[EvidenceContext]) -> str:
    """渲染证据最小信息列表。"""
    if not contexts:
        return "_（无证据上下文）_\n"

    lines = []
    for i, ctx in enumerate(contexts, 1):
        role_label = "🔴 反证" if ctx.role == "counter" else "🟢 支持"
        lines.append(f"**{i}. [{role_label}] {ctx.title}**")
        lines.append(f"  - ID: `{ctx.evidence_id}`")
        lines.append(f"  - 发布者: {ctx.publisher}")
        lines.append(f"  - 发布时间: {ctx.published_at}")
        lines.append(f"  - 来源等级: `{ctx.source_tier}`")
        lines.append(f"  - 类型: {ctx.evidence_type}")
        lines.append(f"  - URL: {ctx.url}")
        lines.append(f"  - 摘录: {ctx.excerpt}")
        lines.append("")
    return "\n".join(lines)


def _render_node_info(node: Optional[dict]) -> str:
    """渲染节点信息。"""
    if node is None:
        return "_（无节点信息）_\n"
    lines = [
        f"- **node_id**: `{node.get('node_id', 'N/A')}`",
        f"- **node_type**: `{node.get('node_type', 'N/A')}`",
        f"- **name**: {node.get('name', 'N/A')}",
        f"- **version**: {node.get('version', 'N/A')}",
        f"- **status**: `{node.get('status', 'N/A')}`",
    ]
    return "\n".join(lines) + "\n"


def _render_edge_info(edge: Optional[dict]) -> str:
    """渲染边信息。"""
    if edge is None:
        return "_（无边信息）_\n"
    lines = [
        f"- **edge_id**: `{edge.get('edge_id', 'N/A')}`",
        f"- **source_node_id**: `{edge.get('source_node_id', 'N/A')}`",
        f"- **relation**: `{edge.get('relation', 'N/A')}`",
        f"- **target_node_id**: `{edge.get('target_node_id', 'N/A')}`",
        f"- **version**: {edge.get('version', 'N/A')}",
        f"- **confidence**: {edge.get('confidence', 'N/A')}",
        f"- **assertion_type**: `{edge.get('assertion_type', 'N/A')}`",
    ]
    return "\n".join(lines) + "\n"


def render_candidate_markdown(
    graph_change: GraphChange,
    evidence_contexts: List[EvidenceContext],
    render_at: Optional[str] = None,
) -> str:
    """将 GraphChange candidate 渲染为 Markdown。

    Args:
        graph_change: 完整 GraphChange 对象。
        evidence_contexts: 证据上下文列表。
        render_at: 渲染时间 ISO-8601。

    Returns:
        Markdown 字符串。
    """
    gc = graph_change.model_dump()
    now = render_at or datetime.now().isoformat(timespec="seconds")

    sections = []

    # 标题
    sections.append(f"# GraphChange Candidate: {gc['graph_change_id'][:8]}")
    sections.append("")

    # 1. GraphChange ID
    sections.append("## 1. 变更标识")
    sections.append("")
    sections.append(f"- **graph_change_id**: `{gc['graph_change_id']}`")
    sections.append(f"- **change_type**: `{gc['change_type']}`")
    sections.append(f"- **review_status**: `{gc['review_status']}`")
    sections.append(f"- **created_at**: {gc['created_at']}")
    sections.append("")

    # 2. Current Knowledge
    sections.append("## 2. 当前图谱知识")
    sections.append("")
    current = gc.get("current_knowledge", "")
    if current:
        sections.append("```json")
        sections.append(current)
        sections.append("```")
    else:
        sections.append("_（无当前知识——此为新节点/边）_")
    sections.append("")

    # 3. New Evidence
    sections.append("## 3. 新证据")
    sections.append("")
    sections.append(_render_evidence_info(evidence_contexts))

    # 4. Suggested Change
    sections.append("## 4. 建议变更")
    sections.append("")
    sections.append(gc.get("suggested_change", "_（无）_"))
    sections.append("")

    # 5. Impact
    sections.append("## 5. 影响范围")
    sections.append("")
    impact = gc.get("impact_scope", [])
    if impact:
        for item in impact:
            sections.append(f"- {item}")
    else:
        sections.append("_（无）_")
    sections.append("")

    # 6. Conflicts
    sections.append("## 6. 冲突")
    sections.append("")
    conflicts = gc.get("conflicts", [])
    if conflicts:
        for item in conflicts:
            sections.append(f"- {item}")
    else:
        sections.append("_（无冲突）_")
    sections.append("")

    # 7. Verification
    sections.append("## 7. 验证点")
    sections.append("")
    vps = gc.get("verification_points", [])
    if vps:
        for item in vps:
            sections.append(f"- [ ] {item}")
    else:
        sections.append("_（无验证点）_")
    sections.append("")

    # 8. 节点/边详情
    sections.append("## 8. 变更载体")
    sections.append("")
    if gc.get("node") is not None:
        sections.append("### 节点")
        sections.append("")
        sections.append(_render_node_info(gc["node"]))
    if gc.get("edge") is not None:
        sections.append("### 边")
        sections.append("")
        sections.append(_render_edge_info(gc["edge"]))

    # 9. Review Checkboxes
    sections.append("## 9. 审核清单")
    sections.append("")
    sections.append("- [ ] 证据来源可靠且可验证")
    sections.append("- [ ] 变更范围明确且影响可控")
    sections.append("- [ ] 实体身份解析正确")
    sections.append("- [ ] 与现有图谱无冲突")
    sections.append("- [ ] 符合知识策略要求")
    sections.append("")

    # 10. Review
    sections.append("## 10. 审核决定")
    sections.append("")
    sections.append("- **审核人**: _（待审核）_")
    sections.append("- **决定**: `[ ] approved / [ ] approved_with_changes / [ ] deferred / [ ] rejected`")
    sections.append("- **备注**: _（待填写）_")
    sections.append("")

    # 11. Approved Patch
    sections.append("## 11. 批准补丁")
    sections.append("")
    sections.append("_（审核通过后在此填写 JSON Patch）_")
    sections.append("")

    # Footer
    sections.append("---")
    sections.append(f"*渲染时间: {now}*")

    return "\n".join(sections)


class CandidateRenderer:
    """Candidate Markdown 渲染器（幂等文件写入）。"""

    def __init__(self, knowledge_dir: Path):
        """knowledge_dir 为项目 knowledge/ 目录。"""
        self._candidates_dir = knowledge_dir / "candidates"
        self._candidates_dir.mkdir(parents=True, exist_ok=True)

    def render_to_file(
        self,
        graph_change: GraphChange,
        evidence_contexts: List[EvidenceContext],
        *,
        dry_run: bool = False,
    ) -> str:
        """渲染 candidate 到 Markdown 文件。

        Args:
            graph_change: GraphChange 实例。
            evidence_contexts: 证据上下文。
            dry_run: 为 True 时只返回内容，不写文件。

        Returns:
            文件路径或 "dry-run"。

        Raises:
            ValueError: CANDIDATE_FILE_CONFLICT（同 id 不同内容）。
        """
        content = render_candidate_markdown(graph_change, evidence_contexts)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        file_path = self._candidates_dir / f"{graph_change.graph_change_id}.md"

        if dry_run:
            return "dry-run"

        if file_path.exists():
            existing_content = file_path.read_text(encoding="utf-8")
            existing_hash = hashlib.sha256(existing_content.encode("utf-8")).hexdigest()
            if existing_hash == content_hash:
                return str(file_path)  # idempotent
            raise ValueError(
                f"CANDIDATE_FILE_CONFLICT: {file_path.name} "
                f"already exists with different content"
            )

        file_path.write_text(content, encoding="utf-8")
        return str(file_path)
