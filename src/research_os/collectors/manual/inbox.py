"""人工 Inbox 服务（Phase 1 任务 9 节）。

用户放入 URL/标题/摘要/手动摘录/来源说明。规则：
- 用户提供的摘录不自动视为事实
- 保留用户提供与系统提取的区别（content_excerpt 为用户提供，raw 标记见 notes）
- 链接无法访问时标记 url_accessible=false
- 不自动进入知识图谱（状态机: submitted -> parsed/accepted/rejected/needs_review）
- 不长期保存用户未要求保存的全文
"""
from __future__ import annotations

from typing import List, Optional

from research_os.models import ManualInbox
from research_os.storage import Database
from research_os.utils.id import new_uuid
from research_os.utils.time import now_iso
from research_os.validators.schema_validator import validate_instance


class ManualInboxService:
    """人工 Inbox：校验（ManualInbox Schema）-> 原子写入 DB。"""

    def __init__(self, db: Database):
        self.db = db

    def add(
        self,
        source_name: str,
        source_url: str,
        title: str,
        content_excerpt: str = "",
        notes: str = "",
        intended_entities: Optional[List[str]] = None,
        published_at: Optional[str] = None,
        submitted_by: str = "user",
        url_accessible: Optional[bool] = None,
    ) -> ManualInbox:
        """新增 inbox 条目（默认 submitted 状态，不进入图谱）。"""
        entry = ManualInbox(
            inbox_id=new_uuid(),
            source_name=source_name,
            source_url=source_url,
            title=title,
            content_excerpt=content_excerpt,
            notes=notes,
            intended_entities=intended_entities or [],
            published_at=published_at,
            submitted_at=now_iso(),
            submitted_by=submitted_by,
            status="submitted",
            url_accessible=True if url_accessible is None else url_accessible,
        )
        errors = validate_instance(entry.model_dump(), "manual_inbox")
        if errors:
            raise ValueError(f"ManualInbox 未通过 Schema 校验: {errors}")
        self.db.upsert(entry)
        return entry

    def list(self, status: Optional[str] = None) -> List[dict]:
        import json

        if status:
            rows = self.db.query(
                "SELECT payload FROM manual_inbox WHERE status = ? ORDER BY submitted_at DESC",
                (status,),
            )
        else:
            rows = self.db.query(
                "SELECT payload FROM manual_inbox ORDER BY submitted_at DESC"
            )
        return [json.loads(r["payload"]) for r in rows]

    def update_status(self, inbox_id: str, status: str) -> ManualInbox:
        """状态流转：submitted/parsed/accepted/rejected/needs_review。"""
        stored = self.db.get("manual_inbox", inbox_id)
        if stored is None:
            raise KeyError(f"inbox 条目不存在: {inbox_id}")
        entry = ManualInbox(**stored)
        entry.status = status  # type: ignore[assignment]
        errors = validate_instance(entry.model_dump(), "manual_inbox")
        if errors:
            raise ValueError(f"ManualInbox 状态更新未通过 Schema 校验: {errors}")
        self.db.upsert(entry)
        return entry
