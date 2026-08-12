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
PROV_DOCUMENT_SOURCE = "document_source"
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

# ---------- R3-10：Strategy Implementation Registry（§75） ----------

SUPPORTED_SCOPE_STRATEGIES = {CTX_SUBJECT, CTX_BENCHMARK, CTX_PEERS, CTX_INDUSTRY,
                              CTX_GLOBAL, CTX_WATCHLIST, CTX_SCENARIO}
SUPPORTED_AUTHORITY_STRATEGIES = {AUTH_SQLITE, AUTH_GRAPH, AUTH_RUN_ARTIFACT, AUTH_INTERNAL}
SUPPORTED_PIT_STRATEGIES = {PIT_AS_OF, PIT_PUBLISHED, PIT_VALID_INTERVAL, PIT_TRADE_DATE,
                            PIT_PUBLICATION_AVAILABILITY, PIT_CLAIM_BUSINESS_TIME}
SUPPORTED_COVERAGE_STRATEGIES = {COV_SINGLETON, COV_ENTITY_SET, COV_PEER_SET, COV_WATCHLIST,
                                 COV_OPEN_WORLD, COV_NOT_APPLICABLE,
                                 "REQUESTED_RUN_SET", "AUTHORITATIVE_TRADING_CALENDAR"}
SUPPORTED_PROVENANCE_STRATEGIES = {PROV_EVIDENCE_TIER, PROV_RAW_SOURCE, PROV_EVIDENCE_IDS,
                                   PROV_DOCUMENT_CHAIN, PROV_DOCUMENT_SOURCE, PROV_MANIFEST,
                                   PROV_INTERNAL, PROV_NOT_APPLICABLE}
SUPPORTED_FRESHNESS_STRATEGIES = {FRESH_PUBLISHED, FRESH_TRADE_DATE, FRESH_UPDATED,
                                  FRESH_OBSERVED, FRESH_SNAPSHOT_AS_OF, FRESH_VALID_FROM,
                                  FRESH_NOT_APPLICABLE, "created_at"}
SUPPORTED_PROJECTION_PREFIXES = ("canonical:", "projection:")


class RuntimeStrategyGate:
    """R3-10：binding strategy ∈ runtime supported strategies（防止 Binding 写名字、
    Runtime 未实现）。"""

    def validate(self, bindings: List["RequirementReadinessBinding"]) -> List[str]:
        violations: List[str] = []
        for b in bindings:
            if b.scope_strategy not in SUPPORTED_SCOPE_STRATEGIES:
                violations.append(f"{b.requirement_id}: scope {b.scope_strategy}")
            if b.authority_strategy not in SUPPORTED_AUTHORITY_STRATEGIES:
                violations.append(f"{b.requirement_id}: authority {b.authority_strategy}")
            if b.pit_strategy not in SUPPORTED_PIT_STRATEGIES:
                violations.append(f"{b.requirement_id}: pit {b.pit_strategy}")
            if b.coverage_strategy not in SUPPORTED_COVERAGE_STRATEGIES:
                violations.append(f"{b.requirement_id}: coverage {b.coverage_strategy}")
            if b.provenance_strategy not in SUPPORTED_PROVENANCE_STRATEGIES:
                violations.append(f"{b.requirement_id}: provenance {b.provenance_strategy}")
            if b.freshness_strategy not in SUPPORTED_FRESHNESS_STRATEGIES:
                violations.append(f"{b.requirement_id}: freshness {b.freshness_strategy}")
            for field, source in b.minimum_field_sources.items():
                if source != "direct" and not source.startswith(SUPPORTED_PROJECTION_PREFIXES):
                    violations.append(f"{b.requirement_id}:{field} projection {source}")
        return violations

    def assert_runtime_supported(self, bindings: List["RequirementReadinessBinding"]) -> None:
        violations = self.validate(bindings)
        if violations:
            raise ValueError(
                f"CONTROL_PLANE_CONFIGURATION_ERROR: runtime strategy 未实现: {violations}")


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
            # §16：statement_scope 是 FinancialFact.statement_scope direct field
            # （严禁 statement_type 投影；consolidated/parent 与 income/balance/cash_flow 不同）
            field_sources["statement_scope"] = "direct"
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
            # §22：symbol 不得从任意 aliases 推断；须可证明 authority（SecurityProfile.symbol）
            field_sources["symbol"] = "projection:entities.symbol_via_security_profile"
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
        # 契约 scope 优先（R2-01 已纠偏）；未知 scope → CONTROL_PLANE_CONFIGURATION_ERROR（§11）
        scope_map = {"global": CTX_GLOBAL, "subject": CTX_SUBJECT,
                     "benchmark": CTX_BENCHMARK, "peers": CTX_PEERS,
                     "industry": CTX_INDUSTRY, "watchlist": CTX_WATCHLIST,
                     "scenario": CTX_SCENARIO}
        strategy = scope_map.get(req.scope.scope_type)
        if strategy is None:
            raise ValueError(
                f"CONTROL_PLANE_CONFIGURATION_ERROR: requirement {req.requirement_id} "
                f"未知 scope strategy {req.scope.scope_type!r}")
        return strategy

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
        if req.data_type == "claims":
            # §33：daily_review.claims 无合法 expected claim universe → OPEN_WORLD（null）
            return COV_OPEN_WORLD
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
        if req.data_type in ("company_profile", "security_profile", "financial_statement_data",
                             "peer_financial_data", "market_valuation_snapshot"):
            return PROV_EVIDENCE_IDS  # evidence_ids / source_ids / source_document（§43）
        if req.data_type in ("company_document", "document_corpus"):
            return PROV_DOCUMENT_SOURCE  # §56：DocumentRecord.source_id → SourceRegistry
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
