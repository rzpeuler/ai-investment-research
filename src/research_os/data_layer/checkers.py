"""ReadinessCheckerRegistry 与 checker families（P7-D1）。

每个 Scenario Requirement 的 data_type 必须存在 checker（43/43 全覆盖）；
缺 checker 时抛 CONTROL_PLANE_CONFIGURATION_ERROR（fail closed），不得返回 MISSING。

判定顺序统一冻结（§22）：
1. Scope eligibility → 2. PIT eligibility → 3. Minimum fields → 4. Minimum coverage
→ 5. Minimum source/tier → 6. Freshness → 7. Final status

只读、零网络、零写入、零 LLM；dry-run 使用 open_read_only 或空 read view。
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from research_os.data_layer.context import ResolvedRequirementContext
from research_os.models import ScenarioDataRequirement

# ---------- 标准化 reason / warning 常量（§40） ----------

NO_ELIGIBLE_RECORDS = "NO_ELIGIBLE_RECORDS"
SCOPE_MISMATCH = "SCOPE_MISMATCH"
PIT_INELIGIBLE = "PIT_INELIGIBLE"
MISSING_REQUIRED_FIELDS = "MISSING_REQUIRED_FIELDS"
COVERAGE_BELOW_MINIMUM = "COVERAGE_BELOW_MINIMUM"
COVERAGE_NOT_MEASURABLE = "COVERAGE_NOT_MEASURABLE"
SOURCE_TIER_BELOW_MINIMUM = "SOURCE_TIER_BELOW_MINIMUM"
SOURCE_TIER_UNPROVEN = "SOURCE_TIER_UNPROVEN"
STALE_DATA = "STALE_DATA"
SOURCE_HEALTH_UNPROVEN = "SOURCE_HEALTH_UNPROVEN"
REQUEST_MATERIAL_PENDING_NORMALIZATION = "REQUEST_MATERIAL_PENDING_NORMALIZATION"

# 分层：S > A > B > C > D
_TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}


def _trading_days_between(start: str, end: str) -> List[str]:
    """known trading window 的确定性近似：工作日日历（周末排除，节假日留给后续治理）。

    仅当 start/end 为 ISO 且可解析时返回；无法解析返回空（调用方 → COVERAGE_NOT_MEASURABLE）。
    """
    from datetime import date, datetime, timedelta
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
    except ValueError:
        return []
    days: List[str] = []
    cur = s.date()
    end_date = e.date()
    while cur < end_date:
        if cur.weekday() < 5:
            days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


def _within_window(trade_date: str, window_start: str, window_end: str) -> bool:
    """trade_date（date-only 或 datetime）与 [start, end) 窗口比较；口径统一为日期。

    date-only 值视为当天任意时刻（该日属于窗口即计入）；datetime 值按 ISO 比较。
    """
    from datetime import datetime
    start_dt = datetime.fromisoformat(window_start)
    end_dt = datetime.fromisoformat(window_end)
    if "T" in trade_date or " " in trade_date:
        val = datetime.fromisoformat(trade_date)
        return start_dt <= val < end_dt
    # date-only：与窗口的日期边界比较
    return start_dt.date().isoformat() <= trade_date < end_dt.date().isoformat()


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
        if ";" in sql and not sql.strip().rstrip(";").endswith("SELECT"):
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
    """空 read view：dry-run 且 DB 不存在时使用（不创建 DB、不初始化）。"""

    def query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        return []

    def has_table(self, table: str) -> bool:
        return False


# ---------- checker families（§20） ----------

class ReadinessChecker(ABC):
    """checker 家族基类。data_types 声明支持的 data_type 集合。"""

    data_types: Tuple[str, ...] = ()
    source_tier_applicable: bool = True

    @abstractmethod
    def check(
        self,
        ctx: ResolvedRequirementContext,
        requirement: ScenarioDataRequirement,
        view: DataReadView,
    ) -> ReadinessCheckResult:
        ...

    def _tier_ok(self, present: List[str], minimum: str) -> Tuple[bool, List[str], List[str]]:
        """返回 (合格, eligible_tiers, ineligible_tiers)。无法证明 tier 时按 SOURCE_TIER_UNPROVEN。"""
        eligible, ineligible = [], []
        for tier in present:
            if tier not in _TIER_ORDER:
                ineligible.append(tier)
                continue
            if _TIER_ORDER[tier] <= _TIER_ORDER[minimum]:
                eligible.append(tier)
            else:
                ineligible.append(tier)
        return bool(eligible), eligible, ineligible

    def _scope_eligible(self, payload: Dict[str, Any], ctx) -> bool:
        """subject / industry scope 精确匹配（fail closed）；不匹配 → ineligible。"""
        scope_type = ctx.requirement.scope.scope_type
        if scope_type == "global":
            return True
        if scope_type in ("subject", "benchmark"):
            if not ctx.entity_ids:
                return False
            values = []
            for key in self.scope_payload_keys:
                v = payload.get(key)
                if v is None:
                    continue
                values.extend(v if isinstance(v, list) else [v])
            if not values:
                return False  # 无法证明属于 subject → ineligible（不猜测）
            return any(str(v) in ctx.entity_ids for v in values)
        if scope_type == "industry":
            if not ctx.industry_ids:
                return False
            values = []
            for key in self.industry_payload_keys:
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
            for key in self.scope_payload_keys:
                v = payload.get(key)
                if v is None:
                    continue
                values.extend(v if isinstance(v, list) else [v])
            if not values:
                return False
            return any(str(v) in ctx.peer_entity_ids for v in values)
        # watchlist / scenario 由上层（capability/planner）处理；此处不误判
        return True


class SqliteObjectChecker(ReadinessChecker):
    """通用 SQLite 对象 checker：按表查 payload，做 scope/PIT/字段/coverage 判定。

    PIT 列映射：published_at / effective_at / valid_from / event_time /
    observed_at / trade_date / created_at（按 data_type 领域解释，禁止万能 timestamp<=as_of）。
    """

    data_types: Tuple[str, ...] = ()
    table: str = ""
    pit_column: str = "published_at"   # 或 trade_date / created_at 等
    record_id_expr: str = "json_extract(payload, '$.raw_item_id')"  # record_ref 来源
    default_scope_column: str = ""      # 若表有 subject 列（如 symbol/company_entity_id）
    scope_payload_keys: Tuple[str, ...] = ("symbol", "company_entity_id", "entity_id", "subject")
    industry_payload_keys: Tuple[str, ...] = ("industry_id", "industry_ids")

    def check(self, ctx, requirement, view) -> ReadinessCheckResult:
        if not view.has_table(self.table):
            return self._miss(requirement, [f"TABLE_ABSENT:{self.table}"])
        if ctx.unresolved:
            return self._miss(requirement, [SCOPE_MISMATCH] + list(ctx.unresolved))

        clauses, params = [], []
        if self.default_scope_column and ctx.entity_ids:
            placeholders = ",".join("?" for _ in ctx.entity_ids)
            clauses.append(f"{self.default_scope_column} IN ({placeholders})")
            params.extend(ctx.entity_ids)
        if ctx.window_start and self.pit_column == "published_at":
            clauses.append(f"json_extract(payload, '$.published_at') >= ?")
            params.append(ctx.window_start)
            if ctx.window_end:
                clauses.append(f"json_extract(payload, '$.published_at') < ?")
                params.append(ctx.window_end)
        if self.pit_column == "trade_date":
            clauses.append(f"trade_date <= ?")
            params.append(ctx.as_of)
        elif self.pit_column == "created_at":
            clauses.append(f"json_extract(payload, '$.created_at') <= ?")
            params.append(ctx.as_of)

        where = " AND ".join(clauses) if clauses else "1=1"
        rows = view.query(f"SELECT payload FROM {self.table} WHERE {where}", tuple(params))

        eligible: List[Dict[str, Any]] = []
        ineligible_count = 0
        available: set[str] = set()
        tiers_present: set[str] = set()
        refs: List[str] = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    ineligible_count += 1
                    continue
            if not isinstance(payload, dict):
                ineligible_count += 1
                continue
            # scope eligibility：subject / industry 精确匹配（payload 级，fail closed）
            if not self._scope_eligible(payload, ctx):
                ineligible_count += 1
                continue
            # tier
            tier = payload.get("source_tier")
            if tier is None:
                tier = payload.get("tier")
            if self.source_tier_applicable and tier is not None:
                tiers_present.add(str(tier))
                ok, _, _ = self._tier_ok([str(tier)], requirement.minimum_source_tier)
                if not ok:
                    ineligible_count += 1
                    continue
            elif self.source_tier_applicable and tier is None:
                # 无法证明 provenance：quality ineligible（SOURCE_TIER_UNPROVEN）
                ineligible_count += 1
                continue
            eligible.append(payload)
            ref = payload.get("raw_item_id") or payload.get("id") or payload.get("bar_id")
            if ref:
                refs.append(str(ref))
            available.update(k for k in payload.keys() if payload.get(k) is not None)

        if not eligible:
            return ReadinessCheckResult(
                status="MISSING",
                eligible_record_count=0,
                ineligible_record_count=ineligible_count,
                source_tiers_present=sorted(tiers_present),
                coverage_ratio=0.0,
                warnings=[NO_ELIGIBLE_RECORDS, *(
                    [SOURCE_TIER_UNPROVEN] if ineligible_count and not tiers_present else [])],
            )
        return self._score(requirement, eligible, ineligible_count, refs, tiers_present, available)

    def _score(self, requirement, eligible, ineligible_count, refs, tiers_present, available):
        missing = [f for f in requirement.minimum_fields if f not in available]
        coverage = None
        warnings: List[str] = []
        if requirement.minimum_fields:
            coverage = len([f for f in requirement.minimum_fields if f in available]) / len(requirement.minimum_fields)
        if requirement.minimum_coverage > 0 and coverage is not None and coverage < requirement.minimum_coverage:
            warnings.append(COVERAGE_BELOW_MINIMUM)
        if missing:
            warnings.append(MISSING_REQUIRED_FIELDS)
        status = "PARTIAL" if missing else "READY"
        if status == "READY" and requirement.minimum_coverage > 0 and coverage is not None \
                and coverage < requirement.minimum_coverage:
            status = "PARTIAL"
        if status == "READY" and not eligible:
            status = "MISSING"
        return ReadinessCheckResult(
            status=status,
            available_fields=sorted(available),
            coverage_ratio=coverage,
            eligible_record_count=len(eligible),
            ineligible_record_count=ineligible_count,
            source_tiers_present=sorted(tiers_present),
            record_refs=refs,
            warnings=warnings,
        )

    def _miss(self, requirement, warnings: List[str]) -> ReadinessCheckResult:
        return ReadinessCheckResult(
            status="MISSING",
            coverage_ratio=0.0,
            warnings=warnings,
        )


class MarketSeriesChecker(SqliteObjectChecker):
    """日线 checker：trade_date PIT + available history + requested window。

    实时 snapshot 不冒充 daily history（数据源独立）。coverage = eligible dates /
    expected trading dates（known trading window）。
    """

    data_types = ("market_daily_ohlcv",)
    table = "market_daily_ohlcv"
    pit_column = "trade_date"
    default_scope_column = "symbol"

    def check(self, ctx, requirement, view) -> ReadinessCheckResult:
        if not view.has_table(self.table):
            return self._miss(requirement, [f"TABLE_ABSENT:{self.table}"])
        if not ctx.entity_ids:
            return self._miss(requirement, [SCOPE_MISMATCH, "subject"])
        bars: List[Dict[str, Any]] = []
        for symbol in ctx.entity_ids:
            rows = view.query(
                "SELECT payload FROM market_daily_ohlcv WHERE symbol = ? AND trade_date <= ?",
                (symbol, ctx.as_of),
            )
            for row in rows:
                payload = row["payload"]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except (TypeError, ValueError):
                        continue
                if isinstance(payload, dict):
                    bars.append(payload)
        if not bars:
            return ReadinessCheckResult(
                status="MISSING", coverage_ratio=0.0,
                warnings=[NO_ELIGIBLE_RECORDS, PIT_INELIGIBLE],
            )
        available_fields = sorted({k for b in bars for k in b.keys() if b.get(k) is not None})
        missing = [f for f in requirement.minimum_fields if f not in available_fields]
        warnings: List[str] = []
        if missing:
            warnings.append(MISSING_REQUIRED_FIELDS)
        # coverage：known trading window（requested window 内的交易日历）为 denominator
        per_symbol_dates = {}
        for b in bars:
            d = b.get("trade_date")
            if d:
                per_symbol_dates.setdefault(b.get("symbol", "?"), set()).add(d)
        coverage = None
        if ctx.window_start and ctx.window_end:
            expected = _trading_days_between(ctx.window_start, ctx.window_end)
            if expected:
                eligible_dates = set()
                for dates in per_symbol_dates.values():
                    eligible_dates |= {
                        d for d in dates
                        if _within_window(d, ctx.window_start, ctx.window_end)
                    }
                coverage = len(eligible_dates) / len(expected)
                coverage = max(0.0, min(1.0, coverage))
            else:
                coverage = None
                warnings.append(COVERAGE_NOT_MEASURABLE)
        else:
            coverage = None
            warnings.append(COVERAGE_NOT_MEASURABLE)
        status = "MISSING" if not bars else ("PARTIAL" if missing else "READY")
        if status == "READY" and coverage is not None and requirement.minimum_coverage > 0 \
                and coverage < requirement.minimum_coverage:
            status = "PARTIAL"
            warnings.append(COVERAGE_BELOW_MINIMUM)
        if status == "READY" and requirement.minimum_coverage > 0 and coverage is None:
            # open-world / 无合法 denominator：minimum_coverage>0 时不得 READY
            status = "PARTIAL"
            warnings.append(COVERAGE_NOT_MEASURABLE)
        return ReadinessCheckResult(
            status=status,
            available_fields=available_fields,
            coverage_ratio=coverage,
            eligible_record_count=len(bars),
            ineligible_record_count=0,
            source_tiers_present=[],
            record_refs=[f"{b.get('symbol')}:{b.get('trade_date')}" for b in bars],
            warnings=warnings,
        )


class GraphSnapshotChecker(ReadinessChecker):
    """知识图谱只读快照 checker：version/as_of 约束读；零 Graph write。

    fail closed：industry scope 过滤、minimum_fields 检查、minimum_coverage
    （open-world 无合法 denominator → 若 min>0 降级）。
    """

    data_types = ("knowledge_graph_snapshot",)
    source_tier_applicable = False

    def check(self, ctx, requirement, view) -> ReadinessCheckResult:
        # 复用 GraphRepository 只读 count 路径（version/as_of 约束）；无连接时视为未就绪
        repo = getattr(view, "graph_repo", None)
        if repo is None:
            return ReadinessCheckResult(
                status="MISSING", coverage_ratio=None,
                warnings=[COVERAGE_NOT_MEASURABLE, "GRAPH_SNAPSHOT_UNAVAILABLE"],
            )
        try:
            node_count = repo.count_nodes() or 0
            edge_count = repo.count_edges() or 0
        except Exception:  # noqa: BLE001
            return ReadinessCheckResult(
                status="MISSING", coverage_ratio=None,
                warnings=[COVERAGE_NOT_MEASURABLE, "GRAPH_READ_FAILED"],
            )
        warnings: List[str] = []
        # industry scope：无 industry 上下文时不猜测（fail closed）
        if ctx.requirement.scope.scope_type == "industry" and not ctx.industry_ids:
            return ReadinessCheckResult(
                status="MISSING", coverage_ratio=None,
                warnings=[SCOPE_MISMATCH, "industry", COVERAGE_NOT_MEASURABLE],
            )
        if node_count == 0 and edge_count == 0:
            return ReadinessCheckResult(
                status="MISSING", coverage_ratio=0.0,
                warnings=[NO_ELIGIBLE_RECORDS],
            )
        # minimum_fields：industry_id / node_refs / edge_refs 等
        available_fields = ["node_refs", "edge_refs"]
        if ctx.industry_ids:
            available_fields.append("industry_id")
        missing = [f for f in requirement.minimum_fields if f not in available_fields]
        if missing:
            warnings.append(MISSING_REQUIRED_FIELDS)
        # coverage：open-world 无合法 denominator → None；min>0 时不得 READY
        coverage = None
        if requirement.minimum_coverage > 0:
            warnings.append(COVERAGE_NOT_MEASURABLE)
        status = "PARTIAL" if missing or (requirement.minimum_coverage > 0) else "READY"
        if status == "PARTIAL" and not missing and requirement.minimum_coverage == 0:
            status = "READY"
        return ReadinessCheckResult(
            status=status,
            available_fields=sorted(available_fields),
            coverage_ratio=coverage,
            eligible_record_count=node_count + edge_count,
            ineligible_record_count=0,
            source_tiers_present=[],
            record_refs=[],
            warnings=warnings,
        )


class RunArtifactChecker(ReadinessChecker):
    """Run 产物 checker：检查 reports/runs/ 下既有产物。"""

    data_types = ("run_artifacts",)
    source_tier_applicable = False

    def check(self, ctx, requirement, view) -> ReadinessCheckResult:
        runs_root = getattr(view, "runs_root", None)
        if runs_root is None or not runs_root.exists():
            return ReadinessCheckResult(
                status="MISSING", coverage_ratio=0.0,
                warnings=[NO_ELIGIBLE_RECORDS],
            )
        artifacts = []
        if runs_root.exists():
            artifacts = [p for p in runs_root.iterdir() if p.is_dir()]
        if not artifacts:
            return ReadinessCheckResult(
                status="MISSING", coverage_ratio=0.0,
                warnings=[NO_ELIGIBLE_RECORDS],
            )
        return ReadinessCheckResult(
            status="READY",
            available_fields=["task_id", "run_id"],
            coverage_ratio=None,
            eligible_record_count=len(artifacts),
            ineligible_record_count=0,
            source_tiers_present=[],
            record_refs=[a.name for a in artifacts[:50]],
            warnings=[COVERAGE_NOT_MEASURABLE],
        )


class CompositeChecker(ReadinessChecker):
    """复合 checker：组合多个 family（如 evidence + claims 共用 EvidenceContentChecker）。

    取最差状态（fail closed）：READY 最轻，SOURCE_UNHEALTHY 最重。
    """

    data_types: Tuple[str, ...] = ()
    inner: List[ReadinessChecker] = []

    def check(self, ctx, requirement, view) -> ReadinessCheckResult:
        results = [c.check(ctx, requirement, view) for c in self.inner]
        return max(results, key=lambda r: _STATUS_ORDER.index(r.status))


_STATUS_ORDER = ["READY", "PARTIAL", "MISSING", "STALE", "SOURCE_UNHEALTHY"]


# ---------- 具体 data_type → checker 映射 ----------

class EvidenceContentChecker(SqliteObjectChecker):
    """Evidence 内容 checker（evidence / claims / event_evidence / evidence_index）。"""

    data_types = ("evidence", "claims", "event_evidence", "evidence_index")
    table = "evidence"
    source_tier_applicable = False


class DocumentChecker(SqliteObjectChecker):
    """文档 checker（company_document / document_corpus / company_profile / security_profile）。"""

    data_types = ("company_document", "document_corpus")
    table = "document_records"
    source_tier_applicable = True


class ProfileChecker(SqliteObjectChecker):
    """主体 profile checker（company_profile / security_profile / industry_membership）。"""

    data_types = ("company_profile", "security_profile", "industry_membership")
    table = "company_profiles"
    pit_column = "created_at"
    source_tier_applicable = True


class FinancialChecker(SqliteObjectChecker):
    """财务 checker（financial_statement_data / peer_financial_data / market_valuation_snapshot）。"""

    data_types = ("financial_statement_data", "peer_financial_data", "market_valuation_snapshot")
    table = "financial_facts"
    pit_column = "created_at"
    source_tier_applicable = True


class AnnouncementChecker(SqliteObjectChecker):
    """公告/快讯/宏观 checker。"""

    data_types = ("news_flash", "company_announcement", "macro_data",
                  "brief_event_content", "brief_attention_content")
    table = "raw_items"
    source_tier_applicable = True


class EntityMappingChecker(SqliteObjectChecker):
    data_types = ("entity_mapping",)
    table = "entities"
    source_tier_applicable = False


class ResearchFindingsChecker(SqliteObjectChecker):
    data_types = ("research_findings",)
    table = "research_findings"
    pit_column = "created_at"
    source_tier_applicable = False


class ReadinessCheckerRegistry:
    """data_type → checker 映射；缺 checker 抛 CONTROL_PLANE_CONFIGURATION_ERROR。"""

    def __init__(self, checkers: Optional[List[ReadinessChecker]] = None):
        self._map: Dict[str, ReadinessChecker] = {}
        selected = checkers if checkers is not None else _DEFAULT_CHECKERS
        for checker in selected:
            for dtype in checker.data_types:
                self._map[dtype] = checker

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


_DEFAULT_CHECKERS: List[ReadinessChecker] = [
    MarketSeriesChecker(),
    GraphSnapshotChecker(),
    RunArtifactChecker(),
    EvidenceContentChecker(),
    DocumentChecker(),
    ProfileChecker(),
    FinancialChecker(),
    AnnouncementChecker(),
    EntityMappingChecker(),
    ResearchFindingsChecker(),
]
