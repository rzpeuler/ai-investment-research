"""GapClassifier（P7-D1）。

输入：ScenarioDataRequirement + DataReadiness + AcquisitionCapability +
DataRequirementRegistry 信息。输出 DataGap。
严格确定性：ZERO LLM / NO NETWORK / NO WRITE；不得调用 Source fetcher。

基本映射：READY → AVAILABLE；其余按能力决定。
AUTO_ACQUIRABLE / STALE_REFRESHABLE 只有 automatic_acquisition_lifecycle =
BUSINESS_SUFFICIENT 才允许输出（保守规则，§46）。
"""
from __future__ import annotations

from typing import List, Optional

from research_os.data_layer.capabilities import AcquisitionCapability, AcquisitionCapabilityRegistry
from research_os.models import DataGap, DataReadiness, ScenarioDataRequirement

# 标准化 reason codes（§62）
READINESS_READY = "READINESS_READY"
NO_ELIGIBLE_RECORDS = "NO_ELIGIBLE_RECORDS"
COVERAGE_NOT_MEASURABLE_RC = "COVERAGE_NOT_MEASURABLE"
DATA_STALE = "DATA_STALE"
AUTO_CAPABILITY_AVAILABLE = "AUTO_CAPABILITY_AVAILABLE"
AUTO_CAPABILITY_NOT_BUSINESS_SUFFICIENT = "AUTO_CAPABILITY_NOT_BUSINESS_SUFFICIENT"
DETERMINISTIC_DERIVATION_AVAILABLE = "DETERMINISTIC_DERIVATION_AVAILABLE"
MANUAL_FALLBACK_AVAILABLE = "MANUAL_FALLBACK_AVAILABLE"
HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
GOVERNED_WORKFLOW_REQUIRED = "GOVERNED_WORKFLOW_REQUIRED"
NO_ACQUISITION_PATH = "NO_ACQUISITION_PATH"

# classification → recommended_action（§63）
_RECOMMENDED_ACTION = {
    "AVAILABLE": "none",
    "AUTO_ACQUIRABLE": "route_existing_sources",
    "STALE_REFRESHABLE": "route_existing_sources",
    "AUTO_DERIVABLE": "derive_existing",
    "MANUAL_INPUT_REQUIRED": "request_manual_input",
    "HUMAN_REVIEW_REQUIRED": "request_human_review",
    "GOVERNED_WORKFLOW_REQUIRED": "governed_workflow",
    "UNAVAILABLE": "unavailable",
}


class GapClassifier:
    """确定性 Gap 分类器。"""

    def __init__(self, capabilities: AcquisitionCapabilityRegistry):
        self._capabilities = capabilities

    def classify(
        self,
        requirement: ScenarioDataRequirement,
        readiness: DataReadiness,
        fallback_modes_available: Optional[List[str]] = None,
    ) -> DataGap:
        capability = self._capabilities.get(requirement.data_type)
        classification, reason_codes, missing_fields, requires_network, \
            requires_user_input, requires_human_review, warnings = \
            self._classify(requirement, readiness, capability, fallback_modes_available)
        return DataGap(
            requirement_id=requirement.requirement_id,
            data_type=requirement.data_type,
            classification=classification,
            reason_codes=sorted(reason_codes),
            missing_fields=sorted(missing_fields),
            recommended_action=_RECOMMENDED_ACTION[classification],
            requires_network=requires_network,
            requires_user_input=requires_user_input,
            requires_human_review=requires_human_review,
            warnings=warnings,
        )

    def _classify(self, requirement, readiness, capability, fallback_modes_available):
        missing_fields = list(readiness.missing_fields or [])
        warnings: List[str] = list(readiness.warnings or [])

        if readiness.status == "READY":
            return ("AVAILABLE", [READINESS_READY], missing_fields,
                    False, False, False, warnings)

        if capability.deterministic_derivation and self._derivation_inputs_sufficient(readiness):
            return ("AUTO_DERIVABLE", [DETERMINISTIC_DERIVATION_AVAILABLE], missing_fields,
                    False, False, False, warnings)

        if readiness.status == "STALE" and \
                capability.automatic_acquisition_lifecycle == "BUSINESS_SUFFICIENT":
            return ("STALE_REFRESHABLE", [DATA_STALE, AUTO_CAPABILITY_AVAILABLE], missing_fields,
                    True, False, False, warnings)

        if capability.automatic_acquisition_lifecycle == "BUSINESS_SUFFICIENT":
            return ("AUTO_ACQUIRABLE", [AUTO_CAPABILITY_AVAILABLE], missing_fields,
                    True, False, False, warnings)

        if capability.automatic_acquisition_lifecycle not in ("NONE",):
            # 有实现但未达到业务充分：不得宣称 AUTO_ACQUIRABLE
            warnings.append(AUTO_CAPABILITY_NOT_BUSINESS_SUFFICIENT)

        if capability.requires_human_review:
            return ("HUMAN_REVIEW_REQUIRED", [HUMAN_REVIEW_REQUIRED], missing_fields,
                    False, True, True, warnings)

        manual_modes = set(capability.manual_modes)
        allowed = set(requirement.acceptable_fallback_modes)
        overlap = manual_modes & allowed
        if overlap:
            return ("MANUAL_INPUT_REQUIRED", [MANUAL_FALLBACK_AVAILABLE], missing_fields,
                    False, True, False, warnings)

        if capability.requires_governed_workflow:
            return ("GOVERNED_WORKFLOW_REQUIRED", [GOVERNED_WORKFLOW_REQUIRED], missing_fields,
                    False, False, False, warnings)

        return ("UNAVAILABLE", [NO_ACQUISITION_PATH], missing_fields,
                False, False, False, warnings)

    @staticmethod
    def _derivation_inputs_sufficient(readiness: DataReadiness) -> bool:
        """确定性推导需要已有权威输入足以执行现有 derivation。

        D1 保守规则：仅当 readiness 已有合格记录（eligible > 0）时才认为可推导。
        """
        return readiness.eligible_record_count > 0
