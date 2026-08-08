"""M3 Candidate Renderer：确定性 Markdown 渲染器。

生成 knowledge/candidates/{id}.md 候选审阅文件。
固定分段结构，证据仅最小信息，幂等回放。

确定性要求：
- 不使用 datetime.now()，render_at 由调用方传入（固定时间戳或空字符串）
- 字节确定性：相同输入 → 相同输出，跨时间不变
- dry-run：__init__ 不创建目录；render_to_file dry_run=True 不写文件
- 文件冲突预检：在 DB 写入前检查，相同 hash → 幂等，不同 hash → 拒绝
- 标题格式：严格固定冻结格式，不受 proposal 内容影响
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Optional

from research_os.models import GraphChange, Evidence
from research_os.knowledge.candidate_sources import EvidenceContext

# 冻结的标题格式（确定性，永不改变）
# M3-R10: 新冻结格式
_FROZEN_HEADINGS = [
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
    render_at: str = "",
) -> str:
    """将 GraphChange candidate 渲染为 Markdown（字节确定性）。

    Args:
        graph_change: 完整 GraphChange 对象。
        evidence_contexts: 证据上下文列表。
        render_at: 渲染时间标签（空字符串则不显示时间，由调用方传入固定值以保证确定性）。

    Returns:
        Markdown 字符串。
    """
    gc = graph_change.model_dump()

    sections = []

    # 使用冻结标题
    headings = iter(_FROZEN_HEADINGS)

    # # 图谱变更候选
    h0 = next(headings)
    sections.append(h0)
    sections.append("")

    # ## GraphChange ID
    h1 = next(headings)
    sections.append(h1)
    sections.append("")
    sections.append(f"- **graph_change_id**: `{gc['graph_change_id']}`")
    sections.append("")

    # ## 变更类型
    h2 = next(headings)
    sections.append(h2)
    sections.append("")
    sections.append(f"- **change_type**: `{gc['change_type']}`")
    sections.append(f"- **review_status**: `{gc['review_status']}`")
    sections.append(f"- **created_at**: {gc['created_at']}")
    sections.append("")

    # ## 当前知识
    h3 = next(headings)
    sections.append(h3)
    sections.append("")
    current = gc.get("current_knowledge", "")
    if current:
        sections.append("```json")
        sections.append(current)
        sections.append("```")
    else:
        sections.append("_（无当前知识——此为新节点/边）_")
    sections.append("")

    # ## 新证据
    h4 = next(headings)
    sections.append(h4)
    sections.append("")
    sections.append(_render_evidence_info(evidence_contexts))

    # ## 建议变更
    h5 = next(headings)
    sections.append(h5)
    sections.append("")
    sections.append(gc.get("suggested_change", "_（无）_"))
    sections.append("")

    # ## 影响范围
    h6 = next(headings)
    sections.append(h6)
    sections.append("")
    impact = gc.get("impact_scope", [])
    if impact:
        for item in impact:
            sections.append(f"- {item}")
    else:
        sections.append("_（无）_")
    sections.append("")

    # ## 冲突信息
    h7 = next(headings)
    sections.append(h7)
    sections.append("")
    conflicts = gc.get("conflicts", [])
    if conflicts:
        for item in conflicts:
            sections.append(f"- {item}")
    else:
        sections.append("_（无冲突）_")
    sections.append("")

    # ## 验证节点
    h8 = next(headings)
    sections.append(h8)
    sections.append("")
    vps = gc.get("verification_points", [])
    if vps:
        for item in vps:
            sections.append(f"- [ ] {item}")
    else:
        sections.append("_（无验证点）_")
    sections.append("")

    # 节点/边详情（inline under 验证节点之后）
    if gc.get("node") is not None:
        sections.append("### 节点")
        sections.append("")
        sections.append(_render_node_info(gc["node"]))
    if gc.get("edge") is not None:
        sections.append("### 边")
        sections.append("")
        sections.append(_render_edge_info(gc["edge"]))

    # ## 审核选项 (+4 checkboxes)
    h9 = next(headings)
    sections.append(h9)
    sections.append("")
    sections.append("- [ ] 证据来源可靠且可验证")
    sections.append("- [ ] 变更范围明确且影响可控")
    sections.append("- [ ] 实体身份解析正确")
    sections.append("- [ ] 与现有图谱无冲突")
    sections.append("")

    # ## Reviewer (blank)
    h10 = next(headings)
    sections.append(h10)
    sections.append("")
    sections.append("_（待审核）_")
    sections.append("")

    # ## Review Notes (blank)
    h11 = next(headings)
    sections.append(h11)
    sections.append("")
    sections.append("_（待填写）_")
    sections.append("")

    # ## Approved Patch (blank)
    h12 = next(headings)
    sections.append(h12)
    sections.append("")
    sections.append("_（审核通过后在此填写 JSON Patch）_")
    sections.append("")

    # Footer（确定性：只在 render_at 非空时显示）
    sections.append("---")
    if render_at:
        sections.append(f"*渲染时间: {render_at}*")
    else:
        sections.append("*渲染时间: --*")

    return "\n".join(sections)


class CandidateRenderer:
    """Candidate Markdown 渲染器（幂等文件写入）。

    __init__ 不创建目录。仅在 render_to_file 时按需创建。
    这确保 dry-run 调用链中无副作用。
    """

    def __init__(self, knowledge_dir: Path, *, preflight_only: bool = False):
        """knowledge_dir 为项目 knowledge/ 目录。

        Note: __init__ 不创建目录。
        preflight_only: 仅用于预检，不实际写文件。
        """
        self._candidates_dir = knowledge_dir / "candidates"
        self._preflight_only = preflight_only

    def preflight_file_conflict(
        self, graph_change: GraphChange,
        evidence_contexts: Optional[List[EvidenceContext]] = None,
    ) -> bool:
        """文件冲突预检（在 DB 写入前调用）。

        检查同 ID 的 markdown 文件是否已存在且内容不同。
        使用与 render_to_file 相同的渲染参数以保证字节一致性。
        相同 hash → 幂等 OK
        不同 hash → ValueError CANDIDATE_FILE_CONFLICT
        不存在 → OK

        Returns:
            True if preflight passed (idempotent or new).

        Raises:
            ValueError: CANDIDATE_FILE_CONFLICT
        """
        ev_contexts = evidence_contexts or []
        content = render_candidate_markdown(graph_change, ev_contexts, render_at="")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        file_path = self._candidates_dir / f"{graph_change.graph_change_id}.md"

        if file_path.exists():
            existing_content = file_path.read_text(encoding="utf-8")
            existing_hash = hashlib.sha256(existing_content.encode("utf-8")).hexdigest()
            if existing_hash != content_hash:
                raise ValueError(
                    f"CANDIDATE_FILE_CONFLICT: {file_path.name} "
                    f"already exists with different content"
                )
            # 同 hash → 幂等 OK
            return True

        return True  # 文件不存在，fresh OK

    def render_to_file(
        self,
        graph_change: GraphChange,
        evidence_contexts: List[EvidenceContext],
        *,
        dry_run: bool = False,
        render_at: str = "",
    ) -> str:
        """渲染 candidate 到 Markdown 文件。

        Args:
            graph_change: GraphChange 实例。
            evidence_contexts: 证据上下文。
            dry_run: 为 True 时只返回内容哈希，不写文件。
            render_at: 渲染时间标签（确定性，由调用方传入）。

        Returns:
            文件路径或 "dry-run"。

        Raises:
            ValueError: CANDIDATE_FILE_CONFLICT（同 id 不同内容）。
        """
        content = render_candidate_markdown(
            graph_change, evidence_contexts, render_at=render_at
        )
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        file_path = self._candidates_dir / f"{graph_change.graph_change_id}.md"

        if dry_run:
            # dry-run：仅检查文件冲突（预检），不写文件
            if file_path.exists():
                existing_content = file_path.read_text(encoding="utf-8")
                existing_hash = hashlib.sha256(existing_content.encode("utf-8")).hexdigest()
                if existing_hash != content_hash:
                    raise ValueError(
                        f"CANDIDATE_FILE_CONFLICT: {file_path.name} "
                        f"already exists with different content"
                    )
            return "dry-run"

        # 文件冲突预检
        if file_path.exists():
            existing_content = file_path.read_text(encoding="utf-8")
            existing_hash = hashlib.sha256(existing_content.encode("utf-8")).hexdigest()
            if existing_hash == content_hash:
                return str(file_path)  # idempotent
            raise ValueError(
                f"CANDIDATE_FILE_CONFLICT: {file_path.name} "
                f"already exists with different content"
            )

        # 按需创建目录
        self._candidates_dir.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return str(file_path)
