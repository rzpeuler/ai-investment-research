"""来源探测结果存储：JSON 证据文件（data/source_probes/）+ SQLite。"""
from __future__ import annotations

import json
from pathlib import Path

from research_os.models import Source, SourceProbe
from research_os.storage import Database
from research_os.utils.time import now_iso


def save_probe(project_root: str | Path, probe: SourceProbe,
               db: Database | None = None) -> Path:
    """保存探测结果：写 JSON 证据文件并持久化到 SQLite。返回证据文件路径。"""
    root = Path(project_root)
    out_dir = root / "data" / "source_probes"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{probe.source_id}.json"
    path.write_text(json.dumps(probe.model_dump(), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    if db is not None:
        db.upsert(probe)
    return path


def update_source_status(project_root: str | Path, source: Source,
                         db: Database | None = None) -> Path:
    """将探测结论回写来源注册表（registry/sources.yaml 由 CLI 汇总时刷新）。"""
    root = Path(project_root)
    path = root / "registry" / "sources.yaml"
    if db is not None:
        db.upsert(source)
    return path


def load_probe_file(path: str | Path) -> dict:
    """读取探测证据文件。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def list_probe_files(project_root: str | Path) -> list[Path]:
    root = Path(project_root)
    d = root / "data" / "source_probes"
    if not d.exists():
        return []
    return sorted(d.glob("*.json"))
