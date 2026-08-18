"""DataTypeReadinessSpec（P7-D1-R1）。

22 个 data_type 的显式语义 spec：authority_kind / authority_location /
checker_family / scope_strategy / pit_strategy / provenance_strategy /
coverage_strategy / freshness_strategy / source_tier_applicable。

不新增 JSON Schema（内部 typed spec）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class DataTypeReadinessSpec:
    data_type: str
    authority_kind: str          # sqlite_table / internal / graph / run_artifact
    authority_location: str      # 表名或 internal 标识
    checker_family: str
    scope_strategy: str          # GLOBAL / SUBJECT / INDUSTRY / PEERS / WATCHLIST
    pit_strategy: str            # published_at / trade_date / created_at / valid_interval / not_applicable
    provenance_strategy: str     # evidence_tier / raw_item_source / evidence_ids / internal / not_applicable
    coverage_strategy: str       # SINGLETON_TARGET / REQUESTED_ENTITY_SET / REQUESTED_PEER_SET /
                                 # CONFIGURED_WATCHLIST / OPEN_WORLD / NOT_APPLICABLE
    freshness_strategy: str      # published_at / trade_date / created_at / observed_at / not_applicable
    source_tier_applicable: bool = True
    freshness_seconds: Optional[int] = None


# 22 个 data_type 的权威映射（§14-28）
# authority_location 与 §16 修正一致：claims→claims、security_profile→security_profiles、
# market_valuation_snapshot→valuation_snapshots、company_profile→company_profiles、
# financial→financial_facts、raw item 系→raw_items、evidence→evidence、entities→entities
DATA_TYPE_SPECS: List[DataTypeReadinessSpec] = [
    # ---- raw item 系（共享 raw_items storage，但 semantic eligibility 独立，§21-26）----
    DataTypeReadinessSpec("news_flash", "sqlite_table", "raw_items", "RawItemChecker",
                          "GLOBAL", "published_at", "raw_item_source", "OPEN_WORLD",
                          "published_at", source_tier_applicable=True),
    DataTypeReadinessSpec("company_announcement", "sqlite_table", "raw_items", "RawItemChecker",
                          "GLOBAL", "published_at", "raw_item_source", "OPEN_WORLD",
                          "published_at", source_tier_applicable=True),
    DataTypeReadinessSpec("macro_data", "sqlite_table", "raw_items", "RawItemChecker",
                          "GLOBAL", "published_at", "raw_item_source", "OPEN_WORLD",
                          "published_at", source_tier_applicable=True),
    DataTypeReadinessSpec("brief_event_content", "sqlite_table", "raw_items", "RawItemChecker",
                          "GLOBAL", "published_at", "raw_item_source", "OPEN_WORLD",
                          "published_at", source_tier_applicable=True),
    DataTypeReadinessSpec("brief_attention_content", "sqlite_table", "raw_items", "RawItemChecker",
                          "WATCHLIST", "published_at", "raw_item_source", "CONFIGURED_WATCHLIST",
                          "published_at", source_tier_applicable=True),
    # ---- 主体 profile 系 ----
    DataTypeReadinessSpec("company_profile", "sqlite_table", "company_profiles", "ProfileChecker",
                          "SUBJECT", "valid_interval", "evidence_ids", "SINGLETON_TARGET",
                          "valid_from", source_tier_applicable=True),
    DataTypeReadinessSpec("security_profile", "sqlite_table", "security_profiles", "ProfileChecker",
                          "SUBJECT", "valid_interval", "evidence_ids", "SINGLETON_TARGET",
                          "valid_from", source_tier_applicable=True),
    DataTypeReadinessSpec("industry_membership", "sqlite_table", "company_profiles", "IndustryMembershipChecker",
                          "INDUSTRY", "valid_interval", "evidence_ids", "REQUESTED_ENTITY_SET",
                          "valid_from", source_tier_applicable=True),
    DataTypeReadinessSpec("entity_mapping", "sqlite_table", "entities", "EntityMappingChecker",
                          "GLOBAL", "valid_interval", "internal", "NOT_APPLICABLE",
                          "not_applicable", source_tier_applicable=False),
    # ---- 财务 / 估值系 ----
    DataTypeReadinessSpec("financial_statement_data", "sqlite_table", "financial_facts", "FinancialChecker",
                          "SUBJECT", "publication_availability", "evidence_ids", "SINGLETON_TARGET",
                          "observed_at", source_tier_applicable=True),
    DataTypeReadinessSpec("peer_financial_data", "sqlite_table", "financial_facts", "FinancialChecker",
                          "PEERS", "publication_availability", "evidence_ids", "REQUESTED_PEER_SET",
                          "observed_at", source_tier_applicable=True),
    DataTypeReadinessSpec("market_valuation_snapshot", "sqlite_table", "valuation_snapshots", "ValuationChecker",
                          "SUBJECT", "as_of", "evidence_ids", "SINGLETON_TARGET",
                          "as_of", source_tier_applicable=True),
    # ---- 文档 ----
    DataTypeReadinessSpec("company_document", "sqlite_table", "document_records", "DocumentChecker",
                          "SUBJECT", "published_at", "document_source", "SINGLETON_TARGET",
                          "published_at", source_tier_applicable=True),
    DataTypeReadinessSpec("document_corpus", "sqlite_table", "document_records", "DocumentChecker",
                          "GLOBAL", "published_at", "document_source", "OPEN_WORLD",
                          "published_at", source_tier_applicable=True),
    # ---- evidence / claims / findings（内部权威，但 tier 经 provenance）----
    DataTypeReadinessSpec("evidence", "sqlite_table", "evidence", "EvidenceContentChecker",
                          "GLOBAL", "published_at", "evidence_tier", "OPEN_WORLD",
                          "published_at", source_tier_applicable=True),
    DataTypeReadinessSpec("claims", "sqlite_table", "claims", "ClaimsChecker",
                          "SUBJECT", "as_of", "evidence_ids", "SINGLETON_TARGET",
                          "not_applicable", source_tier_applicable=True),
    DataTypeReadinessSpec("event_evidence", "sqlite_table", "evidence", "EvidenceContentChecker",
                          "SUBJECT", "published_at", "evidence_tier", "SINGLETON_TARGET",
                          "published_at", source_tier_applicable=True),
    DataTypeReadinessSpec("evidence_index", "sqlite_table", "evidence", "EvidenceContentChecker",
                          "GLOBAL", "published_at", "evidence_tier", "OPEN_WORLD",
                          "published_at", source_tier_applicable=True),
    DataTypeReadinessSpec("research_findings", "sqlite_table", "research_findings", "ResearchFindingsChecker",
                          "SUBJECT", "created_at", "evidence_ids", "SINGLETON_TARGET",
                          "created_at", source_tier_applicable=True),
    # ---- market / graph / run artifacts ----
    DataTypeReadinessSpec("market_daily_ohlcv", "sqlite_table", "market_daily_ohlcv", "MarketSeriesChecker",
                          "SUBJECT", "trade_date", "manifest", "AUTHORITATIVE_TRADING_CALENDAR",
                          "trade_date", source_tier_applicable=True),
    DataTypeReadinessSpec("knowledge_graph_snapshot", "graph", "graph", "GraphSnapshotChecker",
                          "INDUSTRY", "as_of", "internal", "NOT_APPLICABLE",
                          "not_applicable", source_tier_applicable=False),
    DataTypeReadinessSpec("run_artifacts", "run_artifact", "runs_root", "RunArtifactChecker",
                          "GLOBAL", "created_at", "internal", "NOT_APPLICABLE",
                          "not_applicable", source_tier_applicable=False),
]

_SPECS_BY_TYPE = {s.data_type: s for s in DATA_TYPE_SPECS}


def get_spec(data_type: str) -> DataTypeReadinessSpec:
    try:
        return _SPECS_BY_TYPE[data_type]
    except KeyError as exc:
        raise ValueError(
            f"CONTROL_PLANE_CONFIGURATION_ERROR: data_type {data_type!r} 无 DataTypeReadinessSpec"
        ) from exc


def has_spec(data_type: str) -> bool:
    return data_type in _SPECS_BY_TYPE


def all_specs() -> List[DataTypeReadinessSpec]:
    return list(DATA_TYPE_SPECS)
