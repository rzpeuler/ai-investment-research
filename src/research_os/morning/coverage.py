"""四个并列监测方向覆盖状态（Phase 2 任务 5.2 节）。

必须区分：已覆盖 / 部分覆盖 / 仅人工导入 / 未覆盖 / 来源故障 /
窗口内确实无有效信息。禁止把"没有采集能力"写成"该方向没有信息"。
"""
from __future__ import annotations

from typing import Dict, List

from research_os.models.morning import MONITORING_CHANNELS


def build_coverage(
    channel_sources: Dict[str, List[str]],
    succeeded: Dict[str, List[str]],
    failures: Dict[str, List[str]],
    limitations: Dict[str, List[str]],
    automated_channels: Optional[set] = None,
) -> List[dict]:
    """构建四方向覆盖说明。

    channel_sources: 方向 -> 已配置来源
    succeeded: 方向 -> 实际成功来源
    failures: 方向 -> 失败来源
    limitations: 方向 -> 限制说明
    automated_channels: 有自动采集能力的方向（其余视为仅人工导入）
    """
    automated = automated_channels or set()
    coverage = []
    for channel in MONITORING_CHANNELS:
        sources = channel_sources.get(channel, [])
        ok = succeeded.get(channel, [])
        failed = failures.get(channel, [])
        lim = limitations.get(channel, [])
        manual_only = channel not in automated and not ok
        if manual_only:
            status = "manual_only"
            lim = lim or ["当前仅支持 manual_inbox"]
        elif not ok and failed:
            status = "source_failure"
            lim = lim + [f"来源故障: {failed}"]
        elif ok and len(ok) < len(sources):
            status = "partial"
        elif ok:
            status = "covered"
        else:
            status = "not_covered"
        coverage.append({
            "monitoring_channel": channel,
            "status": status,
            "sources_attempted": sources,
            "sources_succeeded": ok,
            "limitations": lim,
        })
    return coverage
