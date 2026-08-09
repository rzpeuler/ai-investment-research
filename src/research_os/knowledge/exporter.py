"""Phase 5 M10 Deterministic JSON Mirror Exporter。

SQLite → JSON 只读确定性导出（零 LLM / 零 Provider / 零 network / 零 DB 写入）。
SQLite 是唯一权威源；JSON 是只读确定性导出；禁止 JSON → SQLite import。

R1: 强只读 DB authority + 项目根 containment + managed path preflight + symlink fail-closed。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from research_os.knowledge.history import HistoryService, HistoryError
from research_os.knowledge.repository import GraphRepository
from research_os.storage.db import Database

_EXPORT_NODE_DIR = "graph/nodes"
_EXPORT_EDGE_DIR = "graph/edges"
_EXPORT_HISTORY_NODE_DIR = "history/nodes"
_EXPORT_HISTORY_EDGE_DIR = "history/edges"

_MANAGED_DIRS = [
    _EXPORT_NODE_DIR,
    _EXPORT_EDGE_DIR,
    _EXPORT_HISTORY_NODE_DIR,
    _EXPORT_HISTORY_EDGE_DIR,
]

# managed parents that must exist as directories (not symlinks)
_MANAGED_PARENTS = [
    "graph",
    "history",
]


@dataclass
class ExportResult:
    """确定性导出的结果对象。"""

    status: str  # "ok" | "error"
    node_identity_count: int = 0
    edge_identity_count: int = 0
    node_version_count: int = 0
    edge_version_count: int = 0
    files_planned: int = 0
    files_written: int = 0
    tree_sha256: str = ""
    errors: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "node_identity_count": self.node_identity_count,
            "edge_identity_count": self.edge_identity_count,
            "node_version_count": self.node_version_count,
            "edge_version_count": self.edge_version_count,
            "files_planned": self.files_planned,
            "files_written": self.files_written,
            "tree_sha256": self.tree_sha256,
            "errors": self.errors,
        }


class ExportError(Exception):
    """Mirror 导出错误（公开错误契约，不泄漏 raw traceback）。"""

    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(f"[{error_code}] {message}")


class KnowledgeMirrorExporter:
    """确定性 JSON Mirror 导出器。

    每身份最新 version graph mirror + 全量 version history mirror。
    单 SQLite read snapshot；preflight fail-closed；删除残留旧 JSON。

    R1: 内部自开 read-only Database；接受 project_root + knowledge_root
    进行 containment + symlink 预检；任意路径逃逸则 EXPORT_PATH_INVALID。
    """

    def __init__(
        self,
        *,
        project_root: Path,
        knowledge_root: Path,
        db_path: Path,
    ):
        """构造导出器。

        Args:
            project_root: 项目根目录（必须为绝对路径，且 knowledge_root 在其内）。
            knowledge_root: knowledge/ 目录（必须为 project_root 的子目录或自身）。
            db_path: SQLite 数据库路径（内部以 mode=ro 打开）。
        """
        # ── resolve & validate project/knowledge containment ──
        self._project_root = project_root.resolve()
        self._knowledge_root_resolved = knowledge_root.resolve(strict=False)

        # canonical knowledge: <project_root>/knowledge
        canonical_knowledge = self._project_root / "knowledge"

        # containment check: knowledge root must be inside project root
        try:
            self._knowledge_root_resolved.relative_to(self._project_root)
        except ValueError:
            raise ExportError(
                "EXPORT_PATH_INVALID",
                f"knowledge_root ({self._knowledge_root_resolved}) "
                f"不在 project_root ({self._project_root}) 内",
            )

        # symlink check: knowledge root itself must not be a symlink
        # 指向外部 (resolve vs raw 比较)
        if os.path.islink(str(knowledge_root)):
            raise ExportError(
                "EXPORT_PATH_INVALID",
                "knowledge_root 不得为 symlink",
            )

        # open read-only DB
        self._db = Database.open_read_only(db_path)
        self._graph_repo = GraphRepository(self._db)
        self._history = HistoryService(self._db, self._graph_repo)
        self._db_path = db_path

    # ── public entry ────────────────────────────────────────

    def export(self, *, dry_run: bool = False) -> ExportResult:
        """执行完整导出流程。

        先做 managed path preflight（检查 symlink/escape），
        然后单 read snapshot → 内存构建 → tree hash → 文件写入。
        """
        # Preflight: check all managed paths BEFORE any filesystem mutation
        if not dry_run:
            self._preflight_managed_paths()

        # 打开共享 read snapshot
        conn = self._db._conn
        conn.execute("BEGIN")

        try:
            node_ids = self._list_node_ids(conn)
            edge_ids = self._list_edge_ids(conn)

            result, file_map = self._build_mirror(
                conn, node_ids, edge_ids, dry_run
            )
            if result.status == "error":
                return result

            result.tree_sha256 = self._compute_tree_sha256(file_map)

        finally:
            conn.execute("ROLLBACK")

        if not dry_run:
            try:
                result.files_written = self._write_mirror(file_map)
            except Exception as exc:
                result.status = "error"
                result.errors.append({
                    "error_code": "EXPORT_WRITE_FAILED",
                    "message": str(exc),
                })
                return result

        return result

    # ── path preflight ──────────────────────────────────────

    def _preflight_managed_paths(self) -> None:
        """在所有文件系统写入前统一检查 managed 路径。

        拒绝：symlink、非目录冲突、resolved 路径在 project_root 外。
        任何失败 → EXPORT_PATH_INVALID，0 文件变更。
        """
        kroot = self._knowledge_root_resolved

        # check parent dirs first
        for parent in _MANAGED_PARENTS:
            pdir = kroot / parent
            if pdir.exists():
                if pdir.is_symlink():
                    raise ExportError(
                        "EXPORT_PATH_INVALID",
                        f"managed parent 为 symlink: {pdir}",
                    )
                if not pdir.is_dir():
                    raise ExportError(
                        "EXPORT_PATH_INVALID",
                        f"managed parent 非目录: {pdir}",
                    )
                # resolve and check containment
                resolved = pdir.resolve()
                try:
                    resolved.relative_to(self._project_root)
                except ValueError:
                    raise ExportError(
                        "EXPORT_PATH_INVALID",
                        f"managed parent 指向 project 外: {resolved}",
                    )

        # check each managed dir
        for managed_dir in _MANAGED_DIRS:
            mdir = kroot / managed_dir
            if mdir.exists():
                if mdir.is_symlink():
                    raise ExportError(
                        "EXPORT_PATH_INVALID",
                        f"managed dir 为 symlink: {mdir}",
                    )
                if not mdir.is_dir():
                    raise ExportError(
                        "EXPORT_PATH_INVALID",
                        f"managed dir 非目录: {mdir}",
                    )
                resolved = mdir.resolve()
                try:
                    resolved.relative_to(self._project_root)
                except ValueError:
                    raise ExportError(
                        "EXPORT_PATH_INVALID",
                        f"managed dir 指向 project 外: {resolved}",
                    )

    # ── identity discovery ──────────────────────────────────

    @staticmethod
    def _list_node_ids(conn) -> List[str]:
        rows = conn.execute(
            "SELECT DISTINCT node_id FROM graph_nodes ORDER BY node_id"
        ).fetchall()
        return [row["node_id"] for row in rows]

    @staticmethod
    def _list_edge_ids(conn) -> List[str]:
        rows = conn.execute(
            "SELECT DISTINCT edge_id FROM graph_edges ORDER BY edge_id"
        ).fetchall()
        return [row["edge_id"] for row in rows]

    # ── mirror building ─────────────────────────────────────

    def _build_mirror(
        self,
        conn,
        node_ids: List[str],
        edge_ids: List[str],
        dry_run: bool,
    ) -> Tuple[ExportResult, Dict[str, bytes]]:
        result = ExportResult(status="ok")
        file_map: Dict[str, bytes] = {}
        planned = 0

        for nid in node_ids:
            try:
                history = self._history.get_node_history(nid, conn=conn)
            except HistoryError as exc:
                result.status = "error"
                result.errors.append({
                    "error_code": "EXPORT_READ_FAILED",
                    "message": f"node {nid}: {exc}",
                })
                return result, {}

            latest = self._latest_version(history)
            if latest is None:
                result.status = "error"
                result.errors.append({
                    "error_code": "EXPORT_INTEGRITY_CONFLICT",
                    "message": f"node {nid}: 无有效版本",
                })
                return result, {}

            result.node_identity_count += 1
            result.node_version_count += len(history.versions)

            path = f"{_EXPORT_NODE_DIR}/{self._encode_filename(nid)}.json"
            file_map[path] = self._json_bytes(latest)
            planned += 1

            hist_path = f"{_EXPORT_HISTORY_NODE_DIR}/{self._encode_filename(nid)}.json"
            hist_payload = {
                "object_id": nid,
                "object_type": "node",
                "versions": [v.payload for v in history.versions
                             if v.payload is not None],
            }
            file_map[hist_path] = self._json_bytes(hist_payload)
            planned += 1

        for eid in edge_ids:
            try:
                history = self._history.get_edge_history(eid, conn=conn)
            except HistoryError as exc:
                result.status = "error"
                result.errors.append({
                    "error_code": "EXPORT_READ_FAILED",
                    "message": f"edge {eid}: {exc}",
                })
                return result, {}

            latest = self._latest_version(history)
            if latest is None:
                result.status = "error"
                result.errors.append({
                    "error_code": "EXPORT_INTEGRITY_CONFLICT",
                    "message": f"edge {eid}: 无有效版本",
                })
                return result, {}

            result.edge_identity_count += 1
            result.edge_version_count += len(history.versions)

            path = f"{_EXPORT_EDGE_DIR}/{self._encode_filename(eid)}.json"
            file_map[path] = self._json_bytes(latest)
            planned += 1

            hist_path = (
                f"{_EXPORT_HISTORY_EDGE_DIR}/{self._encode_filename(eid)}.json"
            )
            hist_payload = {
                "object_id": eid,
                "object_type": "edge",
                "versions": [v.payload for v in history.versions
                             if v.payload is not None],
            }
            file_map[hist_path] = self._json_bytes(hist_payload)
            planned += 1

        result.files_planned = planned
        return result, file_map

    # ── serialization ───────────────────────────────────────

    @staticmethod
    def _json_bytes(payload: Any) -> bytes:
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

    @staticmethod
    def _encode_filename(object_id: str) -> str:
        return urllib.parse.quote(object_id, safe="-._~")

    @staticmethod
    def _latest_version(history) -> Optional[Dict[str, Any]]:
        if not history.versions:
            return None
        return history.versions[-1].payload

    # ── filesystem ──────────────────────────────────────────

    def _write_mirror(self, file_map: Dict[str, bytes]) -> int:
        staging = Path(tempfile.mkdtemp(dir=self._project_root))

        try:
            for rel_path, content in file_map.items():
                target = staging / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)

            for managed_dir in _MANAGED_DIRS:
                staging_dir = staging / managed_dir
                target_dir = self._knowledge_root_resolved / managed_dir

                if target_dir.exists():
                    shutil.rmtree(target_dir)

                if staging_dir.exists():
                    shutil.move(str(staging_dir), str(target_dir))

            return len(file_map)

        finally:
            if staging.exists():
                shutil.rmtree(staging)

    # ── tree hash ───────────────────────────────────────────

    @staticmethod
    def _compute_tree_sha256(file_map: Dict[str, bytes]) -> str:
        hasher = hashlib.sha256()
        for path in sorted(file_map.keys()):
            hasher.update(path.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(file_map[path])
            hasher.update(b"\x00")
        return hasher.hexdigest()
