"""事实/观点/推断分离（Phase 2 任务 9 节）。

使用既有 Claim 类型（FACT/SOURCE_OPINION/MODEL_INFERENCE/HYPOTHESIS/
UNKNOWN/CONFLICT）。确定性规则生成：
- 官方/监管/公司披露来源 -> FACT（需有证据）
- 社区/自媒体/含观点词 -> SOURCE_OPINION（记录说话者）
- 评分推理/影响路径 -> MODEL_INFERENCE（记录依据）
- 冲突检测：同簇内关键数值/时间/状态不一致 -> CONFLICT（不消除冲突）
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from research_os.models import CandidateItem, Claim, EventCluster
from research_os.utils.id import new_uuid
from research_os.utils.time import now_iso
from research_os.validators.schema_validator import validate_instance

_OPINION_HINTS = ["认为", "预计", "看好", "看空", "建议", "观点", "分析师", "机构称",
                  "点评", "呼吁", "表示"]
_INFERENCE_HINTS = ["影响", "传导", "利好", "利空", "受益", "受损", "或将", "可能影响"]
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)(%|亿|万|元|吨|GW|GWh|MW|台|辆|艘|架|亿元|万元)")


def content_type_of(candidate: CandidateItem) -> str:
    """内容类型（fact_report/opinion/analysis/market_data/unknown）。"""
    text = f"{candidate.title} {candidate.summary}"
    official = candidate.monitoring_channel in (
        "official_disclosure", "government_and_regulator", "company_official", "market_data")
    if official:
        return "fact_report"
    if any(h in text for h in _OPINION_HINTS):
        return "opinion"
    if any(h in text for h in _INFERENCE_HINTS):
        return "analysis"
    return "unknown"


def build_claim(candidate: CandidateItem, evidence_ids: Optional[List[str]] = None,
                conflict_notes: Optional[List[str]] = None) -> Claim:
    """从候选生成一条 Claim（先判定类型，再构造并过 Schema 校验）。"""
    ctype = content_type_of(candidate)
    official = candidate.monitoring_channel in (
        "official_disclosure", "government_and_regulator", "company_official")
    conflict_notes = conflict_notes or []
    if conflict_notes:
        claim_type = "CONFLICT"
    elif ctype == "opinion":
        claim_type = "SOURCE_OPINION"
    elif ctype == "analysis":
        claim_type = "MODEL_INFERENCE"
    elif official and candidate.entities:
        claim_type = "FACT"
    else:
        claim_type = "UNKNOWN"

    statement = candidate.summary or candidate.title
    claim = Claim(
        claim_id=new_uuid(),
        claim_type=claim_type,  # type: ignore[arg-type]
        statement=statement[:500],
        subject_entities=list(candidate.entities),
        predicate="reports" if claim_type == "SOURCE_OPINION" else "describes",
        object={
            "candidate_id": candidate.candidate_id,
            "source_ids": candidate.source_ids,
            "monitoring_channel": candidate.monitoring_channel,
            "conflict_notes": conflict_notes,
        },
        as_of=candidate.published_at,
        evidence_ids=evidence_ids or [],
        support_level="direct" if claim_type == "FACT" else "inferred",
        confidence=0.9 if claim_type == "FACT" else 0.5,
        review_status="unreviewed",
    )
    errs = validate_instance(claim.model_dump(), "claim")
    if errs:
        raise ValueError(f"Claim 未通过 Schema 校验: {errs}")
    return claim


def detect_conflicts(cluster: EventCluster, members: List[CandidateItem]) -> List[str]:
    """簇内冲突检测：关键数值/时间/状态不一致（任务 9.6，不消除冲突）。"""
    from research_os.morning.dedup import _OPPOSITE_PAIRS

    notes: List[str] = []
    numbers: Dict[str, List[str]] = {}
    for m in members:
        text = f"{m.title} {m.summary}"
        for num in _NUMBER_RE.findall(text):
            numbers.setdefault(num[1], set()).add(f"{num[0]}{num[1]}")
    for unit, vals in numbers.items():
        if len(vals) > 1:
            notes.append(f"关键数值不一致（{unit}）: {sorted(vals)}")
    # 时间/状态矛盾词（两两比较；同一簇内不得通过选择解释消除）
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            ta = f"{members[i].title} {members[i].summary}"
            tb = f"{members[j].title} {members[j].summary}"
            for a, b in _OPPOSITE_PAIRS:
                if (a in ta and b in tb) or (b in ta and a in tb):
                    notes.append(f"时间/状态矛盾（{a} vs {b}）")
    statuses = {m.status for m in members}
    if len(statuses) > 1:
        notes.append(f"状态不一致: {sorted(statuses)}")
    return notes
