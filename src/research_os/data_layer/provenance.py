"""ReadinessProvenanceResolver（P7-D1-R1）。

把领域对象的既有 provenance 解析为来源 tier（S > A > B > C > D）。
严格：READ ONLY / DETERMINISTIC / ZERO NETWORK / ZERO LLM。

禁止从领域 payload 直接读伪造的 source_tier/tier 字段（§29/32）；
tier 必须来自既有治理 authority（sources.yaml / Evidence.source_tier）。

优先级（§31）：
- Evidence: evidence.source_tier
- RawItem: raw_item.source_id → sources.yaml source_tier
- Profile / Document / FinancialFact / ValuationSnapshot:
  evidence_ids → Evidence.source_tier；或 source_ids → sources.yaml
- 无法 dereference → SOURCE_TIER_UNPROVEN（quality ineligible）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from research_os.data_layer.constants import SOURCE_TIER_UNPROVEN
from research_os.routing.requirements import DataRequirementRegistry
from research_os.source_registry.registry import SourceRegistry

_TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}


class ReadinessProvenanceResolver:
    """把领域对象 provenance 解析为 tier（复用既有治理，禁止第二套 tier registry）。"""

    def __init__(
        self,
        sources_yaml_path: Optional[str] = None,
        data_requirements_path: Optional[str] = None,
    ):
        self._source_registry: Optional[SourceRegistry] = None
        self._data_requirements: Optional[DataRequirementRegistry] = None
        if sources_yaml_path:
            self._source_registry = SourceRegistry(sources_yaml_path)
        if data_requirements_path:
            self._data_requirements = DataRequirementRegistry(data_requirements_path)

    # ---------- 主入口 ----------

    def resolve(
        self,
        payload: Dict[str, Any],
        strategy: str,
        view: Any,
    ) -> Tuple[Optional[str], Optional[str]]:
        """返回 (tier 或 None, warning 或 None)。

        tier=None 且 warning=SOURCE_TIER_UNPROVEN → quality ineligible。
        strategy ∈ {evidence_tier, raw_item_source, evidence_ids, internal, not_applicable}
        """
        if strategy in ("internal", "not_applicable"):
            return None, None
        if strategy == "evidence_tier":
            return self._from_evidence_tier(payload)
        if strategy == "raw_item_source":
            return self._from_raw_item_source(payload, view)
        if strategy == "evidence_ids":
            return self._from_evidence_ids(payload, view)
        if strategy == "manifest":
            return self._from_manifest(payload, view)
        if strategy == "document_source":
            return self._from_document_source(payload)
        return None, SOURCE_TIER_UNPROVEN

    # ---------- 各策略 ----------

    def _from_evidence_tier(self, payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        tier = payload.get("source_tier") or payload.get("tier")
        if tier is not None and str(tier) in _TIER_ORDER:
            return str(tier), None
        return None, SOURCE_TIER_UNPROVEN

    def _from_raw_item_source(
        self, payload: Dict[str, Any], view: Any,
    ) -> Tuple[Optional[str], Optional[str]]:
        source_id = payload.get("source_id")
        if not source_id:
            return None, SOURCE_TIER_UNPROVEN
        tier = self._source_tier_from_governance(source_id)
        if tier:
            return tier, None
        return None, SOURCE_TIER_UNPROVEN

    def _from_evidence_ids(
        self, payload: Dict[str, Any], view: Any,
    ) -> Tuple[Optional[str], Optional[str]]:
        evidence_ids = payload.get("evidence_ids") or []
        source_ids = payload.get("source_ids") or []
        # §43：FinancialFact 若只有 source_document_id → Document → Evidence/source provenance
        source_document_id = payload.get("source_document_id")
        if evidence_ids:
            tiers = []
            for eid in evidence_ids:
                row = self._fetch_evidence(view, str(eid))
                if row is None:
                    continue
                tier = row.get("source_tier") or row.get("tier")
                if tier is not None and str(tier) in _TIER_ORDER:
                    tiers.append(str(tier))
            if tiers:
                # 保守：取最低 tier（最弱 provenance 决定；D 最弱）
                return max(tiers, key=lambda t: _TIER_ORDER[t]), None
        if source_ids:
            tiers = []
            for sid in source_ids:
                tier = self._source_tier_from_governance(str(sid))
                if tier:
                    tiers.append(tier)
            if tiers:
                return max(tiers, key=lambda t: _TIER_ORDER[t]), None
        if source_document_id:
            doc_row = self._fetch_document(view, str(source_document_id))
            if doc_row is not None:
                # document → 其 evidence/source 链
                doc_tier, _ = self._from_evidence_ids(doc_row, view)
                if doc_tier:
                    return doc_tier, None
                doc_source = doc_row.get("source_id")
                if doc_source:
                    tier = self._source_tier_from_governance(str(doc_source))
                    if tier:
                        return tier, None
        return None, SOURCE_TIER_UNPROVEN

    def _from_document_source(self, payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """§56-57：DocumentRecord.source_id → SourceRegistry → source_tier。

        DocumentRecord 正式对象无 evidence_ids；source_id 是权威 provenance。
        """
        source_id = payload.get("source_id")
        if not source_id:
            return None, SOURCE_TIER_UNPROVEN
        tier = self._source_tier_from_governance(str(source_id))
        if tier:
            return tier, None
        return None, SOURCE_TIER_UNPROVEN

    def _from_manifest(self, payload: Dict[str, Any], view: Any) -> Tuple[Optional[str], Optional[str]]:
        """§44：market bar → accepted manifest（覆盖 symbol/date）→ source_id → SourceRegistry tier。

        无匹配 accepted manifest → SOURCE_TIER_UNPROVEN（不得假定市场表天生 Tier B）。
        """
        has_table = getattr(view, "has_table", None)
        if has_table is None or not has_table("market_daily_series_manifests"):
            return None, SOURCE_TIER_UNPROVEN
        symbol = payload.get("symbol")
        trade_date = payload.get("trade_date")
        if not symbol or not trade_date:
            return None, SOURCE_TIER_UNPROVEN
        try:
            rows = view.query(
                "SELECT m.payload FROM market_daily_series_manifests m "
                "WHERE m.validation_status = 'accepted' "
                "AND m.date_start <= ? AND m.date_end >= ? "
                "AND EXISTS (SELECT 1 FROM json_each(json_extract(m.payload, '$.symbols')) "
                "            WHERE json_each.value = ?)",
                (trade_date, trade_date, symbol),
            )
        except Exception:  # noqa: BLE001
            return None, SOURCE_TIER_UNPROVEN
        tiers: List[str] = []
        for row in rows:
            m = row["payload"]
            if isinstance(m, str):
                import json as _json
                try:
                    m = _json.loads(m)
                except (TypeError, ValueError):
                    continue
            if not isinstance(m, dict):
                continue
            source_id = m.get("source_id")
            if not source_id:
                continue
            tier = self._source_tier_from_governance(str(source_id))
            if tier:
                tiers.append(tier)
        if tiers:
            return max(tiers, key=lambda t: _TIER_ORDER[t]), None
        return None, SOURCE_TIER_UNPROVEN

    # ---------- helpers ----------

    def _source_tier_from_governance(self, source_id: str) -> Optional[str]:
        if self._source_registry is not None:
            try:
                source = self._source_registry.get(source_id)
                if source is not None:
                    tier = getattr(source, "source_tier", None)
                    if tier is not None and str(tier) in _TIER_ORDER:
                        return str(tier)
            except Exception:  # noqa: BLE001
                pass
        # 兜底：sources.yaml 只读 fallback（不创建第二套 tier registry）
        return None

    def _fetch_evidence(self, view: Any, evidence_id: str) -> Optional[Dict[str, Any]]:
        has_table = getattr(view, "has_table", None)
        if has_table is None or not has_table("evidence"):
            return None
        try:
            rows = view.query(
                "SELECT payload FROM evidence WHERE json_extract(payload, '$.evidence_id') = ?",
                (evidence_id,),
            )
        except Exception:  # noqa: BLE001
            return None
        if not rows:
            return None
        payload = rows[0]["payload"]
        if isinstance(payload, str):
            import json
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None

    def _fetch_document(self, view: Any, document_id: str) -> Optional[Dict[str, Any]]:
        has_table = getattr(view, "has_table", None)
        if has_table is None or not has_table("document_records"):
            return None
        try:
            rows = view.query(
                "SELECT payload FROM document_records "
                "WHERE json_extract(payload, '$.document_id') = ?",
                (document_id,),
            )
        except Exception:  # noqa: BLE001
            return None
        if not rows:
            return None
        payload = rows[0]["payload"]
        if isinstance(payload, str):
            import json
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None
