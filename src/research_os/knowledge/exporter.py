"""Phase 5 M10-A Deterministic JSON Mirror Exporter。

SQLite → JSON 只读确定性导出（零 LLM / 零 Provider / 零 network / 零 DB 写入）。
SQLite 是唯一权威源；JSON 是只读确定性导出；禁止 JSON → SQLite import。
"""
from __future__ import annotations

import hashlib
import json
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
    """

    # pylint: disable=too-many-instance-attributes

    def __init__(
        self,
        db: Database,
        graph_repo: GraphRepository,
        history_service: HistoryService,
        knowledge_root: Path,
    ):
        self._db = db
        self._graph_repo = graph_repo
        self._history = history_service
        raw_root = str(knowledge_root)
        if ".." in raw_root:
            raise ExportError(
                "EXPORT_PATH_INVALID",
                "knowledge_root 不得包含 ../ 逃逸",
            )
        self._knowledge_root = Path(knowledge_root).resolve()

    # ── public entry ────────────────────────────────────────

    def export(self, *, dry_run: bool = False) -> ExportResult:
        """执行完整导出流程。"""
        # 打开共享 read snapshot
        conn = self._db._conn
        conn.execute("BEGIN")

        try:
            # 2. list identities
            node_ids = self._list_node_ids(conn)
            edge_ids = self._list_edge_ids(conn)

            # 3. build all mirror in memory
            result, file_map = self._build_mirror(
                conn, node_ids, edge_ids, dry_run
            )
            if result.status == "error":
                return result

            # 4. compute tree hash
            result.tree_sha256 = self._compute_tree_sha256(file_map)

        finally:
            conn.execute("ROLLBACK")

        # 5. filesystem write phase (dry_run skip)
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

    # ── validation ─────────────────────────────────────────


    # ── identity discovery ──────────────────────────────────

    @staticmethod
    def _list_node_ids(conn) -> List[str]:
        """列出全部唯一 node identity（按 node_id 排序）。"""
        rows = conn.execute(
            "SELECT DISTINCT node_id FROM graph_nodes ORDER BY node_id"
        ).fetchall()
        return [row["node_id"] for row in rows]

    @staticmethod
    def _list_edge_ids(conn) -> List[str]:
        """列出全部唯一 edge identity（按 edge_id 排序）。"""
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
        """构造所有 JSON bytes，在内存中完成全部 preflight。"""
        result = ExportResult(status="ok")
        file_map: Dict[str, bytes] = {}
        planned = 0

        # Node graph mirror (latest version)
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

            # history mirror
            hist_path = f"{_EXPORT_HISTORY_NODE_DIR}/{self._encode_filename(nid)}.json"
            hist_payload = {
                "object_id": nid,
                "object_type": "node",
                "versions": [v.payload for v in history.versions
                             if v.payload is not None],
            }
            file_map[hist_path] = self._json_bytes(hist_payload)
            planned += 1

        # Edge graph mirror (latest version)
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

            # history mirror
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
        """确定性 JSON 字节序列化。"""
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
        """百分比编码文件名（Windows colon 安全）。"""
        return urllib.parse.quote(object_id, safe="-._~")

    @staticmethod
    def _latest_version(history) -> Optional[Dict[str, Any]]:
        """返回最大 version 的 payload，若无版本返回 None。"""
        if not history.versions:
            return None
        latest_entry = history.versions[-1]  # version ASC 已排序
        return latest_entry.payload

    # ── filesystem ──────────────────────────────────────────

    def _write_mirror(self, file_map: Dict[str, bytes]) -> int:
        """全量替换 managed 目录。staging → replace 模式。"""
        # 写入 staging dir
        staging = Path(tempfile.mkdtemp(dir=self._knowledge_root.parent))

        try:
            for rel_path, content in file_map.items():
                target = staging / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)

            # 替换 managed directories
            for managed_dir in _MANAGED_DIRS:
                staging_dir = staging / managed_dir
                target_dir = self._knowledge_root / managed_dir

                # Remove old target directory
                if target_dir.exists():
                    shutil.rmtree(target_dir)

                if staging_dir.exists():
                    # move staging → target
                    shutil.move(str(staging_dir), str(target_dir))

            return len(file_map)

        finally:
            # Cleanup staging
            if staging.exists():
                shutil.rmtree(staging)

    # ── tree hash ───────────────────────────────────────────

    @staticmethod
    def _compute_tree_sha256(file_map: Dict[str, bytes]) -> str:
        """计算导出树的确定性 SHA256。

        按 relative path lexical sort：
        relative_path UTF-8 + NUL + file bytes + NUL 串联。
        """
        hasher = hashlib.sha256()
        for path in sorted(file_map.keys()):
            hasher.update(path.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(file_map[path])
            hasher.update(b"\x00")
        return hasher.hexdigest()
