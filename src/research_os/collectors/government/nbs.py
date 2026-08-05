"""国家统计局元数据适配器（Phase 1 任务 7.2 节）。

基于真实探测验证：https://www.stats.gov.cn/sj/zxfb/ 数据发布列表页
为静态 HTML，含可提取的 标题+链接 条目（如
"2026年7月下旬流通领域重要生产资料市场价格变动情况 -> ./202608/t20260803_1964273.html"）。

约束：只采集元数据（标题/链接/发布日期），不保存全文；页面结构变更时
返回 schema_changed 状态而非伪造数据。
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
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

LIST_URL = "https://www.stats.gov.cn/sj/zxfb/"
_ARTICLE_RE = re.compile(r'<a[^>]+href="([^"]+\.html)"[^>]*>([^<]{4,120})</a>')
_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月")


class NbsCollector(CollectorAdapter):
    """国家统计局数据发布元数据适配器（source_id: nbs）。"""

    source_id = "nbs"
    version = "1.0.0"

    def _get_page(self, url: str, timeout: float = 25.0) -> Optional[str]:
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
        page = self._get_page(LIST_URL)
        ok = page is not None and "国家统计局" in page
        return HealthStatus(
            source_id=self.source_id,
            ok=ok,
            access="public" if ok else "public_but_unstable",
            message="统计局数据发布页可访问" if ok else "统计局数据发布页不可访问/结构异常",
            checked_at=now_iso(),
        )

    def discover(self, query: Dict[str, Any],
                 time_window: Dict[str, Optional[str]]) -> List[ItemRef]:
        page = self._get_page(LIST_URL)
        if page is None:
            raise RuntimeError("nbs 列表页获取失败")
        refs: List[ItemRef] = []
        seen: set[str] = set()
        for href, title in _ARTICLE_RE.findall(page):
            title = title.strip()
            if not title or not href:
                continue
            url = href if href.startswith("http") else "https://www.stats.gov.cn" + href
            if url in seen:
                continue
            seen.add(url)
            published = None
            m = _DATE_RE.search(title)
            if m:
                published = f"{m.group(1)}-{int(m.group(2)):02d}-01T00:00:00"
            refs.append(ItemRef(
                source_id=self.source_id,
                external_id=content_sha256(url)[:32],
                url=url,
                title=title,
                published_at=published,
            ))
        if not refs:
            # 页面可达但结构未匹配：显式标记 schema 变化，禁止伪造数据
            raise RuntimeError("nbs 页面结构未匹配（schema_changed），未提取到条目")
        return refs

    def fetch(self, item_ref: ItemRef) -> RawPayload:
        page = self._get_page(item_ref.url)
        ok = page is not None and len(page) > 500
        # 最小摘录：页面 <title> 或前 200 字符文本（不保存全文）
        excerpt = ""
        if page:
            m = re.search(r"<title[^>]*>(.*?)</title>", page, re.IGNORECASE | re.DOTALL)
            excerpt = (m.group(1).strip() if m else page[:200])
        return RawPayload(
            source_id=self.source_id,
            external_id=item_ref.external_id,
            url=item_ref.url,
            title=item_ref.title,
            publisher="国家统计局",
            author=None,
            published_at=item_ref.published_at,
            content="",  # 不保存全文
            retrieved_at=now_iso(),
            fetch_status="ok" if ok else "failed",
            error_message="" if ok else "页面不可达",
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
            raw_category="statistics_release",
        )
        errors = validate_instance(item.model_dump(), "raw_item")
        if errors:
            raise ValueError(f"RawItem 未通过 Schema 校验: {errors}")
        return [item]

    def rate_limit_policy(self) -> RateLimitPolicy:
        return RateLimitPolicy(requests_per_minute=5, backoff_seconds=5.0,
                               max_retries=1, timeout_seconds=25.0)
