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

# ---------- R1-08：DerivationPrerequisiteResolver ----------

# 显式 derivation prerequisite 证明器（§79-84）。
# 任何 deterministic_derivation=true 但没有显式 prerequisite resolver 的 data_type
# 不得 AUTO_DERIVABLE（§80）。禁止 eligible_record_count>0 通用规则（§81）。


class DerivationPrerequisiteResolver:
    """确定性推导前提证明器。

    默认规则：任何 data_type 若无显式证明器 → prerequisites NOT proven
    （保守，不得从空气生成推导）。
    """

    def __init__(self) -> None:
        # data_type → 前提证明函数（严格确定性；当前无 data_type 提供显式证明器）
        self._resolvers = {}

    def prerequisites_proven(self, data_type: str, readiness: DataReadiness) -> bool:
        resolver = self._resolvers.get(data_type)
        if resolver is None:
            # §80：无显式 prerequisite resolver → 不得 AUTO_DERIVABLE
            return False
        return bool(resolver(readiness))

    def register(self, data_type: str, fn) -> None:
        self._resolvers[data_type] = fn


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

    def __init__(self, capabilities: AcquisitionCapabilityRegistry,
                 derivation_resolver: Optional[DerivationPrerequisiteResolver] = None):
        self._capabilities = capabilities
        self._derivation = derivation_resolver or DerivationPrerequisiteResolver()

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

        # R1-08：AUTO_DERIVABLE 必须显式证明 prerequisites（禁止 eligible_count 通用规则）
        if capability.deterministic_derivation:
            proven = self._derivation.prerequisites_proven(requirement.data_type, readiness)
            if proven:
                return ("AUTO_DERIVABLE", [DETERMINISTIC_DERIVATION_AVAILABLE], missing_fields,
                        False, False, False, warnings)
            warnings.append("DERIVATION_PREREQUISITES_UNPROVEN")

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
