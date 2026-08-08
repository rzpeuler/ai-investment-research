"""M5 Review Parser：解析人工填写后的审阅 Markdown。

fenced-block aware：```...``` 内部内容不解析为 heading/checkbox。
验证 13 个冻结标题严格顺序且各出现一次。
提取 graph_change_id、candidate_hash、decision、reviewer、notes、patch。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

# ── 冻结 13 标题（与 review_renderer.py 完全一致） ──────────────
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

# 决策复选框映射
_DECISION_LABELS = {
    "批准": "approved",
    "修改后批准": "approved_with_changes",
    "暂缓": "deferred",
    "拒绝": "rejected",
}

# UUID pattern（36 char hex-dash）
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
# SHA256 pattern（64 lowercase hex）
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class ParsedReview:
    """解析后的人工审阅数据。"""
    graph_change_id: str
    candidate_hash: str
    decision: str  # approved / approved_with_changes / deferred / rejected
    reviewer_id: str
    reviewer_type: str = "human"
    display_name: Optional[str] = None
    reviewed_at: str = ""
    review_notes: str = ""
    review_patch: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def _strip_fenced_blocks(text: str) -> str:
    """替换所有 ```...``` 为等长空白行，防止内容误解析为 heading/checkbox。"""
    result = []
    in_fence = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            result.append("")  # 保留行数以维持行号语义
        elif in_fence:
            result.append("")  # fenced 内容替换为空行
        else:
            result.append(line)
    return "\n".join(result)


def _find_headings(text: str) -> List[dict]:
    """在文本中定位所有冻结标题。

    Returns:
        [{heading, line_index, start_pos}, ...] 按出现顺序。
    """
    results = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        for h in _FROZEN_REVIEW_HEADINGS:
            if stripped == h:
                results.append({
                    "heading": h,
                    "line_index": i,
                    "position": len("\n".join(lines[:i])) if i > 0 else 0,
                })
                break
    return results


def _extract_between(text: str, start_heading: str, end_heading: Optional[str]) -> str:
    """提取两个标题之间的文本内容（不含标题行本身）。"""
    lines = text.split("\n")
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == start_heading and start_idx is None:
            start_idx = i + 1  # 从标题下一行开始
        if end_heading and stripped == end_heading and start_idx is not None:
            end_idx = i
            break
    if start_idx is None:
        return ""
    if end_idx is not None:
        return "\n".join(lines[start_idx:end_idx]).strip()
    return "\n".join(lines[start_idx:]).strip()


def _extract_yaml_key(section: str, key: str) -> Optional[str]:
    """从 YAML 样式的 section 中提取字段值。

    支持:
      key: value
      key: "value"
      key: 'value'
    """
    for line in section.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(f"{key}:"):
            val = stripped[len(key) + 1:].strip()
            # 去除引号
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            return val if val else ""
    return None


def _check_fenced_block_integrity(text: str) -> List[str]:
    """检查 fenced blocks 是否配对关闭。"""
    errors = []
    fence_count = 0
    in_fence = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fence_count += 1
    if in_fence:
        errors.append("未闭合的 fenced block（```）")
    return errors


def parse_review_markdown(md_text: str) -> ParsedReview:
    """解析人工填写后的审阅 Markdown。

    Args:
        md_text: 完整的审阅 Markdown 文本。

    Returns:
        ParsedReview 对象，含 errors 列表。
    """
    errors: List[str] = []

    # 1. 检查 fenced block 完整性
    errors.extend(_check_fenced_block_integrity(md_text))

    # 2. 移除 fenced 内容后定位标题
    clean_text = _strip_fenced_blocks(md_text)
    headings = _find_headings(clean_text)

    # 3. 验证 13 个标题严格顺序且各出现一次
    found_heading_names = [h["heading"] for h in headings]
    if found_heading_names != _FROZEN_REVIEW_HEADINGS:
        # 检查缺失和多余
        expected_set = set(_FROZEN_REVIEW_HEADINGS)
        found_set = set(found_heading_names)
        missing = expected_set - found_set
        extra = found_set - expected_set
        if missing:
            errors.append(f"缺失标题: {', '.join(sorted(missing))}")
        if extra:
            errors.append(f"多余标题: {', '.join(sorted(extra))}")
        # 检查顺序
        # Filter found headings to only those in the frozen set (preserve order)
        ordered_found = [h for h in found_heading_names if h in expected_set]
        ordered_expected = [h for h in _FROZEN_REVIEW_HEADINGS if h in found_set]
        if ordered_found != ordered_expected:
            errors.append(
                f"标题顺序错误: 期望 {ordered_expected}, 实际 {ordered_found}"
            )
        if missing or extra:
            # 不允许继续解析
            return ParsedReview(
                graph_change_id="",
                candidate_hash="",
                decision="",
                reviewer_id="",
                errors=errors,
            )

    # Check for duplicate headings
    for h in found_heading_names:
        if found_heading_names.count(h) > 1:
            errors.append(f"重复标题: {h}")
    if errors:
        return ParsedReview(
            graph_change_id="",
            candidate_hash="",
            decision="",
            reviewer_id="",
            errors=errors,
        )

    # 4. 提取 GraphChange ID section 内容
    gc_section = _extract_between(md_text, "## GraphChange ID", "## 变更类型")

    # 提取 graph_change_id
    gc_match = re.search(
        r"\*\*graph_change_id\*\*:\s*`([^`]+)`", gc_section
    )
    if not gc_match:
        errors.append("未找到 graph_change_id")
        graph_change_id = ""
    else:
        graph_change_id = gc_match.group(1).strip()
        if not _UUID_RE.match(graph_change_id):
            errors.append(f"graph_change_id 格式非法: {graph_change_id}")

    # 提取 candidate_hash
    hash_match = re.search(
        r"\*\*candidate_hash\*\*:\s*`([^`]+)`", gc_section
    )
    if not hash_match:
        errors.append("未找到 candidate_hash")
        candidate_hash = ""
    else:
        candidate_hash = hash_match.group(1).strip()
        if not _SHA256_RE.match(candidate_hash):
            errors.append(f"candidate_hash 格式非法: {candidate_hash}")

    # 5. 提取审核选项（checkbox）
    review_section = _extract_between(md_text, "## 审核选项", "## Reviewer")

    checked_decisions = []
    for line in review_section.split("\n"):
        stripped = line.strip()
        for label, dec in _DECISION_LABELS.items():
            # 检查 [x] 或 [X]
            if re.match(rf"- \[[xX]\]\s*{re.escape(label)}\s*$", stripped):
                checked_decisions.append(dec)
                break

    if len(checked_decisions) == 0:
        errors.append("未选中任何审核决策（需要从 [批准/修改后批准/暂缓/拒绝] 中选中一项）")
        decision = ""
    elif len(checked_decisions) > 1:
        errors.append(f"选中了多项审核决策: {checked_decisions}（只能选一项）")
        decision = ""
    else:
        decision = checked_decisions[0]

    # 6. 提取 Reviewer section
    reviewer_section = _extract_between(md_text, "## Reviewer", "## Review Notes")

    reviewer_type = _extract_yaml_key(reviewer_section, "reviewer_type")
    if reviewer_type and reviewer_type != "human":
        errors.append(f"reviewer_type 必须为 'human'，当前为 '{reviewer_type}'")
    elif not reviewer_type:
        errors.append("未填写 reviewer_type")

    reviewer_id = _extract_yaml_key(reviewer_section, "reviewer_id")
    if not reviewer_id:
        errors.append("reviewer_id 未填写（必须为非空字符串）")
    elif reviewer_id.strip() == "":
        errors.append("reviewer_id 为空（必须为非空字符串）")

    display_name = _extract_yaml_key(reviewer_section, "display_name")

    reviewed_at = _extract_yaml_key(reviewer_section, "reviewed_at")
    if not reviewed_at or reviewed_at.strip() == "":
        errors.append("reviewed_at 未填写（必须为显式 ISO 8601 datetime）")
    else:
        # Validate ISO 8601
        from research_os.utils.time import validate_iso
        if not validate_iso(reviewed_at):
            errors.append(f"reviewed_at 不是合法 ISO 8601 datetime: {reviewed_at}")

    # 7. 提取 Review Notes
    notes_section = _extract_between(md_text, "## Review Notes", "## Approved Patch")
    review_notes = notes_section.strip()
    # 移除占位符
    if review_notes == "_（请在此填写审核意见）_":
        review_notes = ""

    # 8. 提取 Approved Patch
    patch_section = _extract_between(md_text, "## Approved Patch", None)
    patch_section = patch_section.strip()
    # 移除 footer
    if "---" in patch_section:
        patch_section = patch_section.split("---")[0].strip()

    review_patch: List[dict] = []
    if decision == "approved_with_changes":
        # 期望 JSON 数组
        if not patch_section or patch_section.startswith("_"):
            errors.append("决策为\"修改后批准\"但未填写 Approved Patch")
        else:
            # 提取 JSON（可能在 ```json ... ``` 内）
            if "```" in patch_section:
                # 提取第一个 fenced block 内的 JSON
                fence_match = re.search(
                    r"```(?:json)?\s*\n(.*?)\n```", patch_section, re.DOTALL
                )
                if fence_match:
                    patch_section = fence_match.group(1).strip()
            try:
                patch_data = json.loads(patch_section)
                if not isinstance(patch_data, list):
                    errors.append("review_patch 必须是 JSON 数组")
                else:
                    review_patch = patch_data
            except json.JSONDecodeError as e:
                errors.append(f"Approved Patch JSON 解析失败: {e}")
    elif decision in ("approved", "deferred", "rejected"):
        # 这些决策不应有 patch
        if patch_section and not patch_section.startswith("_"):
            # 可能有注释或空内容，尝试解析 JSON 看看
            stripped_patch = patch_section.strip()
            if stripped_patch and not stripped_patch.startswith("_"):
                try:
                    patch_data = json.loads(stripped_patch)
                    if isinstance(patch_data, list) and len(patch_data) > 0:
                        errors.append(
                            f"决策为\"{decision}\"但提供了非空 Approved Patch"
                        )
                except json.JSONDecodeError:
                    pass  # 非 JSON，可能是注释文本，忽略

    return ParsedReview(
        graph_change_id=graph_change_id,
        candidate_hash=candidate_hash,
        decision=decision,
        reviewer_id=reviewer_id or "",
        reviewer_type=reviewer_type or "human",
        display_name=display_name,
        reviewed_at=reviewed_at or "",
        review_notes=review_notes,
        review_patch=review_patch,
        errors=errors,
    )
