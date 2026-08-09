"""晨报 Claim/Evidence 机械校验——兼容层。

Phase 6B（DECISIONS #43）后共享校验实现在 `research_os.brief.validation`；
morning_brief 与 evening_brief 共用同一校验规则。
"""
from __future__ import annotations

from typing import Any

from research_os.brief.validation import (
    BriefEvidenceValidation as MorningEvidenceValidation,
    validate_brief_evidence as validate_morning_evidence,
)

__all__ = ["MorningEvidenceValidation", "validate_morning_evidence"]
