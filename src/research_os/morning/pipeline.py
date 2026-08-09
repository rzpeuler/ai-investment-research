"""晨报流水线（Phase 2 任务 4 节完整处理链）——兼容层。

Phase 6B（DECISIONS #43）后共享信息处理链实现在 `research_os.brief.pipeline`；
MorningBriefPipeline 即共享 BriefPipeline（默认 morning 窗口策略），
Phase 2 公开 API 与行为保持不变。
"""
from __future__ import annotations

from research_os.brief.pipeline import (
    BriefPipeline,
    MorningBriefPipeline,
    PipelineArtifacts,
    PipelineConfig,
)

__all__ = ["MorningBriefPipeline", "BriefPipeline", "PipelineConfig", "PipelineArtifacts"]
