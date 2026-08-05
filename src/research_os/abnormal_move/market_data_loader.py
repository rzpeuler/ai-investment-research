"""市场数据加载与人工日线导入（Phase 3 任务书 3.1-3.5 节）。

统一 MarketDailyOhlcv 接口 + 人工导入首版：
- `MarketDataLoader.load_daily()`：从正式日线表读取标准化 Bar（异动分析唯一入口）
- `DailyImportService`：CSV/Parquet 解析 -> 逐行质量检查 -> Manifest 落库 -> 正式表写入
- 质量检查：日期格式、重复键、OHLC 关系、负值、停牌缺口、交易日
- 失败导入不写正式日线表；不允许静默修改用户数据；dry-run 零副作用

快照（MarketRealtimeSnapshot）不得进入本模块任何日级计算。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from research_os.models import MarketDailyOhlcv, MarketDailySeriesManifest
from research_os.storage import Database
from research_os.utils.id import new_uuid

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUIRED_FIELDS = ["symbol", "trade_date", "open", "high", "low", "close", "volume"]
OPTIONAL_FIELDS = ["amount", "turnover_rate", "previous_close", "suspension_status",
                   "limit_status", "adjustment_factor"]


def _parse_date(value: str) -> Optional[date]:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class TradingCalendar:
    """内置简单交易日历：周一至周五，可排除节假日集合。

    首版为人工导入服务；自动来源验证里程碑不依赖本日历。
    """

    def __init__(self, calendar_id: str = "cn-exchange", version: str = "v1",
                 holidays: Optional[Set[str]] = None):
        self.calendar_id = calendar_id
        self.version = version
        self.holidays: Set[str] = set(holidays or {})

    def is_trading_day(self, d: date) -> bool:
        if d.weekday() >= 5:
            return False
        return d.isoformat() not in self.holidays

    def previous_trading_day(self, d: date) -> Optional[date]:
        cursor = d - timedelta(days=1)
        for _ in range(14):
            if self.is_trading_day(cursor):
                return cursor
            cursor -= timedelta(days=1)
        return None

    def next_trading_day(self, d: date) -> Optional[date]:
        cursor = d + timedelta(days=1)
        for _ in range(14):
            if self.is_trading_day(cursor):
                return cursor
            cursor += timedelta(days=1)
        return None

    def trading_days_between(self, start: date, end: date) -> List[date]:
        days = []
        cursor = start
        while cursor <= end:
            if self.is_trading_day(cursor):
                days.append(cursor)
            cursor += timedelta(days=1)
        return days


@dataclass
class RowCheck:
    """单行质量检查结果。"""
    row: Dict[str, Any]
    issues: List[str] = field(default_factory=list)
    rejected: bool = False


class DailyRowValidator:
    """逐行质量检查（任务书 3.3：日期、重复键、OHLC 关系、负值、停牌缺口、交易日）。"""

    def __init__(self, calendar: TradingCalendar):
        self.calendar = calendar

    def check_row(self, row: Dict[str, Any], seen_keys: Set[str]) -> RowCheck:
        issues: List[str] = []
        symbol = str(row.get("symbol", "")).strip()
        if not symbol:
            issues.append("symbol 缺失")

        trade_date_raw = row.get("trade_date")
        d = _parse_date(trade_date_raw) if isinstance(trade_date_raw, str) else None
        if d is None:
            issues.append(f"trade_date 非法: {trade_date_raw!r}")
        else:
            if not self.calendar.is_trading_day(d):
                issues.append(f"{d.isoformat()} 非交易日（周末或节假日）")

        numbers = {}
        for f in ("open", "high", "low", "close", "volume"):
            v = _to_float(row.get(f))
            if v is None:
                issues.append(f"{f} 缺失或非数值: {row.get(f)!r}")
                continue
            numbers[f] = v
            if v < 0:
                issues.append(f"{f} 为负值: {v}")
        if "volume" in numbers and numbers["volume"] == 0:
            issues.append("volume 为 0（停牌日请勿导入价格行；若确为停牌请单独标记）")

        # OHLC 关系
        if all(f in numbers for f in ("open", "high", "low", "close")):
            o, h, l, c = (numbers[f] for f in ("open", "high", "low", "close"))
            if not (l <= o <= h):
                issues.append(f"OHLC 关系违反: open={o} 不在 [low={l}, high={h}]")
            if not (l <= c <= h):
                issues.append(f"OHLC 关系违反: close={c} 不在 [low={l}, high={h}]")
            if any(v <= 0 for v in (o, h, l, c)):
                issues.append("价格必须为正")

        # 重复键
        key = f"{symbol}|{trade_date_raw}"
        if symbol and trade_date_raw:
            if key in seen_keys:
                issues.append(f"重复键: {symbol} {trade_date_raw}")
            seen_keys.add(key)

        rejected = bool(issues)
        return RowCheck(row=row, issues=issues, rejected=rejected)


@dataclass
class ImportPreview:
    """dry-run 预览结果（零副作用）。"""
    file_name: str
    adjustment_method: str
    calendar_id: str
    rows_total: int
    rows_accepted: int
    rows_rejected: int
    symbols: List[str]
    date_start: Optional[str]
    date_end: Optional[str]
    duplicate_keys: List[str]
    issues: List[str]
    warnings: List[str]


@dataclass
class ImportResult:
    """导入结果。"""
    preview: ImportPreview
    manifest: Optional[MarketDailySeriesManifest]
    persisted: bool
    written_rows: int
    validation_status: str


class DailyImportService:
    """人工日线导入服务：解析 -> 校验 -> dry-run 或持久化。"""

    def __init__(self, db: Database, calendar: Optional[TradingCalendar] = None):
        self.db = db
        self.calendar = calendar or TradingCalendar()

    # ---------- 解析 ----------

    def _parse_file(self, path: Path) -> List[Dict[str, Any]]:
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return self._parse_csv(path)
        if suffix in (".parquet", ".pq"):
            return self._parse_parquet(path)
        raise ValueError(f"不支持的文件格式: {suffix}（支持 .csv；.parquet 需安装 pandas+pyarrow）")

    @staticmethod
    def _parse_csv(path: Path) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise ValueError("CSV 无表头")
            missing = [f for f in REQUIRED_FIELDS if f not in reader.fieldnames]
            if missing:
                raise ValueError(f"CSV 缺少必填列: {missing}（需要 {REQUIRED_FIELDS}）")
            for line_no, raw in enumerate(reader, start=2):
                row = {k: (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
                rows.append(row)
        if not rows:
            raise ValueError("CSV 无数据行")
        return rows

    @staticmethod
    def _parse_parquet(path: Path) -> List[Dict[str, Any]]:
        try:
            import pandas  # noqa: F401
            import pyarrow  # noqa: F401
        except ImportError:
            raise ValueError(
                "parquet 导入需要 pandas + pyarrow，请先安装："
                "pip install pandas pyarrow"
            ) from None
        import pandas as pd

        df = pd.read_parquet(str(path))
        missing = [f for f in REQUIRED_FIELDS if f not in df.columns]
        if missing:
            raise ValueError(f"Parquet 缺少必填列: {missing}")
        return df.astype(object).to_dict(orient="records")

    # ---------- 校验与预览 ----------

    def _build_preview(self, path: Path, checks: List[RowCheck],
                       adjustment: str, calendar_id: str) -> ImportPreview:
        accepted = [c for c in checks if not c.rejected]
        rejected = [c for c in checks if c.rejected]
        dup_keys = [c.issues[0].split(": ", 1)[1] for c in rejected
                    if any(i.startswith("重复键") for i in c.issues)]

        symbols = sorted({c.row.get("symbol", "").strip() for c in checks if c.row.get("symbol")})
        dates = [d for d in (_parse_date(c.row.get("trade_date")) for c in checks) if d is not None]
        date_start = min(dates).isoformat() if dates else None
        date_end = max(dates).isoformat() if dates else None

        issues = []
        for c in rejected:
            issues.extend(f"{c.row.get('symbol', '?')} {c.row.get('trade_date', '?')}: {i}" for i in c.issues)
        warnings = []

        # 停牌缺口 / 数据缺失：对每个 symbol，相邻交易日之间跨过工作日
        for sym in symbols:
            sym_dates = sorted({_parse_date(c.row["trade_date"]) for c in checks
                                if c.row.get("symbol") == sym and _parse_date(c.row["trade_date"])})
            for a, b in zip(sym_dates, sym_dates[1:]):
                gap = [d for d in self.calendar.trading_days_between(a, b)
                       if a < d < b]
                if gap:
                    warnings.append(
                        f"{sym}: {a.isoformat()} 与 {b.isoformat()} 之间缺失交易日 "
                        f"{len(gap)} 个（停牌缺口或数据缺失，未自动补值）"
                    )

        return ImportPreview(
            file_name=path.name, adjustment_method=adjustment,
            calendar_id=calendar_id, rows_total=len(checks),
            rows_accepted=len(accepted), rows_rejected=len(rejected),
            symbols=symbols, date_start=date_start, date_end=date_end,
            duplicate_keys=dup_keys, issues=issues[:200], warnings=warnings,
        )

    def _checksum(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    # ---------- 主入口 ----------

    def import_file(self, path: str | Path, source_id: str = "manual_import",
                    adjustment: str = "none", calendar_id: str = "cn-exchange",
                    imported_by: str = "user", data_version: Optional[str] = None,
                    dry_run: bool = False) -> ImportResult:
        """导入日线文件。dry_run=True 时零副作用（不写库、不建 manifest）。"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        if adjustment not in ("none", "qfq", "hfq"):
            raise ValueError(f"复权口径非法: {adjustment}（none/qfq/hfq）")

        self.calendar.calendar_id = calendar_id
        rows = self._parse_file(path)
        validator = DailyRowValidator(self.calendar)
        seen_keys: Set[str] = set()
        checks = [validator.check_row(r, seen_keys) for r in rows]
        preview = self._build_preview(path, checks, adjustment, calendar_id)
        if dry_run:
            return ImportResult(preview=preview, manifest=None,
                                persisted=False, written_rows=0,
                                validation_status="preview")

        # 持久化：manifest + import_rows + 正式表（仅 accepted 行）
        now = datetime.now().isoformat(timespec="seconds")
        version = data_version or f"manual-{preview.date_start or '?'}-{preview.date_end or '?'}"
        validation_status = "rejected" if preview.rows_rejected > 0 else "accepted"
        available_optional = sorted({
            f for c in checks for f in OPTIONAL_FIELDS
            if c.row.get(f) not in (None, "")
        })
        manifest = MarketDailySeriesManifest(
            import_id=new_uuid(),
            source_id=source_id,
            source_kind="manual_import",
            file_name=preview.file_name,
            file_checksum=self._checksum(path),
            imported_at=now,
            imported_by=imported_by,
            symbols=preview.symbols,
            date_start=preview.date_start or "",
            date_end=preview.date_end or "",
            row_count=preview.rows_total,
            adjustment_method=adjustment,  # type: ignore[arg-type]
            adjustment_description=("不复权" if adjustment == "none"
                                    else ("前复权" if adjustment == "qfq" else "后复权")),
            calendar_id=calendar_id,
            calendar_version=self.calendar.version,
            currency="CNY",
            price_unit="yuan",
            volume_unit="shares",
            available_optional_fields=available_optional,
            data_version=version,
            validation_status=validation_status,  # type: ignore[arg-type]
            validation_errors=preview.issues[:200],
            warnings=preview.warnings,
        )
        errs = _validate_manifest(manifest)
        if errs:
            raise ValueError(f"Manifest 未通过 Schema 校验: {errs}")

        with self.db._conn:  # noqa: SLF001 —— 同一进程内的事务边界
            self.db.upsert(manifest)
            skipped = 0
            written = 0
            for c in checks:
                if c.rejected:
                    self._insert_import_row(manifest.import_id, c.row,
                                            "rejected", c.issues)
                    continue
                bar = self._row_to_bar(c.row, manifest.import_id, version, adjustment)
                self._insert_import_row(manifest.import_id, c.row,
                                        "accepted", c.issues)
                if self._insert_daily_bar(bar):
                    written += 1
                else:
                    skipped += 1
            if skipped > 0:
                manifest.warnings.append(
                    f"{skipped} 行与正式日线表已有数据键冲突（symbol+trade_date），"
                    "保留既有数据未覆盖（不静默修改用户数据）"
                )
                self.db.upsert(manifest)
        return ImportResult(preview=preview, manifest=manifest, persisted=True,
                            written_rows=written,
                            validation_status=validation_status)

    def _row_to_bar(self, row: Dict[str, Any], import_id: str,
                    data_version: str, adjustment: str) -> MarketDailyOhlcv:
        bar = MarketDailyOhlcv(
            bar_id=new_uuid(),
            symbol=str(row["symbol"]).strip(),
            trade_date=str(row["trade_date"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            amount=float(row["amount"]) if row.get("amount") not in (None, "") else None,
        )
        errs = _validate_bar(bar)
        if errs:
            raise ValueError(f"Bar 未通过 Schema 校验: {errs}（{bar.symbol} {bar.trade_date}）")
        return bar

    def _insert_import_row(self, import_id: str, row: Dict[str, Any],
                           status: str, issues: List[str]) -> None:
        self.db._conn.execute(  # noqa: SLF001
            "INSERT INTO market_daily_import_rows "
            "(import_id, symbol, trade_date, payload, row_status, issues) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (import_id, str(row.get("symbol", "")).strip(),
             str(row.get("trade_date", "")),
             json.dumps(row, ensure_ascii=False, default=str),
             status, json.dumps(issues, ensure_ascii=False)),
        )

    def _insert_daily_bar(self, bar: MarketDailyOhlcv) -> bool:
        """写入正式日线表；键冲突时保留既有数据（不覆盖）。返回是否真实插入。

        Python sqlite3 的 cursor.rowcount 对 INSERT 恒为 1（不区分 DO NOTHING），
        因此使用显式存在性检查；人工导入规模下开销可忽略。
        """
        existing = self.db._conn.execute(  # noqa: SLF001
            "SELECT 1 FROM market_daily_ohlcv WHERE symbol = ? AND trade_date = ?",
            (bar.symbol, bar.trade_date),
        ).fetchone()
        if existing is not None:
            return False
        self.db._conn.execute(  # noqa: SLF001
            "INSERT INTO market_daily_ohlcv "
            "(bar_id, payload, symbol, trade_date, close) "
            "VALUES (?, ?, ?, ?, ?)",
            (bar.bar_id, json.dumps(bar.model_dump(), ensure_ascii=False),
             bar.symbol, bar.trade_date, bar.close),
        )
        return True


class MarketDataLoader:
    """统一日线接口（异动分析唯一入口，任务书 3.1）。"""

    def __init__(self, db: Database):
        self.db = db

    def load_daily(self, symbol: str, start: Optional[str] = None,
                   end: Optional[str] = None) -> List[MarketDailyOhlcv]:
        """读取正式日线表，返回按 trade_date 升序的标准化 Bar。"""
        sql = "SELECT payload FROM market_daily_ohlcv WHERE symbol = ?"
        params: List[Any] = [symbol]
        if start:
            sql += " AND trade_date >= ?"
            params.append(start)
        if end:
            sql += " AND trade_date <= ?"
            params.append(end)
        sql += " ORDER BY trade_date"
        rows = self.db.query(sql, tuple(params))
        bars = [MarketDailyOhlcv(**json.loads(r["payload"])) for r in rows]
        return bars

    def available_dates(self, symbol: str) -> List[str]:
        rows = self.db.query(
            "SELECT trade_date FROM market_daily_ohlcv WHERE symbol = ? ORDER BY trade_date",
            (symbol,),
        )
        return [r["trade_date"] for r in rows]

    def latest_trade_date(self, symbol: str) -> Optional[str]:
        row = self.db.query(
            "SELECT MAX(trade_date) AS d FROM market_daily_ohlcv WHERE symbol = ?",
            (symbol,),
        )
        return row[0]["d"] if row and row[0]["d"] else None


def _validate_manifest(m: MarketDailySeriesManifest) -> List[str]:
    from research_os.validators.schema_validator import validate_model
    return validate_model(m)


def _validate_bar(b: MarketDailyOhlcv) -> List[str]:
    from research_os.validators.schema_validator import validate_model
    return validate_model(b)
