"""ReadinessFieldProjector + Minimum Field Closure Gate（P7-D1-R2）。

projection != new authority：只用于判断 Requirement 是否满足，不回写原对象。
禁止 LLM / 模糊 alias 猜测。

closure gate：43 个 requirement 每个 minimum_field 必须属于：
A. authority object direct field，或
B. explicit deterministic canonical projection
否则 CONTROL_PLANE_CONFIGURATION_ERROR（不能等到运行时永远显示 missing）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from research_os.data_layer.bindings import RequirementReadinessBinding
from research_os.models import ScenarioDataRequirement

# 各 authority 对象的已知字段集（用于 closure gate 判定 direct field）
AUTHORITY_DIRECT_FIELDS: Dict[str, Set[str]] = {
    "raw_items": {"raw_item_id", "source_id", "url", "title", "publisher", "published_at",
                  "content_hash", "content_excerpt", "entities", "raw_category"},
    "claims": {"claim_id", "claim_type", "statement", "subject_entities", "predicate",
               "object", "as_of", "evidence_ids", "support_level", "confidence"},
    "company_profiles": {"company_profile_id", "entity_id", "canonical_name", "industry_ids",
                         "fiscal_year_end", "reporting_currency", "valid_from", "valid_to",
                         "source_ids", "evidence_ids", "status"},
    "security_profiles": {"security_profile_id", "security_entity_id", "company_entity_id",
                          "symbol", "exchange", "security_type", "listing_date", "delisting_date",
                          "current_name", "source_ids", "evidence_ids", "status", "updated_at"},
    "financial_facts": {"fact_id", "fact_key", "company_entity_id", "statement_type",
                        "taxonomy_code", "period_end", "raw_value", "normalized_value",
                        "value_status", "statement_scope", "source_document_id", "evidence_ids"},
    "valuation_snapshots": {"valuation_snapshot_id", "company_entity_id", "security_entity_id",
                            "as_of", "price", "market_cap", "enterprise_value", "metrics",
                            "peer_selection_id", "percentile_method", "source_ids", "evidence_ids",
                            "status", "shares_outstanding"},
    "document_records": {"document_id", "company_entity_id", "security_entity_id", "document_type",
                         "title", "source_id", "published_at", "sha256", "parse_status"},
    "evidence": {"evidence_id", "source_id", "raw_item_id", "title", "published_at", "url",
                 "excerpt", "evidence_type", "independence_group", "source_tier"},
    "entities": {"entity_id", "entity_type", "canonical_name", "aliases", "market",
                 "industry_ids", "valid_from", "valid_to", "source_ids"},
    "research_findings": {"finding_id", "finding_type", "company_entity_id", "evidence_ids",
                          "created_at", "summary"},
    "market_daily_ohlcv": {"bar_id", "symbol", "trade_date", "open", "high", "low", "close",
                           "volume"},
    "graph": {"node_refs", "edge_refs", "as_of", "industry_id"},
    "runs_root": {"task_id", "run_id"},
}

# canonical projection 标记（binding.minimum_field_sources 中的值以 "canonical:" / "projection:" 开头）
CANONICAL_PREFIXES = ("canonical:", "projection:")


# ---------- R3.1-07：Projection Handler Table（§56） ----------
# 与 bindings.SUPPORTED_PROJECTION_STRATEGIES 机械一致的唯一 capability declaration。
# closure 测试断言：PROJECTION_HANDLERS.keys() == SUPPORTED_PROJECTION_STRATEGIES。
PROJECTION_HANDLERS: Dict[str, str] = {
    "canonical:financial_value": "financial_value",
    "projection:company_profile.industry_ids": "industry_membership",
    "projection:date(published_at)": "date_published",
    "projection:raw_item.company_entity": "company_subject",
    "projection:evidence.source_id": "evidence_source",
    "projection:entities.symbol_via_security_profile": "symbol_security_profile",
    "projection:graph_query_result": "graph_query",
    "projection:graph_industry_context": "graph_industry",
    "projection:artifact_lineage": "artifact_lineage",
}


class ReadinessFieldProjector:
    """确定性 canonical field projection（只读，不回写）。"""

    def has_field(self, payload: Dict[str, Any], field: str, source: str,
                  context: Dict[str, Any]) -> bool:
        """判断 payload 是否满足某 minimum_field。

        source == "direct" → 直接字段存在（非 None）
        其余 source 必须 ∈ SUPPORTED_PROJECTION_STRATEGIES（exact，禁止前缀匹配，§51）；
        未知 source → CONTROL_PLANE_CONFIGURATION_ERROR。
        """
        if source == "direct":
            return payload.get(field) is not None
        handler = PROJECTION_HANDLERS.get(source)
        if handler is None:
            # 未知 projection → CONTROL_PLANE_CONFIGURATION_ERROR（§24，不得伪装成普通 missing field）
            raise ValueError(
                f"CONTROL_PLANE_CONFIGURATION_ERROR: 未知 projection source {source!r}")
        if handler == "financial_value":
            return self._financial_value_exists(payload)
        if handler == "industry_membership":
            return self._industry_membership_exists(payload, context)
        if handler == "date_published":
            return payload.get("published_at") is not None
        if handler == "company_subject":
            return self._company_subject_exists(payload)
        if handler in ("graph_query", "graph_industry"):
            # graph result 由 checker 填充到 payload/context
            return payload.get(field) is not None or context.get(field) is not None
        if handler == "artifact_lineage":
            return payload.get(field) is not None or context.get(field) is not None
        if handler == "evidence_source":
            return payload.get("source_id") is not None
        if handler == "symbol_security_profile":
            # §22：symbol 必须来自可证明 authority 字段（entity.symbol / entity.security_symbol），
            # 不得用通用 aliases 冒充证券代码。
            symbol = payload.get("symbol") or payload.get("security_symbol")
            return symbol is not None
        return False

    # ---------- 具体投影 ----------

    def _financial_value_exists(self, payload: Dict[str, Any]) -> bool:
        """canonical value exists IFF value_status ∈ {reported, derived_from_report}
        AND (normalized_value != null OR raw_value != null)。优先 normalized_value。"""
        status = payload.get("value_status")
        if status not in ("reported", "derived_from_report"):
            return False
        return payload.get("normalized_value") is not None or payload.get("raw_value") is not None

    def _industry_membership_exists(self, payload: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """industry_id 投影必须来自 actual matching industry_ids membership（不得取第一项冒充）。"""
        requested = set(context.get("industry_ids") or [])
        if not requested:
            return False
        ids = payload.get("industry_ids") or []
        if isinstance(ids, str):
            ids = [ids]
        return bool(requested & {str(i) for i in ids})

    def _company_subject_exists(self, payload: Dict[str, Any]) -> bool:
        """company 只能在 RawItem 正式实体关系中存在可确定 company subject 时投影。"""
        entities = payload.get("entities") or []
        if isinstance(entities, str):
            entities = [entities]
        return any(str(e).startswith("company:") for e in entities)


class MinimumFieldClosureValidator:
    """43/43 minimum-field semantic closure gate（§8）。"""

    def __init__(self, bindings: List[RequirementReadinessBinding]):
        self._bindings = bindings

    def validate(self) -> List[str]:
        """返回全部 closure 违规 requirement_id；空 = 通过。"""
        from research_os.data_layer.bindings import SUPPORTED_PROJECTION_STRATEGIES
        violations: List[str] = []
        for binding in self._bindings:
            authority_fields = AUTHORITY_DIRECT_FIELDS.get(binding.authority_location, set())
            for field, source in binding.minimum_field_sources.items():
                if source == "direct":
                    if field not in authority_fields:
                        violations.append(
                            f"{binding.requirement_id}:{field} 非 {binding.authority_location} direct field"
                        )
                elif source not in SUPPORTED_PROJECTION_STRATEGIES:
                    # R3.1-07：projection 必须 exact ∈ 已实现策略 registry（§54）
                    violations.append(
                        f"{binding.requirement_id}:{field} 无已实现 projection source {source}"
                    )
        return violations

    def assert_closure(self) -> None:
        violations = self.validate()
        if violations:
            raise ValueError(
                f"CONTROL_PLANE_CONFIGURATION_ERROR: minimum-field closure 违规: {violations}")
