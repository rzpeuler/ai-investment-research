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
from datetime import date
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
from research_os.utils.time import parse_iso

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
    # R3：eligible authority payloads（供 runtime canonical projector 判定 minimum fields）
    eligible_payloads: List[Dict[str, Any]] = field(default_factory=list)


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

    # ---------- R3-04/07：runtime binding 优先（§9/32/54） ----------

    def _binding(self, ctx) -> Optional[Any]:
        """runtime binding（production preflight 注入）；无 binding（单测）→ None。"""
        return getattr(ctx, "binding", None)

    def _cov_strategy(self, ctx, spec) -> str:
        """R3-04：coverage 必须用 binding.coverage_strategy（§32），不得绕回 generic spec。"""
        binding = self._binding(ctx)
        if binding is not None:
            return binding.coverage_strategy
        return spec.coverage_strategy

    def _prov_strategy(self, ctx, spec) -> str:
        """R3-07：provenance 必须用 binding.provenance_strategy（§54）。"""
        binding = self._binding(ctx)
        if binding is not None:
            return binding.provenance_strategy
        return spec.provenance_strategy

    def _tier_applicable(self, ctx, spec) -> bool:
        """R3-07：tier 适用性必须用 binding.source_tier_applicable（§54）。"""
        binding = self._binding(ctx)
        if binding is not None:
            return binding.source_tier_applicable
        return spec.source_tier_applicable

    def _fresh_strategy(self, ctx, spec) -> str:
        """R3：freshness 必须用 binding.freshness_strategy（§9）。"""
        binding = self._binding(ctx)
        if binding is not None:
            return binding.freshness_strategy
        return spec.freshness_strategy

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
                eligible_payloads=list(eligible),
            )
        if not eligible:
            return ReadinessCheckResult(
                status="MISSING", available_fields=sorted(available),
                coverage_ratio=coverage, eligible_record_count=0,
                ineligible_record_count=ineligible_count,
                source_tiers_present=sorted(tiers_present), record_refs=refs,
                warnings=warnings + ([NO_ELIGIBLE_RECORDS] if NO_ELIGIBLE_RECORDS not in warnings else []),
                freshness_age_seconds=freshness_age,
                eligible_payloads=[],
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
                eligible_payloads=list(eligible),
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
            eligible_payloads=list(eligible),
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

        # 只读 raw_items；窗口 eligibility 必须在 Python parse_iso 后判定（§5）：
        # SQL 字符串 prefilter 不得作为 authoritative eligibility（不同 offset 表示等价时间
        # 但字符串排序不等价）。D1 数据量非瓶颈 → 取全部候选，Python 过滤。
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
            if _iso_gt(published, ctx.as_of):
                ineligible_count += 1
                continue
            # R3.1-01：窗口 eligibility 按 instant 判定（parse_iso，禁止字典序；§5/§11）
            if not _in_window(published, ctx.window_start, ctx.window_end):
                ineligible_count += 1
                continue
            # scope（watchlist / global）
            if not self._scope_eligible(payload, ctx):
                ineligible_count += 1
                continue
            # provenance tier（raw_item_source → sources.yaml）
            if self._tier_applicable(ctx, spec):
                tier, warn = provenance.resolve(payload, self._prov_strategy(ctx, spec), view)
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
        if not eligible or self._fresh_strategy(ctx, spec) == "not_applicable":
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
                "security_profile": ("security_entity_id", "company_entity_id", "entity_id")}

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
            # PIT：按 data_type 生命周期（§23-25）
            if not self._pit_covers(payload, ctx.as_of, requirement.data_type):
                ineligible_count += 1
                continue
            # provenance（evidence_ids → tier）
            if self._tier_applicable(ctx, spec):
                tier, warn = provenance.resolve(payload, self._prov_strategy(ctx, spec), view)
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
        # R3.1-08：coverage 走 binding（§59）；SINGLETON_TARGET：存在合格对象 → 1.0；
        # 缺失 → 0.0（§40）
        if self._cov_strategy(ctx, spec) == "SINGLETON_TARGET":
            coverage = 1.0 if eligible else 0.0
        else:
            coverage = None
        freshness_age = self._profile_age(eligible, spec, ctx, requirement.data_type)
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              list(tiers_present), available, coverage,
                              [] if coverage is not None else [COVERAGE_NOT_MEASURABLE],
                              freshness_age)

    def _pit_covers(self, payload, as_of: str, data_type: str) -> bool:
        """R2-04：SecurityProfile 生命周期 ≠ CompanyProfile 生命周期。

        SecurityProfile: listing_date / delisting_date / status ∈ {listed, suspended,
        delisted, unknown}。as_of < listing_date → PIT_INELIGIBLE（status=listed 不得
        提前可用）。suspended 按自身语义处理（不剔除未来 listing，不按 company 状态污染）。
        CompanyProfile: valid_from/valid_to/status ∈ {active, approved, valid}。
        """
        if data_type == "security_profile":
            # §9：date-only 字段（listing_date/delisting_date）用 date.fromisoformat 显式
            # 比较，不做 naive datetime 混合（as_of 取日期部分，均为 YYYY-MM-DD）。
            try:
                as_of_date = parse_iso(as_of).date()
                listing_raw = payload.get("listing_date")
                listing_date = (
                    date.fromisoformat(str(listing_raw)) if listing_raw is not None else None
                )
                delisting_raw = payload.get("delisting_date")
                delisting_date = (
                    date.fromisoformat(str(delisting_raw))
                    if delisting_raw is not None else None
                )
            except (TypeError, ValueError):
                return False
            if listing_date and listing_date > as_of_date:
                return False  # 尚未上市
            if delisting_date and delisting_date <= as_of_date:
                # delisted 历史映射：delisting_date 已过 → as_of 时不可用
                return False
            status = str(payload.get("status") or "").lower()
            if status == "delisted":
                return False
            if status == "suspended":
                # suspended 按 SecurityProfile 自身语义：可满足 fields（listing 生命周期内）
                return True
            if status == "listed":
                return True
            if status == "unknown":
                return True  # 状态未知不伪造剔除（由 freshness/provenance 兜底）
            # 其他状态值：不按 company 规则污染（§25）
            return True
        # company_profile：valid_from/valid_to + status
        valid_from = payload.get("valid_from")
        valid_to = payload.get("valid_to")
        if _iso_gt(valid_from, as_of):
            return False
        if _iso_le(valid_to, as_of):
            return False
        status = payload.get("status")
        if status and str(status).lower() not in ("active", "approved", "valid"):
            return False
        return True

    def _profile_age(self, eligible, spec, ctx, data_type: str) -> Optional[int]:
        if not eligible or self._fresh_strategy(ctx, spec) == "not_applicable":
            return None
        ages = []
        for p in eligible:
            # §26：SecurityProfile freshness 用 updated_at（listing_date 不代表 freshness）
            ts = p.get("updated_at") if data_type == "security_profile" else p.get("valid_from")
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
        rows = view.query("SELECT payload FROM company_profiles")
        eligible, ineligible_count, available, refs = [], 0, set(), []
        for row in rows:
            payload = self._payload(row)
            if payload is None:
                ineligible_count += 1
                continue
            # R2-07 scope：
            # - subject scope（stock_research_report）：目标 company 必须在 as_of 有行业归属（§35）
            # - industry scope（industry_research/theme_discovery/first_coverage）：必须确认
            #   subject company 属于 requested industry（first_coverage，§36）或行业成员（§37）
            if ctx.requirement.scope.scope_type == "subject":
                if not ctx.entity_ids:
                    ineligible_count += 1
                    continue
                if not self._scope_eligible(payload, ctx, scope_payload_keys=("entity_id", "company_entity_id")):
                    ineligible_count += 1
                    continue
            else:
                if not ctx.industry_ids:
                    ineligible_count += 1
                    continue
                industry_ids = payload.get("industry_ids") or []
                if isinstance(industry_ids, str):
                    industry_ids = [industry_ids]
                if not any(str(i) in ctx.industry_ids for i in industry_ids):
                    ineligible_count += 1
                    continue
            valid_from, valid_to = payload.get("valid_from"), payload.get("valid_to")
            if _iso_gt(valid_from, ctx.as_of):
                ineligible_count += 1
                continue
            if _iso_le(valid_to, ctx.as_of):
                ineligible_count += 1
                continue
            status = payload.get("status")
            if status and str(status).lower() not in ("active", "approved", "valid"):
                ineligible_count += 1
                continue
            # R3-07/§55：IndustryMembership 必须执行 minimum_source_tier
            # （CompanyProfile.source_ids/evidence_ids → Provenance；不能仅 membership 正确就跳过 tier）
            if self._tier_applicable(ctx, spec):
                tier, warn = provenance.resolve(
                    payload, self._prov_strategy(ctx, spec), view)
                if tier is None:
                    ineligible_count += 1
                    continue
                if _TIER_ORDER[tier] > _TIER_ORDER[requirement.minimum_source_tier]:
                    ineligible_count += 1
                    continue
            eligible.append(payload)
            ref = payload.get("company_profile_id") or payload.get("id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        # R3.1-08：coverage 走 binding.coverage_strategy（§59；binding 已把
        # subject→SINGLETON_TARGET、industry→OPEN_WORLD 固化，§28-30）：
        # - subject scope（stock）：valid membership exists → 1.0；missing → 0.0
        # - industry scope 无权威完整成员全集：coverage = null（不得"一个成员 → 1.0"）
        coverage = None
        warnings: List[str] = []
        if self._cov_strategy(ctx, spec) == "SINGLETON_TARGET":
            coverage = 1.0 if eligible else 0.0
        else:
            coverage = None
            warnings.append(COVERAGE_NOT_MEASURABLE)
        freshness_age = None
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
            # R2-06/§34：canonical value projection——value_status 必须是 reported/derived_from_report
            # 且 normalized/raw value 非空（conflict/missing/not_applicable 不得满足）
            if not self._canonical_value_ok(payload):
                ineligible_count += 1
                continue
            if self._tier_applicable(ctx, spec):
                tier, warn = provenance.resolve(payload, self._prov_strategy(ctx, spec), view)
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
        # R2-06 coverage：
        # - financial_statement_data：无合法完整 fact universe → null + COVERAGE_NOT_MEASURABLE
        #   （不得"一条 fact → 1.0"；§31）
        # - peer_financial_data：coverage = peers with ≥1 fully eligible canonical fact / N（§32-33）
        coverage = None
        warnings: List[str] = []
        if self._cov_strategy(ctx, spec) == "SINGLETON_TARGET":
            # 无合法 expected complete fact universe → null（§31）
            coverage = None
            warnings.append(COVERAGE_NOT_MEASURABLE)
        elif self._cov_strategy(ctx, spec) == "REQUESTED_PEER_SET":
            if ctx.peer_entity_ids:
                peer_fact_count = {p.get("company_entity_id") for p in eligible}
                coverage = len(peer_fact_count & set(ctx.peer_entity_ids)) / len(ctx.peer_entity_ids)
                coverage = max(0.0, min(1.0, coverage))
            else:
                coverage = None  # peer set unresolved → null（§33）
                warnings.append(COVERAGE_NOT_MEASURABLE)
        else:
            coverage = None
            warnings.append(COVERAGE_NOT_MEASURABLE)
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
                              list(tiers_present), available, coverage, warnings, freshness_age)

    @staticmethod
    def _canonical_value_ok(payload: Dict[str, Any]) -> bool:
        """§10/§34：canonical value exists IFF value_status ∈ {reported, derived_from_report}
        AND (normalized_value != null OR raw_value != null)。conflict/missing/not_applicable 不得满足。"""
        status = payload.get("value_status")
        if status not in ("reported", "derived_from_report"):
            return False
        return payload.get("normalized_value") is not None or payload.get("raw_value") is not None

    def _publication_proven(self, payload, view, as_of: str) -> bool:
        """机械证明 as_of 时财务信息已公开（§18，防 look-ahead）。
        优先：evidence_ids → evidence.published_at <= as_of；或
        source_document_id → document_records.published_at <= as_of；
        period_end <= as_of 不足以证明（发布可能晚于 as_of）。
        R3.1-01：必须 fetch exact referenced object → parse published_at → parse as_of
        → 按 instant 比较（published_at <= as_of）。禁止 SQL 字符串时间比较（§6）。
        """
        try:
            as_of_dt = parse_iso(as_of)
        except ValueError:
            return False
        evidence_ids = payload.get("evidence_ids") or []
        if evidence_ids and view.has_table("evidence"):
            for eid in evidence_ids:
                rows = view.query(
                    "SELECT payload FROM evidence "
                    "WHERE json_extract(payload, '$.evidence_id') = ?",
                    (str(eid),),
                )
                for row in rows:
                    ep = self._payload(row)
                    if ep is None:
                        continue
                    pub = ep.get("published_at")
                    try:
                        pub_dt = parse_iso(pub)
                    except ValueError:
                        continue
                    if pub_dt <= as_of_dt:
                        return True
        source_doc = payload.get("source_document_id")
        if source_doc and view.has_table("document_records"):
            rows = view.query(
                "SELECT payload FROM document_records "
                "WHERE json_extract(payload, '$.document_id') = ?",
                (str(source_doc),),
            )
            for row in rows:
                dp = self._payload(row)
                if dp is None:
                    continue
                pub = dp.get("published_at")
                try:
                    pub_dt = parse_iso(pub)
                except ValueError:
                    continue
                if pub_dt <= as_of_dt:
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
            # PIT：snapshot as_of 不得晚于 requirement as_of（§29）
            snap_as_of = payload.get("as_of")
            if _iso_gt(snap_as_of, ctx.as_of):
                ineligible_count += 1
                continue
            # R2-05：正式状态 complete / partial / not_applicable / insufficient_data（§27-28）
            status = str(payload.get("status") or "").lower()
            if status == "not_applicable" or status == "insufficient_data":
                ineligible_count += 1
                continue
            if status == "partial":
                # partial 仅在 requirement 所需 fields（as_of/price/shares_outstanding）非空时满足
                if payload.get("price") is None or payload.get("shares_outstanding") is None:
                    ineligible_count += 1
                    continue
            # complete 或未知状态：继续按 PIT/fields/provenance 判定
            if self._tier_applicable(ctx, spec):
                tier, warn = provenance.resolve(payload, self._prov_strategy(ctx, spec), view)
                if tier is None:
                    ineligible_count += 1
                    continue
                tiers_present.add(tier)
                if _TIER_ORDER[tier] > _TIER_ORDER[requirement.minimum_source_tier]:
                    ineligible_count += 1
                    continue
            eligible.append(payload)
            ref = payload.get("valuation_snapshot_id") or payload.get("id")
            refs.append(str(ref) if ref else "")
        # §29：多个 snapshot 时确定性选取 latest eligible snapshot（as_of <= requirement as_of）；
        # R3.1-01：必须按 instant 排序（parse_iso），禁止字符串排序（§7/§14）；
        # malformed as_of → candidate ineligible（不得排进 latest selection）。
        if eligible:
            latest: Optional[Dict[str, Any]] = None
            latest_dt: Optional[Any] = None
            latest_ref = ""
            for payload, ref in zip(eligible, refs):
                snap_dt = _parse_dt(str(payload.get("as_of") or ""))
                if snap_dt is None:
                    continue  # malformed → ineligible（§10）
                if latest_dt is None or snap_dt > latest_dt:
                    latest, latest_dt, latest_ref = payload, snap_dt, ref
            if latest is None:
                eligible, refs, available, coverage = [], [], set(), 0.0
            else:
                eligible = [latest]
                refs = [latest_ref] if latest_ref else []
                available = {k for k in latest.keys() if latest.get(k) is not None}
                coverage = 1.0
        else:
            coverage = 0.0
        freshness_age = None
        if eligible:
            ts = eligible[0].get("as_of")
            if ts:
                try:
                    freshness_age = _seconds_between(ts, ctx.as_of)
                except ValueError:
                    freshness_age = None
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
            if _iso_gt(published, ctx.as_of):
                ineligible_count += 1
                continue
            if self._tier_applicable(ctx, spec):
                # R3-07：Document 用 binding.provenance_strategy（document_source：source_id→SourceRegistry）
                tier, warn = provenance.resolve(
                    payload, self._prov_strategy(ctx, spec), view)
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
        if self._cov_strategy(ctx, spec) == "SINGLETON_TARGET":
            coverage = 1.0 if eligible else 0.0
        elif self._cov_strategy(ctx, spec) == "OPEN_WORLD":
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
            # R3-03：Evidence subject/industry scope 必须经 RawItem provenance（§25-29）。
            # Evidence 无 subject 字段不再默认放行；通过 raw_item_id → RawItem.entities 校验。
            if requirement.data_type in ("evidence", "event_evidence", "evidence_index"):
                if not self._evidence_scope_ok(payload, ctx, view):
                    ineligible_count += 1
                    continue
            else:
                has_subject_field = any(payload.get(k) is not None for k in scope_keys)
                if has_subject_field and not self._scope_eligible(payload, ctx, scope_payload_keys=scope_keys):
                    ineligible_count += 1
                    continue
            # R2-03：explicit window 真正过滤（§18-20）
            if ctx.window_start or ctx.window_end:
                if requirement.data_type == "claims":
                    # claims 用正式 business timestamp（as_of）
                    business_time = payload.get("as_of")
                else:
                    business_time = payload.get("published_at")
                if business_time and not _in_window(business_time, ctx.window_start, ctx.window_end):
                    ineligible_count += 1
                    continue
            published = payload.get("published_at")
            if _iso_gt(published, ctx.as_of):
                ineligible_count += 1
                continue
            # claims 的 as_of 不得晚于请求 cutoff（§115）
            claim_as_of = payload.get("as_of")
            if _iso_gt(claim_as_of, ctx.as_of):
                ineligible_count += 1
                continue
            if self._tier_applicable(ctx, spec):
                tier, warn = provenance.resolve(payload, self._prov_strategy(ctx, spec), view)
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
        if self._cov_strategy(ctx, spec) == "SINGLETON_TARGET":
            coverage = 1.0 if eligible else 0.0
        elif self._cov_strategy(ctx, spec) == "OPEN_WORLD":
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

    # ---------- R3-03：EvidenceScopeResolver ----------

    def _evidence_scope_ok(self, payload: Dict[str, Any], ctx, view) -> bool:
        """Evidence subject/industry scope 经 RawItem provenance 校验（§25-29）。

        - global scope：无需 join（但仍走 PIT/tier/freshness/canonical）。
        - subject/industry：Evidence.raw_item_id → RawItem.entities；
          RawItem 无法解引用 → ineligible（不得假设相关）。
        """
        scope_type = ctx.requirement.scope.scope_type
        if scope_type == "global":
            return True
        raw_item_id = payload.get("raw_item_id")
        if not raw_item_id:
            return False  # subject/industry Evidence 必须可解引用 raw_item
        entities = self._fetch_raw_item_entities(view, str(raw_item_id))
        if entities is None:
            return False  # raw_item 缺失 → ineligible
        if scope_type in ("subject", "benchmark"):
            if not ctx.entity_ids:
                return False
            return any(str(e) in ctx.entity_ids for e in entities)
        if scope_type == "industry":
            if not ctx.industry_ids:
                return False
            if any(str(e) in ctx.industry_ids for e in entities):
                return True
            companies = [str(e) for e in entities if str(e).startswith("company:")]
            if companies and self._company_belongs_to_industry(view, companies, ctx.industry_ids):
                return True
            return False
        if scope_type == "peers":
            if not ctx.peer_entity_ids:
                return False
            return any(str(e) in ctx.peer_entity_ids for e in entities)
        return False  # watchlist/scenario 未知 scope → fail closed

    def _fetch_raw_item_entities(self, view, raw_item_id: str) -> Optional[List[str]]:
        """RawItem.entities 确定性解引用（只读）。"""
        has_table = getattr(view, "has_table", None)
        if has_table is None or not has_table("raw_items"):
            return None
        try:
            rows = view.query(
                "SELECT payload FROM raw_items "
                "WHERE json_extract(payload, '$.raw_item_id') = ?",
                (raw_item_id,),
            )
        except Exception:  # noqa: BLE001
            return None
        if not rows:
            return None
        payload = rows[0]["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        entities = payload.get("entities") if isinstance(payload, dict) else None
        if not entities:
            return []
        return [str(e) for e in entities]

    def _company_belongs_to_industry(self, view, companies: List[str],
                                     industry_ids: List[str]) -> bool:
        """company → valid CompanyProfile → requested industry membership（确定性证明）。"""
        has_table = getattr(view, "has_table", None)
        if has_table is None or not has_table("company_profiles"):
            return False
        try:
            rows = view.query("SELECT payload FROM company_profiles")
        except Exception:  # noqa: BLE001
            return False
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    continue
            if not isinstance(payload, dict):
                continue
            if str(payload.get("entity_id")) not in companies:
                continue
            ids = payload.get("industry_ids") or []
            if isinstance(ids, str):
                ids = [ids]
            if any(str(i) in industry_ids for i in ids):
                return True
        return False


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
            if _iso_gt(valid_from, ctx.as_of):
                ineligible_count += 1
                continue
            if _iso_le(valid_to, ctx.as_of):
                ineligible_count += 1
                continue
            eligible.append(payload)
            ref = payload.get("entity_id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        # R3-02/§22：symbol 必须来自可证明 authority（SecurityProfile.symbol），
        # 非 entities payload 直接字段；确定性 join 进 eligible payloads 供 projector 判定
        if eligible:
            symbols = self._resolve_symbols(view, eligible)
            for payload in eligible:
                if symbols.get(str(payload.get("entity_id"))):
                    payload["security_symbol"] = symbols[str(payload.get("entity_id"))]
        # R3.1-04：coverage 必须服从 binding.coverage_strategy（§27-31）：
        # subject → SINGLETON_TARGET（1.0/0.0）；industry/global → OPEN_WORLD（null，
        # 本阶段无完整权威 denominator，不得"一条映射 → 1.0"）。
        cov = self._cov_strategy(ctx, spec)
        if cov == "SINGLETON_TARGET":
            coverage = 1.0 if eligible else 0.0
        else:
            coverage = None  # OPEN_WORLD：coverage_ratio = null（§28/§30-31）
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              [], available, coverage, [] if coverage is not None
                              else [COVERAGE_NOT_MEASURABLE], None)

    def _resolve_symbols(self, view, entities) -> dict:
        """Entity → SecurityProfile → SecurityProfile.symbol 确定性映射（只读）。"""
        has_table = getattr(view, "has_table", None)
        if has_table is None or not has_table("security_profiles"):
            return {}
        result: dict = {}
        try:
            rows = view.query("SELECT payload FROM security_profiles")
        except Exception:  # noqa: BLE001
            return {}
        entity_ids = {str(e.get("entity_id")) for e in entities}
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    continue
            if not isinstance(payload, dict):
                continue
            company = payload.get("company_entity_id")
            symbol = payload.get("symbol")
            if company and symbol and str(company) in entity_ids:
                result[str(company)] = str(symbol)
        return result

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
            if _iso_gt(created, ctx.as_of):
                ineligible_count += 1
                continue
            # §42：tier via evidence_ids → Evidence provenance（无法证明 → SOURCE_TIER_UNPROVEN）
            if self._tier_applicable(ctx, spec):
                tier, warn = provenance.resolve(payload, self._prov_strategy(ctx, spec), view)
                if tier is None:
                    ineligible_count += 1
                    continue
                if _TIER_ORDER[tier] > _TIER_ORDER[requirement.minimum_source_tier]:
                    ineligible_count += 1
                    continue
            eligible.append(payload)
            ref = payload.get("finding_id") or payload.get("id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)
        # R3.1-08：coverage 走 binding（§59）；research_findings → SINGLETON_TARGET
        if self._cov_strategy(ctx, spec) == "SINGLETON_TARGET":
            coverage = 1.0 if eligible else 0.0
        else:
            coverage = None
        return self._finalize(requirement, spec, eligible, ineligible_count, refs,
                              [], available, coverage,
                              [] if coverage is not None else [COVERAGE_NOT_MEASURABLE], None)

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
            # §9：trade_date 为 date-only 语义，与 as_of 日期部分显式比较（非 naive datetime）
            try:
                trade_day = date.fromisoformat(str(trade_date))
                as_of_date = parse_iso(ctx.as_of).date()
            except (TypeError, ValueError):
                ineligible_count += 1
                continue
            if trade_day > as_of_date:
                ineligible_count += 1
                continue
            # §44：bar tier via accepted manifest（bar symbol/date → manifest.source_id →
            # SourceRegistry tier）；无匹配 accepted manifest → SOURCE_TIER_UNPROVEN
            if self._tier_applicable(ctx, spec):
                tier, warn = provenance.resolve(payload, self._prov_strategy(ctx, spec), view)
                if tier is None:
                    ineligible_count += 1
                    continue
                if _TIER_ORDER[tier] > _TIER_ORDER[requirement.minimum_source_tier]:
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
    """knowledge_graph_snapshot（复用既有 Graph lifecycle/query authority，§62-68 / R2-09）。

    industry scope：实际调用 GraphQueryService.query_graph(root_node_id=industry_id, as_of)
    生成真实 node_refs/edge_refs（§48-49）。root 存在但未执行 query → 不得声称 edge_refs。
    global scope：现有公共 API 无合法 global snapshot 读取 → fail closed（§51）。
    """

    data_types = ("knowledge_graph_snapshot",)

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        graph_query = getattr(view, "graph_query_service", None)
        history = getattr(view, "graph_history_service", None)
        if graph_query is None or history is None:
            return self._miss(requirement, [GRAPH_SCOPE_UNRESOLVED, "GRAPH_AUTHORITY_UNAVAILABLE"])
        # global scope：无合法 global snapshot 读取 → fail closed（§51/§67）
        if ctx.requirement.scope.scope_type == "global":
            return self._miss(requirement, [GRAPH_SCOPE_UNRESOLVED, "GLOBAL_SNAPSHOT_UNPROVEN"])
        # industry scope：identity resolution + query_graph 实证
        if not ctx.industry_ids:
            return self._miss(requirement, [SCOPE_MISMATCH, "industry", GRAPH_SCOPE_UNRESOLVED])
        industry_id = ctx.industry_ids[0]
        node_refs: List[str] = []
        edge_refs: List[str] = []
        try:
            resolved = history.resolve_node_as_of(industry_id, ctx.as_of)
            if resolved is None:
                return self._miss(requirement, [GRAPH_SCOPE_UNRESOLVED, f"ROOT_MISSING:{industry_id}"])
            result = graph_query.query_graph(
                root_node_id=industry_id, as_of=ctx.as_of,
                max_depth=1, direction="both",
            )
            if result is None:
                return self._miss(requirement, [GRAPH_SCOPE_UNRESOLVED, f"QUERY_FAILED:{industry_id}"])
            node_refs = self._extract_node_ids(result)
            edge_refs = self._extract_edge_ids(result)
        except Exception as exc:  # noqa: BLE001
            return self._miss(requirement, [GRAPH_SCOPE_UNRESOLVED, f"GRAPH_READ_FAILED:{type(exc).__name__}"])
        available = {"node_refs", "edge_refs", "as_of", "industry_id"}
        if not node_refs:
            # query 成功但无 node：edge_refs 字段存在性由 query 结果证明；不伪造 ID（§50）
            available.add("node_refs")  # 空结果仍可证明字段存在
        missing = [f for f in requirement.minimum_fields if f not in available]
        warnings = [COVERAGE_NOT_MEASURABLE]
        if missing:
            warnings.append(MISSING_REQUIRED_FIELDS)
        status = "PARTIAL" if missing or requirement.minimum_coverage > 0 else "READY"
        # R3.1-05：仅在实际 Graph query 被证明后生成 projectable authority payload（§34）：
        # 供 runtime canonical projector 判定 node_refs/edge_refs/as_of/industry_id，
        # 不得 synthetic fake IDs；空结果不伪造 payload（字段存在性由 available 证明）。
        eligible_payloads: List[Dict[str, Any]] = []
        if node_refs or edge_refs:
            eligible_payloads.append({
                "node_refs": list(node_refs),
                "edge_refs": list(edge_refs),
                "as_of": ctx.as_of,
                "industry_id": industry_id,
            })
        return ReadinessCheckResult(
            status=status, available_fields=sorted(available), coverage_ratio=None,
            eligible_record_count=1 if node_refs else 0, ineligible_record_count=0,
            source_tiers_present=[], record_refs=node_refs[:50],
            warnings=warnings, freshness_age_seconds=None,
            eligible_payloads=eligible_payloads,
        )

    @staticmethod
    def _extract_node_ids(result) -> List[str]:
        """从 query_graph 结果提取真实 node ids。"""
        ids: List[str] = []
        nodes = getattr(result, "nodes", None)
        if isinstance(nodes, list):
            for n in nodes:
                nid = getattr(n, "node_id", None) or (n.get("node_id") if isinstance(n, dict) else None)
                if nid:
                    ids.append(str(nid))
        elif isinstance(result, dict):
            nodes = result.get("nodes") or []
            for n in nodes:
                nid = n.get("node_id") if isinstance(n, dict) else getattr(n, "node_id", None)
                if nid:
                    ids.append(str(nid))
        return ids

    @staticmethod
    def _extract_edge_ids(result) -> List[str]:
        ids: List[str] = []
        edges = getattr(result, "edges", None)
        if isinstance(edges, list):
            for e in edges:
                eid = getattr(e, "edge_id", None) or (e.get("edge_id") if isinstance(e, dict) else None)
                if eid:
                    ids.append(str(eid))
        elif isinstance(result, dict):
            edges = result.get("edges") or []
            for e in edges:
                eid = e.get("edge_id") if isinstance(e, dict) else getattr(e, "edge_id", None)
                if eid:
                    ids.append(str(eid))
        return ids


class RunArtifactChecker(ReadinessChecker):
    """run_artifacts（authority=runs_root 正式 lineage，R2-13）。

    禁止"目录数 = readiness"。必须验证正式 task.json / validation.json lineage：
    - directory id == task_id
    - task completed
    - eligible scenario
    - validation pass-equivalent
    - business cutoff <= as_of
    若 request 指定 previous_run_ids：只检查这些 requested runs。
    """

    data_types = ("run_artifacts",)

    def check(self, ctx, requirement, view, provenance) -> ReadinessCheckResult:
        spec = get_spec(requirement.data_type)
        runs_root = getattr(view, "runs_root", None)
        if runs_root is None or not runs_root.exists():
            return self._miss(requirement, [NO_ELIGIBLE_RECORDS])
        # R3-05：previous_run_ids 专用 context 字段（§37-39）
        previous_run_ids = getattr(ctx, "previous_run_ids", None)
        if previous_run_ids is None:
            previous_run_ids = []
        # R3.1-02：deterministic 去重（保留首次出现；重复 ID 不得扭曲 denominator，§18）
        seen: set = set()
        unique_requested: List[str] = []
        for run_id in previous_run_ids:
            if run_id not in seen:
                seen.add(run_id)
                unique_requested.append(run_id)
        eligible_meta: List[Dict[str, Any]] = []
        ineligible_count = 0
        for run_id in unique_requested:
            meta = self._valid_artifact_meta(runs_root, run_id, ctx.as_of)
            if meta is not None:
                eligible_meta.append(meta)
            else:
                ineligible_count += 1
        # 无 requested prior-run set → 不得扫描全部 runs（§17）；MISSING + coverage null
        if not unique_requested:
            return self._miss(requirement, [NO_ELIGIBLE_RECORDS, "NO_REQUESTED_RUNS"])
        # R3.1-02：coverage = valid requested / unique requested（§16）
        coverage = len(eligible_meta) / len(unique_requested) if unique_requested else None
        available = {"task_id", "run_id"}
        # run_id 来自正式 scenario_execution_result.json（§20-22），非目录名伪造
        refs = [m["run_id"] for m in eligible_meta]
        if not eligible_meta:
            return ReadinessCheckResult(
                status="MISSING", available_fields=sorted(available),
                coverage_ratio=coverage, eligible_record_count=0,
                ineligible_record_count=ineligible_count,
                source_tiers_present=[], record_refs=[],
                warnings=[NO_ELIGIBLE_RECORDS, "NO_VALID_REQUESTED_RUNS"],
                freshness_age_seconds=None,
                eligible_payloads=[],
            )
        # §19：minimum_coverage 必须真实影响 RunArtifact readiness（PARTIAL + COVERAGE_BELOW_MINIMUM）
        status = "READY" if available.issuperset(requirement.minimum_fields) else "PARTIAL"
        warnings: List[str] = []
        if requirement.minimum_coverage > 0 and coverage < requirement.minimum_coverage:
            status = "PARTIAL"
            warnings.append(COVERAGE_BELOW_MINIMUM)
        return ReadinessCheckResult(
            status=status,
            available_fields=sorted(available),
            coverage_ratio=coverage,
            eligible_record_count=len(eligible_meta), ineligible_record_count=ineligible_count,
            source_tiers_present=[], record_refs=refs[:50],
            warnings=warnings,
            freshness_age_seconds=None,
            eligible_payloads=eligible_meta,
        )

    def _valid_artifact_meta(self, runs_root, run_id: str, as_of: str) -> Optional[Dict[str, Any]]:
        """复用共享 lineage helper（review.prior_run_lineage，§40-42）校验 prior run；
        返回 lineage 元数据（含正式 task_id/run_id）。
        R3.1-03：run_id 必须由 scenario_execution_result.json 正式证明（§20-23），
        禁止 directory-name fallback；validation_status 与共享 acceptance 必须一致。
        """
        from research_os.review.prior_run_lineage import (
            extract_business_cutoff,
            validate_execution_result,
            validate_prior_run,
        )
        from research_os.utils.time import parse_iso
        try:
            as_of_dt = parse_iso(as_of)
        except ValueError:
            return None
        run_dir = runs_root / run_id
        tdata = validate_prior_run(run_dir, run_id)
        if tdata is None:
            return None
        scenario = str(tdata.get("scenario") or "").strip()
        cutoff_dt = extract_business_cutoff(tdata, run_dir, scenario, as_of_dt)
        if cutoff_dt is None or cutoff_dt > as_of_dt:
            return None  # business cutoff 无法证明或晚于 as_of → reject
        # R3.1-03：run_id 必须由正式 scenario_execution_result.json 证明（§20-22），
        # 禁止 directory-name fallback；validation_status 一致性由共享 helper 校验（§23/§25）。
        rdata = validate_execution_result(run_dir, run_id)
        if rdata is None:
            return None
        return {
            "task_id": str(rdata.get("task_id") or "").strip(),
            "run_id": str(rdata.get("run_id") or "").strip(),
            "scenario": scenario,
            "business_cutoff": cutoff_dt.isoformat(timespec="seconds"),
        }


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


def _iso_gt(a: Optional[str], b: Any) -> bool:
    """R3-06/R3.1-01：timezone-aware datetime 比较（a > b）；无法解析 → fail-closed。

    a 为 payload 时间字段（str）；b 为 as_of（str 或已 parse 的 naive datetime，
    语义 Asia/Shanghai）。date-only（YYYY-MM-DD）显式视为当天 00:00 Asia/Shanghai，
    不得以 naive datetime 与不同语义混合（§9）。
    """
    if a is None:
        return False
    from research_os.utils.time import parse_iso
    a_dt = _parse_dt(a)
    if a_dt is None:
        return True  # 无法解析 → fail-closed（视为 ineligible）
    b_dt = _as_dt(b)
    if b_dt is None:
        return True  # as_of 无法解析 → fail-closed
    return a_dt > b_dt


def _iso_le(a: Optional[str], b: Any) -> bool:
    """R3-06/R3.1-01：timezone-aware datetime 比较（a <= b）；date-only 同 _iso_gt 规则。"""
    if a is None:
        return False
    from research_os.utils.time import parse_iso
    a_dt = _parse_dt(a)
    if a_dt is None:
        return True  # 无法解析 → fail-closed
    b_dt = _as_dt(b)
    if b_dt is None:
        return True
    return a_dt <= b_dt


def _parse_dt(value: str) -> Optional[Any]:
    """str → Asia/Shanghai 语义 naive datetime；date-only → 当天 00:00（§9）。"""
    try:
        return parse_iso(value)
    except ValueError:
        return _parse_date_only(value)
def _parse_date_only(value: str) -> Optional[Any]:
    """date-only（YYYY-MM-DD）→ 当天 00:00 Asia/Shanghai 语义的 naive datetime（§9）。"""
    from datetime import date, datetime as _dt, time
    try:
        d = date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return _dt.combine(d, time(0, 0))


def _as_dt(value: Any) -> Optional[Any]:
    """str → parse_iso；datetime 原样；无法解析 → None。"""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return parse_iso(value)
        except ValueError:
            return _parse_date_only(value)
    if hasattr(value, "tzinfo"):  # datetime
        return value
    return None



def _in_window(value: str, start: Optional[str], end: Optional[str]) -> bool:
    """[start, end) 窗口语义（R3-06：parse_iso 后按时间比较，禁止字典序）。"""
    if not start and not end:
        return True
    from research_os.utils.time import parse_iso
    try:
        value_dt = parse_iso(value)
    except ValueError:
        return False  # 无法解析 → fail closed
    if start:
        try:
            if value_dt < parse_iso(start):
                return False
        except ValueError:
            return False
    if end:
        try:
            if value_dt >= parse_iso(end):
                return False
        except ValueError:
            return False
    return True
