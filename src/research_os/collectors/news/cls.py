"""财联社电报元数据适配器（Phase 1 任务 6.4 节新闻候选）。

基于真实探测：https://www.cls.cn/telegraph 静态内容含 title/content 文本。
本适配器只做元数据级提取（B 级来源，补充背景，不作核心事实唯一来源）。

页面结构高度动态：提取失败时返回 schema_changed，禁止伪造条目。
"""
from __future__ import annotations

import re
import subprocess
from typing import Any, Dict, List, Optional

from research_os.collectors.base import (
    CollectorAdapter,
    HealthStatus,
    ItemRef,
    RateLimitPolicy,
    RawPayload,
)
from research_os.models import RawItem
from research_os.utils.id import content_sha256, new_uuid
from research_os.utils.time import now_iso
from research_os.validators.schema_validator import validate_instance

TELEGRAPH_URL = "https://www.cls.cn/telegraph"
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class ClsMetadataCollector(CollectorAdapter):
    """财联社电报元数据适配器（source_id: cls，B 级，实验性）。"""

    source_id = "cls"
    version = "0.1.0"

    def _get_page(self, url: str, timeout: float = 20.0) -> Optional[str]:
        cmd = ["curl.exe", "-sS", "-L", "--max-time", str(int(timeout)),
               "-A", "Mozilla/5.0", url]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        except subprocess.TimeoutExpired:
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout

    def healthcheck(self) -> HealthStatus:
        page = self._get_page(TELEGRAPH_URL)
        ok = page is not None and len(page) > 1000
        return HealthStatus(
            source_id=self.source_id,
            ok=ok,
            access="public_but_unstable" if ok else "unavailable",
            message="财联社电报页可访问" if ok else "财联社电报页不可访问",
            checked_at=now_iso(),
        )

    def discover(self, query: Dict[str, Any],
                 time_window: Dict[str, Optional[str]]) -> List[ItemRef]:
        page = self._get_page(TELEGRAPH_URL)
        if page is None:
            raise RuntimeError("cls 电报页获取失败")
        # 本阶段仅记录页面级元数据（标题），不解析电报条目（JS 渲染，结构不稳定）
        m = _TITLE_RE.search(page)
        title = m.group(1).strip()[:120] if m else "财联社电报"
        if not m:
            raise RuntimeError("cls 页面结构未匹配（schema_changed）")
        return [ItemRef(
            source_id=self.source_id,
            external_id=content_sha256(title)[:32],
            url=TELEGRAPH_URL,
            title=title,
            published_at=now_iso(),
            extra={"note": "B级来源；电报条目需 JS 渲染，本阶段仅元数据"},
        )]

    def fetch(self, item_ref: ItemRef) -> RawPayload:
        page = self._get_page(item_ref.url)
        ok = page is not None and len(page) > 1000
        return RawPayload(
            source_id=self.source_id,
            external_id=item_ref.external_id,
            url=item_ref.url,
            title=item_ref.title,
            publisher="财联社",
            author=None,
            published_at=item_ref.published_at,
            content="",  # 不保存电报正文
            retrieved_at=now_iso(),
            fetch_status="ok" if ok else "failed",
            error_message="" if ok else "电报页不可达",
        )

    def normalize(self, raw_payload: RawPayload) -> List[RawItem]:
        item = RawItem(
            raw_item_id=new_uuid(),
            source_id=self.source_id,
            external_id=raw_payload.external_id,
            url=raw_payload.url,
            title=raw_payload.title,
            publisher=raw_payload.publisher,
            author=raw_payload.author,
            published_at=raw_payload.published_at or now_iso(),
            retrieved_at=raw_payload.retrieved_at or now_iso(),
            content_hash=content_sha256(f"{raw_payload.url}|{raw_payload.title}"),
            content_excerpt=raw_payload.title[:200],
            content_storage="metadata_and_excerpt",
            language="zh-CN",
            access_status="ok" if raw_payload.fetch_status == "ok" else "failed",
            entities=[],
            raw_category="news_flash_metadata",
        )
        errors = validate_instance(item.model_dump(), "raw_item")
        if errors:
            raise ValueError(f"RawItem 未通过 Schema 校验: {errors}")
        return [item]

    def rate_limit_policy(self) -> RateLimitPolicy:
        return RateLimitPolicy(requests_per_minute=3, backoff_seconds=10.0,
                               max_retries=1, timeout_seconds=20.0)
