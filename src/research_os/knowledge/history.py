"""M7 Deterministic History Service：identity-scoped history + as_of resolution。

零 LLM / 零 Provider / 零 network。只做 single-identity history 与
single-identity as_of resolution（不是 M8 graph query engine）。

冻结语义（Decision #37）：
- append-only：所有 version 行只读，永不回写 vN
- 半开区间 [effective_from, effective_to)
  - effective_from = vN.valid_from（null = unbounded past）
  - effective_to   = min(vN.valid_to, vN+1.valid_from)（只有其一 / 均 null 对应规则）
  - effective_from > effective_to → HISTORY_INTERVAL_INVALID（fail-closed）
- derived lifecycle：superseded / expired / retired 全部派生，不 UPDATE 旧对象
  - retired：retire tombstone（node status=retired / edge origin change_type==retire_edge）
    且 as_of >= retire_at（valid_from == valid_to == retire_at）
  - superseded：存在已生效 successor（as_of >= successor.valid_from）
  - expired：无已生效 successor 且 valid_to != null 且 as_of >= valid_to
  - not_yet_valid：as_of < effective_from
- strict read：每行 JSON decode → top-level dict → JSON Schema → Pydantic →
  model_dump → JSON Schema；DB columns 与 payload 必须一致
- version chain：1..N contiguous，缺号/重复 → HISTORY_VERSION_GAP
- origin integrity：graph_change 必须有匹配 GraphChange（identity / version /
  change_type 兼容）；缺失/损坏 → HISTORY_ORIGIN_INTEGRITY_CONFLICT
- as_of 必须显式提供，禁止默认 now()
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from research_os.models import GraphChange, GraphEdge, GraphNode
from research_os.validators.schema_validator import validate_instance
from research_os.utils.time import parse_iso


class HistoryError(Exception):
    """history 失败（error_code 精确机械 code）。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass
class VersionEntry:
    """单个版本的历史条目（deterministic）。"""

    version: int
    payload: Dict[str, Any]
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    superseded_by_version: Optional[int] = None
    is_tombstone: bool = False
    derived_status: Optional[str] = None  # 仅 as_of 提供时计算


@dataclass
class HistoryResult:
    """identity-scoped history 输出（deterministic JSON 友好）。"""

    kind: str  # "node" | "edge"
    identity: str
    as_of: Optional[str]
    versions: List[VersionEntry] = field(default_factory=list)
    resolved: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "identity": self.identity,
            "as_of": self.as_of,
            "versions": [
                {
                    "version": e.version,
                    "payload": e.payload,
                    "effective_from": e.effective_from,
                    "effective_to": e.effective_to,
                    "superseded_by_version": e.superseded_by_version,
                    "is_tombstone": e.is_tombstone,
                    "derived_status": e.derived_status,
                }
                for e in self.versions
            ],
            "resolved": self.resolved,
        }


# DB columns 与 payload 字段的对应核对表
_NODE_COLUMNS = (
    ("node_id", "node_id"),
    ("version", "version"),
    ("node_type", "node_type"),
    ("name", "name"),
    ("status", "status"),
    ("review_status", "review_status"),
    ("origin_kind", "origin_kind"),
    ("created_at", "created_at"),
    ("valid_from", "valid_from"),
    ("valid_to", "valid_to"),
    ("last_reviewed_at", "last_reviewed_at"),
    ("originating_graph_change_id", "originating_graph_change_id"),
)
_EDGE_COLUMNS = (
    ("edge_id", "edge_id"),
    ("version", "version"),
    ("source_node_id", "source_node_id"),
    ("relation", "relation"),
    ("target_node_id", "target_node_id"),
    ("assertion_type", "assertion_type"),
    ("review_status", "review_status"),
    ("created_at", "created_at"),
    ("valid_from", "valid_from"),
    ("valid_to", "valid_to"),
    ("confidence", "confidence"),
    ("last_reviewed_at", "last_reviewed_at"),
    ("originating_graph_change_id", "originating_graph_change_id"),
)

_NODE_COMPATIBLE_CHANGE_TYPES = ("add_node", "modify_attribute", "retire_node")
_EDGE_COMPATIBLE_CHANGE_TYPES = ("add_edge", "modify_attribute", "retire_edge")


class HistoryService:
    """M7 确定性历史服务（零 LLM / 零 Provider / 零 network）。"""

    def __init__(self, db, graph_repo):
        self._db = db
        self._graph_repo = graph_repo

    # ── public API ──────────────────────────────────────────

    def get_node_history(self, node_id: str,
                         as_of: Optional[str] = None) -> HistoryResult:
        """完整 node history（version 1..N 全量）。as_of 提供时附带 resolve。"""
        as_of = self._validate_as_of(as_of)
        payloads = self._load_version_payloads("node", node_id, None)
        entries = self._derive_intervals(payloads)
        if as_of is not None:
            self._attach_derived_status(entries, as_of)
        resolved = self._resolve(entries, as_of) if as_of is not None else None
        return HistoryResult(kind="node", identity=node_id, as_of=as_of,
                             versions=entries, resolved=resolved)

    def get_edge_history(self, edge_id: str,
                         as_of: Optional[str] = None) -> HistoryResult:
        """完整 edge history（version 1..N 全量）。as_of 提供时附带 resolve。"""
        as_of = self._validate_as_of(as_of)
        payloads = self._load_version_payloads("edge", edge_id, None)
        entries = self._derive_intervals(payloads)
        if as_of is not None:
            self._attach_derived_status(entries, as_of)
        resolved = self._resolve(entries, as_of) if as_of is not None else None
        return HistoryResult(kind="edge", identity=edge_id, as_of=as_of,
                             versions=entries, resolved=resolved)

    def resolve_node_as_of(self, node_id: str, as_of: str) -> Dict[str, Any]:
        """as_of 时点 node 状态（deterministic，禁止默认 now()）。"""
        as_of = self._validate_as_of(as_of, required=True)
        payloads = self._load_version_payloads("node", node_id, None)
        entries = self._derive_intervals(payloads)
        return self._resolve(entries, as_of)

    def resolve_edge_as_of(self, edge_id: str, as_of: str,
                           conn=None) -> Dict[str, Any]:
        """as_of 时点 edge 状态（deterministic，禁止默认 now()）。

        conn: 可选外部连接（apply 事务内 incident-edge guard 复用）。
        """
        as_of = self._validate_as_of(as_of, required=True)
        payloads = self._load_version_payloads("edge", edge_id, conn)
        entries = self._derive_intervals(payloads)
        return self._resolve(entries, as_of)

    # ── as_of ───────────────────────────────────────────────

    @staticmethod
    def _validate_as_of(as_of: Optional[str], *,
                        required: bool = False) -> Optional[str]:
        if as_of is None:
            if required:
                raise HistoryError(
                    "HISTORY_AS_OF_REQUIRED",
                    "as_of 必须显式提供（禁止默认 now()）",
                )
            return None
        try:
            parse_iso(as_of)
        except ValueError as e:
            raise HistoryError(
                "HISTORY_AS_OF_INVALID", f"as_of 非法 ISO: {e}"
            ) from e
        return as_of

    # ── strict load ─────────────────────────────────────────

    def _load_version_payloads(self, kind: str, identity: str,
                               conn) -> List[Dict[str, Any]]:
        """strict read：全部版本行 → 每行 full strict parse + column 核对。

        版本按 version ASC 排序；version chain 必须 1..N contiguous。
        """
        dbc = conn or self._db._conn
        if kind == "node":
            table, id_col, schema_name, model = (
                "graph_nodes", "node_id", "graph_node", GraphNode)
            columns = _NODE_COLUMNS
        else:
            table, id_col, schema_name, model = (
                "graph_edges", "edge_id", "graph_edge", GraphEdge)
            columns = _EDGE_COLUMNS
        try:
            rows = dbc.execute(
                f"SELECT * FROM {table} WHERE {id_col} = ? ORDER BY version ASC",
                (identity,),
            ).fetchall()
        except Exception as e:
            raise HistoryError(
                "HISTORY_READ_FAILED",
                f"history read failed for {kind} {identity}: {e}",
            ) from e

        payloads: List[Dict[str, Any]] = []
        for row in rows:
            identity_val = row[id_col]
            version_val = int(row["version"])
            payload = self._strict_parse_row(
                kind, identity_val, version_val, row, dbc,
                schema_name, model, columns)
            payloads.append(payload)

        # version chain：1..N contiguous
        versions = [p["version"] for p in payloads]
        if versions != list(range(1, len(versions) + 1)):
            raise HistoryError(
                "HISTORY_VERSION_GAP",
                f"{kind} {identity} version chain 断裂：{versions}（要求 1..{len(versions)} contiguous）",
            )
        return payloads

    def _strict_parse_row(self, kind, identity_val, version_val, row, dbc,
                          schema_name, model, columns) -> Dict[str, Any]:
        """单行 strict parse：JSON → dict → schema → Pydantic → dump → schema，
        并核对 DB columns 与 payload。"""
        try:
            payload = json.loads(row["payload"])
        except Exception as e:
            raise HistoryError(
                "HISTORY_PAYLOAD_INVALID",
                f"{kind} {identity_val} v{version_val} payload invalid JSON: {e}",
            ) from e
        if not isinstance(payload, dict):
            raise HistoryError(
                "HISTORY_PAYLOAD_INVALID",
                f"{kind} {identity_val} v{version_val} payload 顶层必须是 object，"
                f"got {type(payload).__name__}",
            )
        schema_errors = validate_instance(payload, schema_name)
        if schema_errors:
            raise HistoryError(
                "HISTORY_SCHEMA_INVALID",
                f"{kind} {identity_val} v{version_val} schema invalid: "
                f"{'; '.join(schema_errors)}",
            )
        try:
            obj = model(**payload)
        except Exception as e:
            raise HistoryError(
                "HISTORY_SCHEMA_INVALID",
                f"{kind} {identity_val} v{version_val} Pydantic parse failed: {e}",
            ) from e
        try:
            dumped = obj.model_dump()
        except Exception as e:
            raise HistoryError(
                "HISTORY_SCHEMA_INVALID",
                f"{kind} {identity_val} v{version_val} model_dump failed: {e}",
            ) from e
        schema_errors2 = validate_instance(dumped, schema_name)
        if schema_errors2:
            raise HistoryError(
                "HISTORY_SCHEMA_INVALID",
                f"{kind} {identity_val} v{version_val} dump schema re-validation failed: "
                f"{'; '.join(schema_errors2)}",
            )

        # DB columns 与 payload 核对（不得只信一边）
        for col, payload_key in columns:
            db_value = row[col]
            pv = dumped.get(payload_key)
            if db_value != pv:
                raise HistoryError(
                    "HISTORY_INTEGRITY_CONFLICT",
                    f"{kind} {identity_val} v{version_val} DB column {col}={db_value!r} "
                    f"与 payload {payload_key}={pv!r} 不一致",
                )

        # origin integrity（graph_change origin 必须有匹配 GraphChange）
        self._check_origin(kind, dumped, dbc)
        return dumped

    def _check_origin(self, kind: str, payload: Dict[str, Any], dbc) -> None:
        """origin integrity：graph_change 必须有匹配 GraphChange。

        Governance seed（node origin_kind=governance_seed / GOVERNANCE edge）
        允许 originating_graph_change_id=null，不查 GraphChange。
        """
        gc_id = payload.get("originating_graph_change_id")
        if gc_id is None:
            return  # governance seed
        try:
            row = dbc.execute(
                "SELECT payload FROM graph_changes WHERE graph_change_id = ?",
                (gc_id,),
            ).fetchone()
        except Exception as e:
            raise HistoryError(
                "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                f"{kind} {payload.get('node_id') or payload.get('edge_id')} "
                f"origin GraphChange {gc_id} 读取失败: {e}",
            ) from e
        if row is None:
            raise HistoryError(
                "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                f"{kind} origin GraphChange 缺失: {gc_id}",
            )
        try:
            gc_dict = json.loads(row["payload"])
        except Exception as e:
            raise HistoryError(
                "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                f"origin GraphChange {gc_id} payload invalid JSON: {e}",
            ) from e
        if not isinstance(gc_dict, dict):
            raise HistoryError(
                "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                f"origin GraphChange {gc_id} payload 顶层非 object",
            )
        schema_errors = validate_instance(gc_dict, "graph_change")
        if schema_errors:
            raise HistoryError(
                "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                f"origin GraphChange {gc_id} schema invalid: "
                f"{'; '.join(schema_errors)}",
            )
        try:
            gc = GraphChange(**gc_dict)
        except Exception as e:
            raise HistoryError(
                "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                f"origin GraphChange {gc_id} Pydantic parse failed: {e}",
            ) from e

        if kind == "node":
            if gc.node is None or gc.node.node_id != payload["node_id"]:
                raise HistoryError(
                    "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                    f"origin GraphChange {gc_id} node identity 不匹配",
                )
            if gc.node.version != payload["version"]:
                raise HistoryError(
                    "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                    f"origin GraphChange {gc_id} node version 不匹配",
                )
            if gc.change_type not in _NODE_COMPATIBLE_CHANGE_TYPES:
                raise HistoryError(
                    "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                    f"origin GraphChange {gc_id} change_type={gc.change_type} "
                    f"与 node 不兼容",
                )
        else:
            if gc.edge is None or gc.edge.edge_id != payload["edge_id"]:
                raise HistoryError(
                    "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                    f"origin GraphChange {gc_id} edge identity 不匹配",
                )
            if gc.edge.version != payload["version"]:
                raise HistoryError(
                    "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                    f"origin GraphChange {gc_id} edge version 不匹配",
                )
            if gc.change_type not in _EDGE_COMPATIBLE_CHANGE_TYPES:
                raise HistoryError(
                    "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                    f"origin GraphChange {gc_id} change_type={gc.change_type} "
                    f"与 edge 不兼容",
                )

    # ── interval derivation ─────────────────────────────────

    def _derive_intervals(self, payloads: List[Dict[str, Any]]) -> List[VersionEntry]:
        """半开区间 [effective_from, effective_to) 派生。

        effective_to = min(intrinsic_end, successor_end) 等规则；
        effective_from > effective_to（均非 null）→ HISTORY_INTERVAL_INVALID。
        """
        entries: List[VersionEntry] = []
        for i, p in enumerate(payloads):
            successor = payloads[i + 1] if i + 1 < len(payloads) else None
            intrinsic_end = p.get("valid_to")
            successor_end = successor["valid_from"] if successor else None
            eff_from = p.get("valid_from")
            eff_to = self._min_time(intrinsic_end, successor_end)

            if (eff_from is not None and eff_to is not None
                    and parse_iso(eff_from) > parse_iso(eff_to)):
                raise HistoryError(
                    "HISTORY_INTERVAL_INVALID",
                    f"version {p['version']} effective_from={eff_from} "
                    f"> effective_to={eff_to}（半开区间非法）",
                )

            superseded_by = successor["version"] if successor is not None else None
            is_tombstone = self._is_tombstone(p, successor)
            entries.append(VersionEntry(
                version=p["version"],
                payload=p,
                effective_from=eff_from,
                effective_to=eff_to,
                superseded_by_version=superseded_by,
                is_tombstone=is_tombstone,
            ))
        return entries

    @staticmethod
    def _min_time(a: Optional[str], b: Optional[str]) -> Optional[str]:
        if a is None:
            return b
        if b is None:
            return a
        return a if parse_iso(a) <= parse_iso(b) else b

    def _is_tombstone(self, p: Dict[str, Any], successor) -> bool:
        """retire tombstone：node status=retired / edge origin change_type==retire_edge。

        edge origin 读取失败 → fail-closed（raise HistoryError，
        HISTORY_ORIGIN_INTEGRITY_CONFLICT），绝不把已 retired 判定为非 tombstone。
        """
        if "status" in p:
            return p.get("status") == "retired"
        gc_id = p.get("originating_graph_change_id")
        if gc_id is None:
            return False
        try:
            ct = self._graph_repo.get_graph_change_type(gc_id)
        except Exception as e:
            raise HistoryError(
                "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                f"edge origin GraphChange {gc_id} 读取失败（retire 判定 fail-closed）: {e}",
            ) from e
        if ct is None:
            raise HistoryError(
                "HISTORY_ORIGIN_INTEGRITY_CONFLICT",
                f"edge origin GraphChange {gc_id} 缺失（retire 判定 fail-closed）",
            )
        return ct == "retire_edge"

    # ── derived status / resolve ────────────────────────────

    def _attach_derived_status(self, entries: List[VersionEntry],
                               as_of: str) -> None:
        as_of_dt = parse_iso(as_of)
        for i, e in enumerate(entries):
            nxt = entries[i + 1] if i + 1 < len(entries) else None
            e.derived_status = self._status_of(e, nxt, as_of_dt)

    def _status_of(self, e: VersionEntry, nxt: Optional[VersionEntry],
                   as_of_dt) -> str:
        # retired：tombstone 且 as_of >= retire_at（valid_from == valid_to）
        if e.is_tombstone:
            retire_at = e.effective_from
            if retire_at is not None and as_of_dt >= parse_iso(retire_at):
                return "retired"
        # superseded：已生效 successor
        if nxt is not None and nxt.effective_from is not None \
                and as_of_dt >= parse_iso(nxt.effective_from):
            return "superseded"
        # expired：无已生效 successor 且 valid_to 已到
        if e.payload.get("valid_to") is not None \
                and as_of_dt >= parse_iso(e.payload["valid_to"]):
            return "expired"
        # not_yet_valid
        if e.effective_from is not None and as_of_dt < parse_iso(e.effective_from):
            return "not_yet_valid"
        return "active"

    def _resolve(self, entries: List[VersionEntry],
                 as_of: Optional[str]) -> Optional[Dict[str, Any]]:
        """as_of 时点解析（deterministic）。

        选择最后一个 effective_from <= as_of 的版本；无则第一个版本
        not_yet_valid；resolved 的 derived_status 用 _status_of 计算。
        """
        if not entries:
            return None
        as_of_dt = parse_iso(as_of)
        selected = None
        for e in entries:
            if e.effective_from is not None \
                    and parse_iso(e.effective_from) > as_of_dt:
                break  # 后续版本均未生效
            selected = e
        if selected is None:
            first = entries[0]
            return {
                "version": first.version,
                "derived_status": "not_yet_valid",
                "is_active": False,
                "payload": first.payload,
            }
        idx = entries.index(selected)
        nxt = entries[idx + 1] if idx + 1 < len(entries) else None
        status = self._status_of(selected, nxt, as_of_dt)
        return {
            "version": selected.version,
            "derived_status": status,
            "is_active": status == "active",
            "payload": selected.payload,
        }
