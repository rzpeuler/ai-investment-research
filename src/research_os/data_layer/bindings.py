"""RequirementReadinessBinding（P7-D1-R2）。

ScenarioDataRequirement + DataTypeReadinessSpec → effective runtime semantics。

43/43 binding gate：每个 requirement 必须恰好一个 effective binding；
不允许同一 data_type 在所有 scenario 下假设语义完全相同（如 industry_membership
在 stock_research_report 与 industry_research 的 scope/coverage 不同）。

不新增 JSON Schema（内部 typed binding）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from research_os.data_layer.specs import DataTypeReadinessSpec, get_spec
from research_os.models import ScenarioDataRequirement
from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry

# 策略值常量
CTX_SUBJECT = "subject"
CTX_BENCHMARK = "benchmark"
CTX_PEERS = "peers"
CTX_INDUSTRY = "industry"
CTX_GLOBAL = "global"
CTX_WATCHLIST = "watchlist"
CTX_SCENARIO = "scenario"

AUTH_SQLITE = "sqlite_table"
AUTH_GRAPH = "graph"
AUTH_RUN_ARTIFACT = "run_artifact"
AUTH_INTERNAL = "internal"

PIT_AS_OF = "as_of"
PIT_PUBLISHED = "published_at"
PIT_VALID_INTERVAL = "valid_interval"
PIT_TRADE_DATE = "trade_date"
PIT_PUBLICATION_AVAILABILITY = "publication_availability"
PIT_CLAIM_BUSINESS_TIME = "claim_as_of"

COV_SINGLETON = "SINGLETON_TARGET"
COV_ENTITY_SET = "REQUESTED_ENTITY_SET"
COV_PEER_SET = "REQUESTED_PEER_SET"
COV_WATCHLIST = "CONFIGURED_WATCHLIST"
COV_OPEN_WORLD = "OPEN_WORLD"
COV_NOT_APPLICABLE = "NOT_APPLICABLE"

PROV_EVIDENCE_TIER = "evidence_tier"
PROV_RAW_SOURCE = "raw_item_source"
PROV_EVIDENCE_IDS = "evidence_ids"
PROV_DOCUMENT_CHAIN = "document_chain"
PROV_MANIFEST = "manifest"
PROV_INTERNAL = "internal"
PROV_NOT_APPLICABLE = "not_applicable"

FRESH_PUBLISHED = "published_at"
FRESH_TRADE_DATE = "trade_date"
FRESH_UPDATED = "updated_at"
FRESH_OBSERVED = "observed_at"
FRESH_SNAPSHOT_AS_OF = "snapshot_as_of"
FRESH_VALID_FROM = "valid_from"
FRESH_NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class RequirementReadinessBinding:
    requirement_id: str
    scenario: str
    data_type: str
    spec: DataTypeReadinessSpec
    context_strategy: str
    authority_strategy: str
    authority_location: str
    scope_strategy: str
    pit_strategy: str
    field_projection_strategy: str
    provenance_strategy: str
    coverage_strategy: str
    freshness_strategy: str
    source_tier_applicable: bool
    # minimum_fields → canonical projection 来源（direct=authority 字段 / projection=确定性投影）
    minimum_field_sources: Dict[str, str] = field(default_factory=dict)


class RequirementReadinessBindingResolver:
    """按 scenario+data_type 解析 effective binding（43/43）。"""

    def __init__(self, requirement_registry: ScenarioDataRequirementRegistry):
        self._requirements = requirement_registry
        self._bindings: Dict[str, RequirementReadinessBinding] = {}
        self._build_all()

    def _build_all(self) -> None:
        for req in self._requirements.all():
            binding = self._bind(req)
            self._bindings[req.requirement_id] = binding

    def get(self, requirement_id: str) -> RequirementReadinessBinding:
        try:
            return self._bindings[requirement_id]
        except KeyError as exc:
            raise ValueError(
                f"CONTROL_PLANE_CONFIGURATION_ERROR: requirement {requirement_id!r} 无 binding"
            ) from exc

    def all(self) -> List[RequirementReadinessBinding]:
        return [self._bindings[k] for k in self._requirement_order()]

    def _requirement_order(self) -> List[str]:
        return [r.requirement_id for r in self._requirements.all()]

    # ---------- binding 构造 ----------

    def _bind(self, req: ScenarioDataRequirement) -> RequirementReadinessBinding:
        spec = get_spec(req.data_type)
        scope_strategy = self._scope_strategy(req, spec)
        pit_strategy = self._pit_strategy(req, spec)
        cov_strategy = self._coverage_strategy(req, spec)
        prov_strategy = self._provenance_strategy(req, spec)
        fresh_strategy = self._freshness_strategy(req, spec)
        context_strategy = scope_strategy  # context 由 scope 决定（global→global 等）

        # 默认 minimum_field 直接来自 authority 对象字段（field closure gate 会校验）
        field_sources = {f: "direct" for f in req.minimum_fields}
        # 已知 canonical projection（§10）
        if req.data_type == "financial_statement_data":
            field_sources["value"] = "canonical:financial_value"
            field_sources["statement_scope"] = "projection:financial_facts.statement_type"
        if req.data_type == "peer_financial_data":
            field_sources["value"] = "canonical:financial_value"
        if req.data_type == "industry_membership":
            if "industry_id" in field_sources:
                field_sources["industry_id"] = "projection:company_profile.industry_ids"
        if req.data_type == "macro_data" and "publish_date" in field_sources:
            field_sources["publish_date"] = "projection:date(published_at)"
        if req.data_type == "company_announcement" and "company" in field_sources:
            field_sources["company"] = "projection:raw_item.company_entity"
        if req.data_type in ("evidence", "event_evidence", "evidence_index"):
            if "source_ref" in field_sources:
                field_sources["source_ref"] = "projection:evidence.source_id"
        if req.data_type == "entity_mapping" and "symbol" in field_sources:
            field_sources["symbol"] = "projection:entities.symbol_or_alias"
        if req.data_type == "knowledge_graph_snapshot":
            for f in ("node_refs", "edge_refs"):
                if f in field_sources:
                    field_sources[f] = "projection:graph_query_result"
            if "industry_id" in field_sources:
                field_sources["industry_id"] = "projection:graph_industry_context"
        if req.data_type == "run_artifacts":
            for f in ("task_id", "run_id"):
                if f in field_sources:
                    field_sources[f] = "projection:artifact_lineage"

        return RequirementReadinessBinding(
            requirement_id=req.requirement_id,
            scenario=req.scenario,
            data_type=req.data_type,
            spec=spec,
            context_strategy=context_strategy,
            authority_strategy=spec.authority_kind,
            authority_location=spec.authority_location,
            scope_strategy=scope_strategy,
            pit_strategy=pit_strategy,
            field_projection_strategy=spec.checker_family,
            provenance_strategy=prov_strategy,
            coverage_strategy=cov_strategy,
            freshness_strategy=fresh_strategy,
            source_tier_applicable=self._tier_applicable(req, spec),
            minimum_field_sources=field_sources,
        )

    # ---------- 策略解析（scenario 相关覆盖） ----------

    def _scope_strategy(self, req, spec) -> str:
        # 契约 scope 优先（R2-01 已纠偏）
        scope_map = {"global": CTX_GLOBAL, "subject": CTX_SUBJECT,
                     "benchmark": CTX_BENCHMARK, "peers": CTX_PEERS,
                     "industry": CTX_INDUSTRY, "watchlist": CTX_WATCHLIST,
                     "scenario": CTX_SCENARIO}
        return scope_map.get(req.scope.scope_type, CTX_GLOBAL)

    def _pit_strategy(self, req, spec) -> str:
        if req.point_in_time_policy == "strict_as_of":
            if req.data_type in ("company_profile", "security_profile", "industry_membership",
                                 "entity_mapping"):
                return PIT_VALID_INTERVAL
            if req.data_type == "financial_statement_data" or req.data_type == "peer_financial_data":
                return PIT_PUBLICATION_AVAILABILITY
            if req.data_type == "market_daily_ohlcv":
                return PIT_TRADE_DATE
            if req.data_type == "knowledge_graph_snapshot":
                return PIT_AS_OF
            return PIT_AS_OF
        if req.point_in_time_policy == "window_bounded":
            if req.data_type == "claims":
                return PIT_CLAIM_BUSINESS_TIME
            return PIT_PUBLISHED
        return PIT_AS_OF

    def _coverage_strategy(self, req, spec) -> str:
        # scenario 覆盖：industry_membership 在 stock_research_report（subject）→ singleton；
        # 在 industry_research/theme_discovery（industry 无完整成员全集）→ open-world null
        if req.data_type == "industry_membership":
            if req.scope.scope_type == "subject":
                return COV_SINGLETON
            return COV_OPEN_WORLD
        if req.data_type == "financial_statement_data":
            return COV_SINGLETON  # 无合法 fact universe → null（checker 处理）
        if req.data_type == "peer_financial_data":
            return COV_PEER_SET
        return spec.coverage_strategy

    def _provenance_strategy(self, req, spec) -> str:
        # Evidence 系必须用 evidence_tier（§40）
        if req.data_type in ("evidence", "event_evidence", "evidence_index"):
            return PROV_EVIDENCE_TIER
        if req.data_type == "claims":
            return PROV_EVIDENCE_IDS  # Claim tier via Evidence（§41）
        if req.data_type == "research_findings":
            return PROV_EVIDENCE_IDS  # §42
        if req.data_type == "market_daily_ohlcv":
            return PROV_MANIFEST  # §44：bar via accepted manifest → source_id → tier
        if req.data_type in ("company_profile", "security_profile", "company_document",
                             "document_corpus", "financial_statement_data",
                             "peer_financial_data", "market_valuation_snapshot"):
            return PROV_EVIDENCE_IDS  # evidence_ids / source_ids / source_document（§43）
        return spec.provenance_strategy

    def _freshness_strategy(self, req, spec) -> str:
        if req.data_type == "security_profile":
            return FRESH_UPDATED  # §26：listing_date 不代表 freshness，用 updated_at
        if req.data_type == "market_valuation_snapshot":
            return FRESH_SNAPSHOT_AS_OF  # §65
        if req.data_type == "financial_statement_data" or req.data_type == "peer_financial_data":
            return FRESH_OBSERVED
        if req.data_type == "company_profile":
            return FRESH_VALID_FROM
        return spec.freshness_strategy

    def _tier_applicable(self, req, spec) -> bool:
        # 内部 authority 明确跳过（Graph snapshot / run artifact lineage / entity mapping）
        # claims/research_findings tier 经 evidence_ids provenance（spec source_tier_applicable=True）
        if req.data_type in ("knowledge_graph_snapshot", "run_artifacts",
                             "entity_mapping"):
            return False
        return spec.source_tier_applicable
