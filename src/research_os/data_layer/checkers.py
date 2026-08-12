"""ReadinessCheckerRegistry 与 checker families（P7-D1-R1）。

每个 data_type 必须有 checker（22/22）+ 显式 DataTypeReadinessSpec（22/22）；
缺任一 → CONTROL_PLANE_CONFIGURATION_ERROR（fail closed），不得返回 MISSING。

R1 语义修正：
- authority 表映射按 specs（claims→claims、security_profile→security_profiles、
  market_valuation_snapshot→valuation_snapshots、company_profile→company_profiles）
- RawItem 系共享 raw_items 但 semantic eligibility 独立（raw_category/source 约束）
- coverage 策略显式声明；open-world 恒 null；禁止工作日≈交易日
- freshness_seconds 真正执行（STALE）
- provenance 由 ReadinessProvenanceResolver 解析（禁止 payload.source_tier 通用伪造）

判定顺序（§87）：1 Scope → 2 PIT → 3 Required Fields → 4 Coverage → 5 Provenance/Tier
→ 6 Freshness → 7 Source Health → 8 Final Status

只读、零网络、零写入、零 LLM。
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from research_os.data_layer.constants import (
    COVERAGE_BELOW_MINIMUM,
    COVERAGE_NOT_MEASURABLE,
    FRESHNESS_UNPROVEN,
    GRAPH_SCOPE_UNRESOLVED,
    MISSING_REQUIRED_FIELDS,
    NO_ELIGIBLE_RECORDS,
    PIT_INELIGIBLE,
    RAW_TYPE_INELIGIBLE,
    REQUEST_MATERIAL_PENDING_NORMALIZATION,
    SCOPE_MISMATCH,
    SOURCE_HEALTH_UNPROVEN,
    SOURCE_TIER_BELOW_MINIMUM,
    SOURCE_TIER_UNPROVEN,
    STALE_DATA,
)
from research_os.data_layer.context import ResolvedRequirementContext
from research_os.data_layer.provenance import ReadinessProvenanceResolver
from research_os.data_layer.specs import DataTypeReadinessSpec, get_spec
from research_os.models import ScenarioDataRequirement

# ---------- 标准化 reason / warning 常量（§40） ----------

_TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}

_STATUS_ORDER = ["READY", "PARTIAL", "MISSING", "STALE", "SOURCE_UNHEALTHY"]


@dataclass
class ReadinessCheckResult:
    """内部判定结果（转成 DataReadiness 由 DataReadinessService 完成）。"""

    status: str  # READY / PARTIAL / MISSING / STALE / SOURCE_UNHEALTHY
    available_fields: List[str] = field(default_factory=list)
    coverage_ratio: Optional[float] = None
    eligible_record_count: int = 0
    ineligible_record_count: int = 0
    source_tiers_present: List[str] = field(default_factory=list)
    record_refs: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    freshness_age_seconds: Optional[int] = None


class DataReadView(ABC):
    """只读数据访问抽象：Production=SQLite read；Dry-run=empty/no-data。"""

    @abstractmethod
    def query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def has_table(self, table: str) -> bool:
        ...


class SqliteReadView(DataReadView):
    """SQLite 只读视图（mode=ro 或普通连接，只执行 SELECT）。"""

    def __init__(self, db: Any):
        self._db = db

    def query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        if not sql.lstrip().upper().startswith("SELECT"):
            raise ValueError("ReadView 只允许只读查询")
        return self._db.query(sql, params)

    def has_table(self, table: str) -> bool:
        try:
            row = self._db.query(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
        except Exception:  # noqa: BLE001
            return False
        return bool(row)


class EmptyReadView(DataReadView):
    """空 read view：DB 不存在时使用（不创建 DB、不初始化）。"""

    def query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        return []

    def has_table(self, table: str) -> bool:
        return False


# ---------- checker families（§20，按 spec 驱动） ----------

class ReadinessChecker(ABC):
    """checker 家族基类。data_types 声明支持的 data_type 集合。"""

    data_types: Tuple[str, ...] = ()

    @abstractmethod
    def check(
        self,
        ctx: ResolvedRequirementContext,
        requirement: ScenarioDataRequirement,
        view: DataReadView,
        provenance: ReadinessProvenanceResolver,
    ) -> ReadinessCheckResult:
        ...

    # ---------- 通用工具 ----------

    def _scope_eligible(
        self,
        payload: Dict[str, Any],
        ctx: ResolvedRequirementContext,
        scope_payload_keys: Tuple[str, ...] = ("symbol", "company_entity_id",
                                               "security_entity_id", "entity_id",
                                               "subject"),
        industry_payload_keys: Tuple[str, ...] = ("industry_ids", "industry_id"),
    ) -> bool:
        """subject / industry / peers scope 精确匹配（fail closed）；不匹配 → ineligible。"""
        scope_type = ctx.requirement.scope.scope_type
        if scope_type == "global":
            return True
        if scope_type in ("subject", "benchmark"):
            if not ctx.entity_ids:
                return False
            values: List[str] = []
            for key in scope_payload_keys:
                v = payload.get(key)
                if v is None:
                    continue
                values.extend(v if isinstance(v, list) else [v])
            if not values:
                return False
            return any(str(v) in ctx.entity_ids for v in values)
        if scope_type == "industry":
            if not ctx.industry_ids:
                return False
            values = []
            for key in industry_payload_keys:
                v = payload.get(key)
                if v is None:
                    continue
                values.extend(v if isinstance(v, list) else [v])
            if not values:
                return False
            return any(str(v) in ctx.industry_ids for v in values)
        if scope_type == "peers":
            if not ctx.peer_entity_ids:
                return False
            values = []
            for key in scope_payload_keys:
                v = payload.get(key)
                if v is None:
                    continue
                values.extend(v if isinstance(v, list) else [v])
            if not values:
                return False
            return any(str(v) in ctx.peer_entity_ids for v in values)
        # watchlist / scenario 由上层处理；此处不误判
        return True

    def _finalize(
        self,
        requirement: ScenarioDataRequirement,
        spec: DataTypeReadinessSpec,
        eligible: List[Dict[str, Any]],
        ineligible_count: int,
        refs: List[str],
        tiers_present: List[str],
        available: set,
        coverage: Optional[float],
        coverage_warnings: List[str],
        freshness_age: Optional[int],
        health_warning: Optional[str] = None,
    ) -> ReadinessCheckResult:
        """统一状态定级（ReadinessFinalizer，§86-89）。"""
        missing = [f for f in requirement.minimum_fields if f not in available]
        warnings: List[str] = list(coverage_warnings)
        if missing:
            warnings.append(MISSING_REQUIRED_FIELDS)
        if health_warning:
            warnings.append(health_warning)

        if health_warning == "SOURCE_UNHEALTHY":
            return ReadinessCheckResult(
                status="SOURCE_UNHEALTHY", available_fields=sorted(available),
                coverage_ratio=coverage, eligible_record_count=len(eligible),
                ineligible_record_count=ineligible_count,
                source_tiers_present=sorted(tiers_present), record_refs=refs,
                warnings=warnings, freshness_age_seconds=freshness_age,
            )
        if not eligible:
            return ReadinessCheckResult(
                status="MISSING", available_fields=sorted(available),
                coverage_ratio=coverage, eligible_record_count=0,
                ineligible_record_count=ineligible_count,
                source_tiers_present=sorted(tiers_present), record_refs=refs,
                warnings=warnings + ([NO_ELIGIBLE_RECORDS] if NO_ELIGIBLE_RECORDS not in warnings else []),
                freshness_age_seconds=freshness_age,
            )

        # freshness（§56-57）：有合格数据时 freshness 失败 → STALE（优先于 coverage 降级）
        freshness_issue: Optional[str] = None
        if requirement.freshness_seconds > 0:
            if freshness_age is None:
                freshness_issue = FRESHNESS_UNPROVEN
            elif freshness_age > requirement.freshness_seconds:
                freshness_issue = STALE_DATA
        if freshness_issue == STALE_DATA:
            warnings.append(STALE_DATA)
            return ReadinessCheckResult(
                status="STALE", available_fields=sorted(available),
                coverage_ratio=coverage, eligible_record_count=len(eligible),
                ineligible_record_count=ineligible_count,
                source_tiers_present=sorted(tiers_present), record_refs=refs,
                warnings=warnings, freshness_age_seconds=freshness_age,
            )
        if freshness_issue == FRESHNESS_UNPROVEN:
            warnings.append(FRESHNESS_UNPROVEN)

        # coverage 规则（§45-46）
        if requirement.minimum_coverage > 0 and coverage is None:
            status = "PARTIAL"
            if COVERAGE_NOT_MEASURABLE not in warnings:
                warnings.append(COVERAGE_NOT_MEASURABLE)
        elif coverage is not None and coverage < requirement.minimum_coverage \
                and requirement.minimum_coverage > 0:
            status = "PARTIAL"
            if COVERAGE_BELOW_MINIMUM not in warnings:
                warnings.append(COVERAGE_BELOW_MINIMUM)
        elif missing:
            status = "PARTIAL"
        elif freshness_issue == FRESHNESS_UNPROVEN:
            status = "PARTIAL"
        else:
            status = "READY"

        return ReadinessCheckResult(
            status=status, available_fields=sorted(available),
            coverage_ratio=coverage, eligible_record_count=len(eligible),
            ineligible_record_count=ineligible_count,
            source_tiers_present=sorted(tiers_present), record_refs=refs,
            warnings=warnings, freshness_age_seconds=freshness_age,
        )

    def _miss(self, requirement, warnings: List[str]) -> ReadinessCheckResult:
        return ReadinessCheckResult(
            status="MISSING", coverage_ratio=None, warnings=warnings,
        )


class RawItemChecker(ReadinessChecker):
    """RawItem 系 checker（news_flash / company_announcement / macro_data /
    brief_event_content / brief_attention_content）。

    共享 raw_items 表，但 semantic eligibility 独立（§21-26）：
    只读 raw_items 中 source_id / raw_category 满足该 canonical data_type 的确定性约束。
    禁止任意 RawItem 跨类型满足 Requirement（§22）。
    """

    data_types = ("news_flash", "company_announcement", "macro_data",
                  "brief_event_content", "brief_attention_content")

    # data_type → 确定性 eligibility 约束（source 治理已注册 / raw_category）
    _TYPE_RAW_CATEGORY: Dict[str, Tuple[str, ...]] = {
        "news_flash": ("fast_news", "news", "market_news"),
        "company_announcement": ("official_disclosure", "announcement"),
        "macro_data": ("government_and_regulator", "macro", "macro_data"),
    }

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        if not view.has_table("raw_items"):
            return self._miss(requirement, [f"TABLE_ABSENT:raw_items"])
        if spec.scope_strategy == "WATCHLIST" and ctx.requirement.scope.scope_type == "watchlist":
            # watchlist scope：无 watchlist 上下文 → fail closed（不猜测）
            if not ctx.watchlist_group:
                return self._miss(requirement, [SCOPE_MISMATCH, "watchlist"])

        # 只读 raw_items；按窗口过滤
        rows = []
        if ctx.window_start and ctx.window_end:
            rows = view.query(
                "SELECT payload FROM raw_items "
                "WHERE json_extract(payload, '$.published_at') >= ? "
                "AND json_extract(payload, '$.published_at') < ?",
                (ctx.window_start, ctx.window_end),
            )
        else:
            rows = view.query("SELECT payload FROM raw_items")

        eligible: List[Dict[str, Any]] = []
        ineligible_count = 0
        available: set = set()
        tiers_present: set = set()
        refs: List[str] = []
        for row in rows:
            payload = self._payload(row)
            if payload is None:
                ineligible_count += 1
                continue
            # semantic eligibility（§23）：raw_category 或 source_id 映射
            raw_category = (payload.get("raw_category") or "").lower()
            allowed_categories = self._TYPE_RAW_CATEGORY.get(requirement.data_type)
            eligible_type = False
            if allowed_categories and raw_category in allowed_categories:
                eligible_type = True
            source_id = payload.get("source_id")
            if not eligible_type and source_id and \
                    self._source_maps_to_type(source_id, requirement.data_type):
                eligible_type = True
            if not eligible_type:
                ineligible_count += 1
                continue
            # PIT：published_at 不得晚于 as_of（§115；窗口下界之外再加 as_of 上界）
            published = payload.get("published_at")
            if published and published > ctx.as_of:
                ineligible_count += 1
                continue
            # scope（watchlist / global）
            if not self._scope_eligible(payload, ctx):
                ineligible_count += 1
                continue
            # provenance tier（raw_item_source → sources.yaml）
            if spec.source_tier_applicable:
                tier, warn = provenance.resolve(payload, "raw_item_source", view)
                if tier is None:
                    ineligible_count += 1
                    continue
                tiers_present.add(tier)
                if _TIER_ORDER[tier] > _TIER_ORDER[requirement.minimum_source_tier]:
                    ineligible_count += 1
                    continue
            eligible.append(payload)
            ref = payload.get("raw_item_id") or payload.get("id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)

        # coverage：open-world（无合法 denominator）→ null（§43-44）
        coverage = None
        warnings = [COVERAGE_NOT_MEASURABLE]
        freshness_age = self._freshness_age(eligible, spec, ctx)
        return self._finalize(
            requirement, spec, eligible, ineligible_count, refs,
            list(tiers_present), available, coverage, warnings, freshness_age,
        )

    def _source_maps_to_type(self, source_id: str, data_type: str) -> bool:
        """source_id → canonical data_type 的确定性映射（既有治理信息，只读）。"""
        # cninfo → company_announcement；nbs → macro_data；cls → news_flash
        if data_type == "company_announcement" and source_id in ("cninfo", "sse", "szse", "csrc"):
            return True
        if data_type == "macro_data" and source_id in ("nbs", "csrc"):
            return True
        if data_type == "news_flash" and source_id in ("cls",):
            return True
        return False

    def _payload(self, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None

    def _freshness_age(self, eligible, spec, ctx) -> Optional[int]:
        if not eligible or spec.freshness_strategy == "not_applicable":
            return None
        from research_os.utils.time import parse_iso
        ages = []
        for p in eligible:
            ts = p.get("published_at")
            if ts:
                try:
                    ages.append(_seconds_between(ts, ctx.as_of))
                except ValueError:
                    continue
        if not ages:
            return None
        return max(ages)  # 保守：满足 requirement 所需记录集合中的最大 age（§55）


class ProfileChecker(ReadinessChecker):
    """company_profile / security_profile 系 checker（authority 按 spec 映射）。"""

    data_types = ("company_profile", "security_profile")
    _TABLE = {"company_profile": "company_profiles", "security_profile": "security_profiles"}
    _ID_KEYS = {"company_profile": ("company_entity_id", "entity_id"),
                "security_profile": ("security_entity_id", "entity_id")}

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        table = self._TABLE[requirement.data_type]
        if not view.has_table(table):
            return self._miss(requirement, [f"TABLE_ABSENT:{table}"])
        if not ctx.entity_ids:
            return self._miss(requirement, [SCOPE_MISMATCH, "subject"])
        rows = view.query(f"SELECT payload FROM {table}")
        eligible, ineligible_count, available, tiers_present, refs = [], 0, set(), set(), []
        for row in rows:
            payload = self._payload(row)
            if payload is None:
                ineligible_count += 1
                continue
            if not self._scope_eligible(payload, ctx, scope_payload_keys=self._ID_KEYS[requirement.data_type]):
                ineligible_count += 1
                continue
            # PIT：valid_from/valid_to 区间必须覆盖 as_of（valid_interval，§17）
            if not self._valid_interval_covers(payload, ctx.as_of):
                ineligible_count += 1
                continue
            # provenance（evidence_ids → tier）
            if spec.source_tier_applicable:
                tier, warn = provenance.resolve(payload, "evidence_ids", view)
                if tier is None:
                    ineligible_count += 1
                    continue
                tiers_present.add(tier)
                if _TIER_ORDER[tier] > _TIER_ORDER[requirement.minimum_source_tier]:
                    ineligible_count += 1
                    continue
            eligible.append(payload)
            ref = payload.get("company_profile_id") or payload.get("security_profile_id") \
                or payload.get("id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        # SINGLETON_TARGET：存在合格对象 → 1.0；缺失 → 0.0（§40）
        coverage = 1.0 if eligible else 0.0
        freshness_age = self._profile_age(eligible, spec, ctx)
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              list(tiers_present), available, coverage, [], freshness_age)

    def _valid_interval_covers(self, payload, as_of: str) -> bool:
        valid_from = payload.get("valid_from")
        valid_to = payload.get("valid_to")
        if valid_from and valid_from > as_of:
            return False  # 尚未生效
        if valid_to and valid_to <= as_of:
            return False  # 已过期
        status = payload.get("status")
        if status and str(status).lower() not in ("active", "approved", "valid"):
            return False
        return True

    def _profile_age(self, eligible, spec, ctx) -> Optional[int]:
        if not eligible or spec.freshness_strategy == "not_applicable":
            return None
        ages = []
        for p in eligible:
            ts = p.get("valid_from")
            if ts:
                try:
                    ages.append(_seconds_between(ts, ctx.as_of))
                except ValueError:
                    continue
        return max(ages) if ages else None

    def _payload(self, row):
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None


class IndustryMembershipChecker(ReadinessChecker):
    """industry_membership：机械证明 requested company → valid industry membership（§20）。"""

    data_types = ("industry_membership",)

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        if not view.has_table("company_profiles"):
            return self._miss(requirement, [f"TABLE_ABSENT:company_profiles"])
        if not ctx.industry_ids:
            return self._miss(requirement, [SCOPE_MISMATCH, "industry"])
        rows = view.query("SELECT payload FROM company_profiles")
        eligible, ineligible_count, available, refs = [], 0, set(), []
        for row in rows:
            payload = self._payload(row)
            if payload is None:
                ineligible_count += 1
                continue
            industry_ids = payload.get("industry_ids") or []
            if isinstance(industry_ids, str):
                industry_ids = [industry_ids]
            if not any(str(i) in ctx.industry_ids for i in industry_ids):
                ineligible_count += 1
                continue
            valid_from, valid_to = payload.get("valid_from"), payload.get("valid_to")
            if valid_from and valid_from > ctx.as_of:
                ineligible_count += 1
                continue
            if valid_to and valid_to <= ctx.as_of:
                ineligible_count += 1
                continue
            eligible.append(payload)
            ref = payload.get("company_profile_id") or payload.get("id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        # REQUESTED_ENTITY_SET（§41）：industries with eligible membership / requested industries
        coverage = None
        if ctx.industry_ids:
            industries_with_eligible = set()
            for p in eligible:
                ids = p.get("industry_ids") or []
                if isinstance(ids, str):
                    ids = [ids]
                industries_with_eligible.update(str(i) for i in ids if str(i) in ctx.industry_ids)
            if ctx.industry_ids:
                coverage = len(industries_with_eligible) / len(ctx.industry_ids)
        freshness_age = None
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              [], available, coverage, [], freshness_age)

    def _payload(self, row):
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None


class FinancialChecker(ReadinessChecker):
    """financial_statement_data / peer_financial_data（authority=financial_facts，§18-19）。"""

    data_types = ("financial_statement_data", "peer_financial_data")

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        if not view.has_table("financial_facts"):
            return self._miss(requirement, [f"TABLE_ABSENT:financial_facts"])
        rows = view.query("SELECT payload FROM financial_facts")
        scope_keys = ("company_entity_id",)
        if spec.scope_strategy == "PEERS" and not ctx.peer_entity_ids:
            # peer set unresolved → coverage null（§42），不发明 denominator
            return self._finalize(requirement, spec, [], 0, [], [], set(),
                                  None, [COVERAGE_NOT_MEASURABLE], None)
        eligible, ineligible_count, available, tiers_present, refs = [], 0, set(), set(), []
        for row in rows:
            payload = self._payload(row)
            if payload is None:
                ineligible_count += 1
                continue
            if not self._scope_eligible(payload, ctx, scope_payload_keys=scope_keys):
                ineligible_count += 1
                continue
            # PIT：publication availability（§18）——证据或 document 发布必须早于 as_of
            if not self._publication_proven(payload, view, ctx.as_of):
                ineligible_count += 1
                continue
            if spec.source_tier_applicable:
                tier, warn = provenance.resolve(payload, "evidence_ids", view)
                if tier is None:
                    ineligible_count += 1
                    continue
                tiers_present.add(tier)
                if _TIER_ORDER[tier] > _TIER_ORDER[requirement.minimum_source_tier]:
                    ineligible_count += 1
                    continue
            eligible.append(payload)
            ref = payload.get("fact_id") or payload.get("id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        # coverage：SINGLETON / REQUESTED_PEER_SET
        coverage = None
        if spec.coverage_strategy == "SINGLETON_TARGET":
            coverage = 1.0 if eligible else 0.0
        elif spec.coverage_strategy == "REQUESTED_PEER_SET" and ctx.peer_entity_ids:
            if eligible:
                coverage = 1.0
        else:
            coverage = None
        freshness_age = None
        if eligible:
            ages = []
            for p in eligible:
                ts = p.get("observed_at") or p.get("created_at")
                if ts:
                    try:
                        ages.append(_seconds_between(ts, ctx.as_of))
                    except ValueError:
                        continue
            freshness_age = max(ages) if ages else None
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              list(tiers_present), available, coverage, [], freshness_age)

    def _publication_proven(self, payload, view, as_of: str) -> bool:
        """机械证明 as_of 时财务信息已公开（§18，防 look-ahead）。

        优先：evidence_ids → evidence.published_at <= as_of；或
        source_document_id → document_records.published_at <= as_of；
        period_end <= as_of 不足以证明（发布可能晚于 as_of）。
        """
        evidence_ids = payload.get("evidence_ids") or []
        if evidence_ids and view.has_table("evidence"):
            for eid in evidence_ids:
                rows = view.query(
                    "SELECT payload FROM evidence "
                    "WHERE json_extract(payload, '$.evidence_id') = ? "
                    "AND json_extract(payload, '$.published_at') <= ?",
                    (str(eid), as_of),
                )
                if rows:
                    return True
        source_doc = payload.get("source_document_id")
        if source_doc and view.has_table("document_records"):
            rows = view.query(
                "SELECT payload FROM document_records "
                "WHERE json_extract(payload, '$.document_id') = ? "
                "AND json_extract(payload, '$.published_at') <= ?",
                (str(source_doc), as_of),
            )
            if rows:
                return True
        return False

    def _payload(self, row):
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None


class ValuationChecker(ReadinessChecker):
    """market_valuation_snapshot（authority=valuation_snapshots，§16 修正）。"""

    data_types = ("market_valuation_snapshot",)

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        if not view.has_table("valuation_snapshots"):
            return self._miss(requirement, [f"TABLE_ABSENT:valuation_snapshots"])
        if not ctx.entity_ids:
            return self._miss(requirement, [SCOPE_MISMATCH, "subject"])
        rows = view.query("SELECT payload FROM valuation_snapshots")
        scope_keys = ("company_entity_id", "security_entity_id", "entity_id")
        eligible, ineligible_count, available, tiers_present, refs = [], 0, set(), set(), []
        for row in rows:
            payload = self._payload(row)
            if payload is None:
                ineligible_count += 1
                continue
            if not self._scope_eligible(payload, ctx, scope_payload_keys=scope_keys):
                ineligible_count += 1
                continue
            # PIT：snapshot as_of 不得晚于 requirement as_of（as_of 策略）
            snap_as_of = payload.get("as_of")
            if snap_as_of and snap_as_of > ctx.as_of:
                ineligible_count += 1
                continue
            status = payload.get("status")
            if status and str(status).lower() not in ("active", "approved", "valid"):
                ineligible_count += 1
                continue
            if spec.source_tier_applicable:
                tier, warn = provenance.resolve(payload, "evidence_ids", view)
                if tier is None:
                    ineligible_count += 1
                    continue
                tiers_present.add(tier)
                if _TIER_ORDER[tier] > _TIER_ORDER[requirement.minimum_source_tier]:
                    ineligible_count += 1
                    continue
            eligible.append(payload)
            ref = payload.get("valuation_snapshot_id") or payload.get("id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        coverage = 1.0 if eligible else 0.0
        freshness_age = None
        if eligible:
            ages = []
            for p in eligible:
                ts = p.get("as_of")
                if ts:
                    try:
                        ages.append(_seconds_between(ts, ctx.as_of))
                    except ValueError:
                        continue
            freshness_age = max(ages) if ages else None
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              list(tiers_present), available, coverage, [], freshness_age)

    def _payload(self, row):
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None


class DocumentChecker(ReadinessChecker):
    """company_document / document_corpus（authority=document_records）。"""

    data_types = ("company_document", "document_corpus")

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        if not view.has_table("document_records"):
            return self._miss(requirement, [f"TABLE_ABSENT:document_records"])
        rows = view.query("SELECT payload FROM document_records")
        scope_keys = ("company_entity_id", "security_entity_id", "entity_id")
        eligible, ineligible_count, available, tiers_present, refs = [], 0, set(), set(), []
        for row in rows:
            payload = self._payload(row)
            if payload is None:
                ineligible_count += 1
                continue
            if not self._scope_eligible(payload, ctx, scope_payload_keys=scope_keys):
                ineligible_count += 1
                continue
            published = payload.get("published_at")
            if published and published > ctx.as_of:
                ineligible_count += 1
                continue
            if spec.source_tier_applicable:
                tier, warn = provenance.resolve(payload, "evidence_ids", view)
                if tier is None:
                    ineligible_count += 1
                    continue
                tiers_present.add(tier)
                if _TIER_ORDER[tier] > _TIER_ORDER[requirement.minimum_source_tier]:
                    ineligible_count += 1
                    continue
            eligible.append(payload)
            ref = payload.get("document_id") or payload.get("id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        coverage = None
        if spec.coverage_strategy == "SINGLETON_TARGET":
            coverage = 1.0 if eligible else 0.0
        elif spec.coverage_strategy == "OPEN_WORLD":
            coverage = None
        else:
            coverage = None
        freshness_age = None
        if eligible:
            ages = []
            for p in eligible:
                ts = p.get("published_at")
                if ts:
                    try:
                        ages.append(_seconds_between(ts, ctx.as_of))
                    except ValueError:
                        continue
            freshness_age = max(ages) if ages else None
        warnings = [COVERAGE_NOT_MEASURABLE] if coverage is None else []
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              list(tiers_present), available, coverage, warnings, freshness_age)

    def _payload(self, row):
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None


class EvidenceContentChecker(ReadinessChecker):
    """evidence / claims / event_evidence / evidence_index（authority 按 spec 映射）。"""

    data_types = ("evidence", "claims", "event_evidence", "evidence_index")

    _TABLE = {"evidence": "evidence", "claims": "claims",
              "event_evidence": "evidence", "evidence_index": "evidence"}

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        table = self._TABLE[requirement.data_type]
        if not view.has_table(table):
            return self._miss(requirement, [f"TABLE_ABSENT:{table}"])
        rows = view.query(f"SELECT payload FROM {table}")
        scope_keys = ("subject_entities", "entities", "company_entity_id", "entity_id", "subject")
        eligible, ineligible_count, available, tiers_present, refs = [], 0, set(), set(), []
        for row in rows:
            payload = self._payload(row)
            if payload is None:
                ineligible_count += 1
                continue
            if not self._scope_eligible(payload, ctx, scope_payload_keys=scope_keys):
                ineligible_count += 1
                continue
            published = payload.get("published_at")
            if published and published > ctx.as_of:
                ineligible_count += 1
                continue
            # claims 的 as_of 不得晚于请求 cutoff（§115）
            claim_as_of = payload.get("as_of")
            if claim_as_of and claim_as_of > ctx.as_of:
                ineligible_count += 1
                continue
            if spec.source_tier_applicable:
                tier, warn = provenance.resolve(payload, spec.provenance_strategy, view)
                if tier is None:
                    ineligible_count += 1
                    continue
                tiers_present.add(tier)
                if _TIER_ORDER[tier] > _TIER_ORDER[requirement.minimum_source_tier]:
                    ineligible_count += 1
                    continue
            eligible.append(payload)
            ref = payload.get("evidence_id") or payload.get("claim_id") or payload.get("id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        coverage = None
        if spec.coverage_strategy == "SINGLETON_TARGET":
            coverage = 1.0 if eligible else 0.0
        elif spec.coverage_strategy == "OPEN_WORLD":
            coverage = None
        else:
            coverage = None
        freshness_age = None
        if eligible:
            ages = []
            for p in eligible:
                ts = p.get("published_at") or p.get("created_at")
                if ts:
                    try:
                        ages.append(_seconds_between(ts, ctx.as_of))
                    except ValueError:
                        continue
            freshness_age = max(ages) if ages else None
        warnings = [COVERAGE_NOT_MEASURABLE] if coverage is None else []
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              list(tiers_present), available, coverage, warnings, freshness_age)

    def _payload(self, row):
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None


class EntityMappingChecker(ReadinessChecker):
    """entity_mapping（authority=entities，内部权威，tier 不适用）。"""

    data_types = ("entity_mapping",)

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        if not view.has_table("entities"):
            return self._miss(requirement, [f"TABLE_ABSENT:entities"])
        rows = view.query("SELECT payload FROM entities")
        eligible, ineligible_count, available, refs = [], 0, set(), []
        for row in rows:
            payload = self._payload(row)
            if payload is None:
                ineligible_count += 1
                continue
            if not self._scope_eligible(payload, ctx, scope_payload_keys=("entity_id", "aliases")):
                ineligible_count += 1
                continue
            valid_from, valid_to = payload.get("valid_from"), payload.get("valid_to")
            if valid_from and valid_from > ctx.as_of:
                ineligible_count += 1
                continue
            if valid_to and valid_to <= ctx.as_of:
                ineligible_count += 1
                continue
            eligible.append(payload)
            ref = payload.get("entity_id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        coverage = 1.0 if eligible else 0.0
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              [], available, coverage, [], None)

    def _payload(self, row):
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None


class ResearchFindingsChecker(ReadinessChecker):
    """research_findings（authority=research_findings，内部权威）。"""

    data_types = ("research_findings",)

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        if not view.has_table("research_findings"):
            return self._miss(requirement, [f"TABLE_ABSENT:research_findings"])
        rows = view.query("SELECT payload FROM research_findings")
        scope_keys = ("company_entity_id", "entity_id", "subject")
        eligible, ineligible_count, available, refs = [], 0, set(), []
        for row in rows:
            payload = self._payload(row)
            if payload is None:
                ineligible_count += 1
                continue
            if not self._scope_eligible(payload, ctx, scope_payload_keys=scope_keys):
                ineligible_count += 1
                continue
            created = payload.get("created_at")
            if created and created > ctx.as_of:
                ineligible_count += 1
                continue
            eligible.append(payload)
            ref = payload.get("finding_id") or payload.get("id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        coverage = 1.0 if eligible else 0.0
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              [], available, coverage, [], None)

    def _payload(self, row):
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None


class MarketSeriesChecker(ReadinessChecker):
    """market_daily_ohlcv（authority=market_daily_ohlcv，trade_date PIT）。"""

    data_types = ("market_daily_ohlcv",)

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        if not view.has_table("market_daily_ohlcv"):
            return self._miss(requirement, [f"TABLE_ABSENT:market_daily_ohlcv"])
        if not ctx.entity_ids:
            return self._miss(requirement, [SCOPE_MISMATCH, "subject"])
        rows = view.query("SELECT payload FROM market_daily_ohlcv")
        scope_keys = ("symbol", "company_entity_id", "entity_id")
        eligible, ineligible_count, available, refs = [], 0, set(), []
        for row in rows:
            payload = self._payload(row)
            if payload is None:
                ineligible_count += 1
                continue
            if not self._scope_eligible(payload, ctx, scope_payload_keys=scope_keys):
                ineligible_count += 1
                continue
            trade_date = payload.get("trade_date")
            if trade_date and trade_date > ctx.as_of[:10]:
                ineligible_count += 1
                continue
            eligible.append(payload)
            ref = f"{payload.get('symbol')}:{payload.get('trade_date')}"
            refs.append(ref)
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        # coverage：AUTHORITATIVE_TRADING_CALENDAR
        # 仓库当前无权威交易日历 authority → null + COVERAGE_NOT_MEASURABLE（§47-48, 104）
        coverage = None
        warnings = [COVERAGE_NOT_MEASURABLE]
        freshness_age = None
        if eligible:
            ages = []
            for p in eligible:
                ts = p.get("trade_date")
                if ts:
                    try:
                        ages.append(_seconds_between(ts + "T00:00:00+08:00", ctx.as_of))
                    except ValueError:
                        continue
            freshness_age = max(ages) if ages else None
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              [], available, coverage, warnings, freshness_age)

    def _payload(self, row):
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        return payload if isinstance(payload, dict) else None


class GraphSnapshotChecker(ReadinessChecker):
    """knowledge_graph_snapshot（复用既有 Graph lifecycle/query authority，§62-68）。"""

    data_types = ("knowledge_graph_snapshot",)

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        graph_query = getattr(view, "graph_query_service", None)
        history = getattr(view, "graph_history_service", None)
        if graph_query is None or history is None:
            return self._miss(requirement, [GRAPH_SCOPE_UNRESOLVED, "GRAPH_AUTHORITY_UNAVAILABLE"])
        # industry scope：现有 graph identity resolution（industry_id → root node）
        if ctx.requirement.scope.scope_type == "industry" and not ctx.industry_ids:
            return self._miss(requirement, [SCOPE_MISMATCH, "industry", GRAPH_SCOPE_UNRESOLVED])
        try:
            # 用 HistoryService.resolve_node_as_of 证明 industry root 在 as_of 有效
            for industry_id in ctx.industry_ids or [None]:
                if industry_id is None:
                    continue
                resolved = history.resolve_node_as_of(industry_id, ctx.as_of)
                if resolved is None:
                    return self._miss(requirement, [GRAPH_SCOPE_UNRESOLVED, f"ROOT_MISSING:{industry_id}"])
                node = graph_query.get_node(industry_id, ctx.as_of)
                if node is None or getattr(node, "error", None):
                    return self._miss(requirement, [GRAPH_SCOPE_UNRESOLVED, f"NOT_VALID_AT_AS_OF:{industry_id}"])
        except Exception as exc:  # noqa: BLE001
            return self._miss(requirement, [GRAPH_SCOPE_UNRESOLVED, f"GRAPH_READ_FAILED:{type(exc).__name__}"])
        # global scope：无法机械证明 global snapshot coverage → coverage null
        coverage = None
        warnings = [COVERAGE_NOT_MEASURABLE]
        if not ctx.industry_ids and ctx.requirement.scope.scope_type == "global":
            # 无 industry root 可证明 → 保守 not READY（§67）
            return self._miss(requirement, [GRAPH_SCOPE_UNRESOLVED, "GLOBAL_SNAPSHOT_UNPROVEN"])
        available = {"node_refs", "edge_refs", "as_of"}
        if ctx.industry_ids:
            available.add("industry_id")
        missing = [f for f in requirement.minimum_fields if f not in available]
        if missing:
            warnings.append(MISSING_REQUIRED_FIELDS)
        status = "PARTIAL" if missing or requirement.minimum_coverage > 0 else "READY"
        return ReadinessCheckResult(
            status=status, available_fields=sorted(available), coverage_ratio=coverage,
            eligible_record_count=1 if ctx.industry_ids else 0, ineligible_record_count=0,
            source_tiers_present=[], record_refs=list(ctx.industry_ids or []),
            warnings=warnings, freshness_age_seconds=None,
        )


class RunArtifactChecker(ReadinessChecker):
    """run_artifacts（authority=runs_root 目录产物，内部权威）。"""

    data_types = ("run_artifacts",)

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        runs_root = getattr(view, "runs_root", None)
        if runs_root is None or not runs_root.exists():
            return self._miss(requirement, [NO_ELIGIBLE_RECORDS])
        artifacts = [p for p in runs_root.iterdir() if p.is_dir()]
        if not artifacts:
            return self._miss(requirement, [NO_ELIGIBLE_RECORDS])
        # 走 _finalize：minimum_fields / coverage / freshness 统一判定
        available = {"task_id", "run_id"}
        return self._finalize(
            requirement, spec, artifacts, 0,
            [a.name for a in artifacts[:50]], [], available,
            coverage=None, coverage_warnings=[COVERAGE_NOT_MEASURABLE],
            freshness_age=None,
        )


# ---------- ReadinessCheckerRegistry（22/22 注册） ----------

class ReadinessCheckerRegistry:
    """data_type → checker 映射；缺 checker 抛 CONTROL_PLANE_CONFIGURATION_ERROR。"""

    def __init__(self, checkers: Optional[List[ReadinessChecker]] = None,
                 provenance: Optional[ReadinessProvenanceResolver] = None):
        self._map: Dict[str, ReadinessChecker] = {}
        selected = checkers if checkers is not None else _DEFAULT_CHECKERS
        for checker in selected:
            for dtype in checker.data_types:
                self._map[dtype] = checker
        # 默认加载仓库 sources.yaml 治理（provenance tier 必须来自既有 Source authority）
        if provenance is None:
            _repo_root = Path(__file__).resolve().parents[3]
            sources_path = _repo_root / "registry" / "sources.yaml"
            provenance = ReadinessProvenanceResolver(
                sources_yaml_path=str(sources_path) if sources_path.exists() else None)
        self._provenance = provenance

    def has(self, data_type: str) -> bool:
        return data_type in self._map

    def get(self, data_type: str) -> ReadinessChecker:
        try:
            return self._map[data_type]
        except KeyError as exc:
            raise ValueError(
                f"CONTROL_PLANE_CONFIGURATION_ERROR: data_type {data_type!r} 无 checker"
            ) from exc

    def data_types(self) -> List[str]:
        return sorted(self._map)

    def evaluate(self, ctx, requirement, view, checked_at: str):
        from research_os.data_layer.readiness import DataReadinessService
        return DataReadinessService(self).evaluate(requirement, ctx, view, checked_at, self._provenance)


_DEFAULT_CHECKERS: List[ReadinessChecker] = [
    RawItemChecker(),
    ProfileChecker(),
    IndustryMembershipChecker(),
    FinancialChecker(),
    ValuationChecker(),
    DocumentChecker(),
    EvidenceContentChecker(),
    EntityMappingChecker(),
    ResearchFindingsChecker(),
    MarketSeriesChecker(),
    GraphSnapshotChecker(),
    RunArtifactChecker(),
]


def _seconds_between(ts: str, as_of: str) -> int:
    from research_os.utils.time import parse_iso
    t0 = parse_iso(ts)
    t1 = parse_iso(as_of)
    return max(0, int((t1 - t0).total_seconds()))
