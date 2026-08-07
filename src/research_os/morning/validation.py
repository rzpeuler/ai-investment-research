"""晨报 Claim/Evidence 机械校验。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class MorningEvidenceValidation:
    status: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def validate_morning_evidence(artifacts: Any) -> MorningEvidenceValidation:
    errors: List[str] = []
    warnings: List[str] = []
    evidence_by_id: Dict[str, dict] = {
        e.evidence_id: e.model_dump() if hasattr(e, "model_dump") else dict(e)
        for e in artifacts.evidences
    }
    raw_by_id = {r.raw_item_id: r.model_dump() for r in artifacts.raw_items}
    raw_ids = set(raw_by_id)
    claim_ids = {c.get("claim_id") for c in artifacts.claims}
    candidate_ids = {c.candidate_id for c in artifacts.candidates}

    for eid, evidence in evidence_by_id.items():
        if evidence.get("raw_item_id") not in raw_ids:
            errors.append(f"Evidence.raw_item_id 不存在: {eid}")
        else:
            raw = raw_by_id[evidence["raw_item_id"]]
            for field_name in ("source_id", "publisher", "published_at", "retrieved_at", "url"):
                if evidence.get(field_name) != raw.get(field_name):
                    errors.append(f"Evidence 与 RawItem 的 {field_name} 不一致: {eid}")
        if not evidence.get("source_id") or not evidence.get("published_at") or not evidence.get("url"):
            errors.append(f"Evidence 缺来源、时间或追溯位置: {eid}")

    def check_eids(owner: str, ids: List[str]) -> None:
        for eid in ids:
            if eid in claim_ids:
                errors.append(f"claim_id 冒充 evidence_id: {owner} -> {eid}")
            if eid in candidate_ids:
                errors.append(f"candidate_id 冒充 evidence_id: {owner} -> {eid}")
            if eid not in evidence_by_id:
                errors.append(f"不存在的 Evidence ID: {owner} -> {eid}")

    for claim in artifacts.claims:
        eids = list(claim.get("evidence_ids") or [])
        check_eids(claim.get("claim_id", "claim"), eids)
        if claim.get("claim_type") == "FACT":
            if not eids:
                errors.append(f"FACT 缺 Evidence: {claim.get('claim_id')}")
            if eids and all(evidence_by_id.get(eid, {}).get("source_tier") in ("C", "D") for eid in eids):
                errors.append(f"C/D 级来源不能单独支持核心 FACT: {claim.get('claim_id')}")
        if claim.get("claim_type") == "MODEL_INFERENCE":
            errors.append(f"deterministic_fallback 不得产生 MODEL_INFERENCE: {claim.get('claim_id')}")
        if claim.get("claim_type") == "SOURCE_OPINION":
            obj = claim.get("object") or {}
            if not (obj.get("speaker") or obj.get("publisher")):
                errors.append(f"SOURCE_OPINION 缺说话者或发布主体: {claim.get('claim_id')}")
    for cluster in artifacts.clusters:
        check_eids(cluster.cluster_id, list(cluster.primary_evidence_ids))

    for match in re.finditer(r"Evidence ID:\s*`?([0-9a-fA-F-]{36})`?", artifacts.markdown):
        if match.group(1) not in evidence_by_id:
            errors.append(f"Markdown 引用不存在的 Evidence: {match.group(1)}")
    return MorningEvidenceValidation("fail" if errors else "pass", errors, warnings)
