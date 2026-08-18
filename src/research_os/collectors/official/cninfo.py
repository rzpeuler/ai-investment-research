"""巨潮资讯正式披露适配器（Phase 1 任务 7.2 节）。

基于真实探测验证的公开查询接口：
POST http://www.cninfo.com.cn/new/hisAnnouncement/query
返回 JSON：announcements[] {secCode, secName, orgId, announcementId,
announcementTitle, announcementTime(ms), adjunctUrl, adjunctType, ...}

约束：
- 只采集元数据 + 最小摘录（metadata_and_excerpt），不下载/不保存 PDF 全文
- 禁止猜测字段；字段来自实测响应
- 失败必须显式返回状态
"""
from __future__ import annotations

import subprocess
import shutil
from datetime import timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from research_os.collectors.base import (
    CollectorAdapter,
    HealthStatus,
    ItemRef,
    RateLimitPolicy,
    RawPayload,
)
from research_os.models import RawItem
from research_os.utils.id import content_sha256, new_uuid
from research_os.utils.time import now_iso, shanghai_now
from research_os.utils.url import normalize_url
from research_os.validators.schema_validator import validate_instance

QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
TOPSEARCH_URL = "http://www.cninfo.com.cn/new/information/topSearch/query"
BASE_URL = "http://static.cninfo.com.cn/"


def _curl_executable() -> Optional[str]:
    """返回当前平台可用的 curl；缺失时由调用方显式降级。"""
    return shutil.which("curl.exe") or shutil.which("curl")


def _recent_se_date() -> str:
    """返回包含上海当天在内的最近 5 个自然日查询窗口。"""
    end_date = shanghai_now().date()
    start_date = end_date - timedelta(days=4)
    return f"{start_date.isoformat()}~{end_date.isoformat()}"


class CninfoCollector(CollectorAdapter):
    """巨潮资讯公告元数据适配器（source_id: cninfo）。"""

    source_id = "cninfo"
    version = "1.0.0"

    def _post_query(self, params: Dict[str, Any], timeout: float = 25.0) -> Optional[dict]:
        """调用公告查询接口。失败返回 None（调用方显式处理）。"""
        curl = _curl_executable()
        if curl is None:
            return None
        data = urlencode(params)
        cmd = [
            curl, "-sS", "--max-time", str(int(timeout)),
            "-X", "POST", QUERY_URL,
            "-H", "Content-Type: application/x-www-form-urlencoded",
            "--data", data,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        try:
            import json

            return json.loads(proc.stdout.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def _resolve_secid(self, stock: str, timeout: float = 20.0) -> Optional[str]:
        """CNINFO 官方 topSearch 接口：股票代码 → orgId（确定性、官方映射，非猜测）。

        公告查询接口的 secid 必须为 orgId（如 600519→gssh0600519、300750→GD165627）；
        stock 参数本身不生效（真实接口行为，跨市场实测）。失败返回 None（调用方 fail closed）。
        """
        curl = _curl_executable()
        if curl is None or not stock:
            return None
        data = urlencode({"keyWord": stock, "maxNum": 5})
        cmd = [
            curl, "-sS", "--max-time", str(int(timeout)),
            "-X", "POST", TOPSEARCH_URL,
            "-H", "Content-Type: application/x-www-form-urlencoded",
            "--data", data,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        try:
            import json

            items = json.loads(proc.stdout.decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(items, list):
            return None
        for it in items:
            if str(it.get("code")) == stock:
                org_id = it.get("orgId")
                if isinstance(org_id, str) and org_id:
                    return org_id
        return None

    # ---------- 接口 ----------

    def healthcheck(self) -> HealthStatus:
        result = self._post_query({"pageNum": 1, "pageSize": 1, "column": "szse",
                                   "tabName": "fulltext", "seDate": _recent_se_date()})
        ok = result is not None and "announcements" in result
        return HealthStatus(
            source_id=self.source_id,
            ok=ok,
            access="public" if ok else "public_but_unstable",
            message="巨潮公告查询接口可用" if ok else "巨潮公告查询接口不可用/返回异常",
            checked_at=now_iso(),
        )

    def discover(self, query: Dict[str, Any],
                 time_window: Dict[str, Optional[str]]) -> List[ItemRef]:
        """按时间窗口发现公告。

        query: {"stock": "600519", "searchkey": "..."}（可选）
        time_window: {"start": ISO, "end": ISO}（可选，默认近 5 日）
        """
        start = (time_window or {}).get("start")
        end = (time_window or {}).get("end")
        se_date = _recent_se_date()
        if start and end:
            se_date = f"{start[:10]}~{end[:10]}"
        # 真实接口行为（跨市场实测）：secid=orgId 是主过滤；column 固定 szse
        # 才能命中（column=shmb 时 secid 过滤恒空）。stock 参数不生效。
        stock = str(query.get("stock") or "")
        secid = query.get("secid") or (self._resolve_secid(stock) if stock else "")
        if stock and not secid:
            raise RuntimeError(
                f"cninfo 无法解析 orgId（{stock}）→ fail closed，禁止猜测"
            )
        params: Dict[str, Any] = {
            "pageNum": 1, "pageSize": 50,
            "column": "szse", "tabName": "fulltext",
            "plate": "", "stock": "",
            "searchkey": query.get("searchkey", ""),
            "secid": secid,
            "category": "", "trade": "",
            "seDate": se_date,
            "sortName": "", "sortType": "",
            "isHLtitle": "false",
        }
        result = self._post_query(params)
        if result is None:
            raise RuntimeError(f"cninfo 查询失败（{QUERY_URL} 无有效响应）")
        if not isinstance(result, dict) or "announcements" not in result:
            # 结构变化：显式失败，禁止把空响应解释为"没有公告"
            raise RuntimeError("cninfo 响应结构变化（缺少 announcements 字段）")
        refs: List[ItemRef] = []
        for ann in result.get("announcements") or []:
            title = ann.get("announcementTitle") or ""
            if not title:
                continue
            ts_ms = ann.get("announcementTime")
            published = None
            if isinstance(ts_ms, (int, float)) and ts_ms > 0:
                from datetime import datetime as _dt

                from research_os.utils.time import to_iso

                published = to_iso(_dt.fromtimestamp(ts_ms / 1000))
            url = BASE_URL + (ann.get("adjunctUrl") or "")
            refs.append(ItemRef(
                source_id=self.source_id,
                external_id=str(ann.get("announcementId") or ""),
                url=normalize_url(url),
                title=title,
                published_at=published,
                extra={
                    "secCode": ann.get("secCode"),
                    "secName": ann.get("secName"),
                    "adjunctType": ann.get("adjunctType"),
                    "announcementType": ann.get("announcementType"),
                },
            ))
        return refs

    def fetch(self, item_ref: ItemRef) -> RawPayload:
        """验证公告附件 URL 可达性（仅 HEAD 少量字节，不下载全文）。"""
        reachable = False
        curl = _curl_executable()
        if curl is not None:
            cmd = [curl, "-sS", "-I", "--max-time", "15",
                   "-A", "Mozilla/5.0", item_ref.url]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
                reachable = proc.returncode == 0 and any(
                    line.startswith("HTTP/") and "200" in line
                    for line in proc.stdout.splitlines()
                )
            except (OSError, subprocess.TimeoutExpired):
                reachable = False
        return RawPayload(
            source_id=self.source_id,
            external_id=item_ref.external_id,
            url=item_ref.url,
            title=item_ref.title,
            publisher=item_ref.extra.get("secName") or "巨潮资讯",
            author=None,
            published_at=item_ref.published_at,
            content="",  # 不下载全文
            retrieved_at=now_iso(),
            fetch_status="ok" if reachable else "failed",
            error_message="" if reachable else "附件 URL 不可达",
        )

    def normalize(self, raw_payload: RawPayload) -> List[RawItem]:
        """构建 RawItem：仅元数据 + 最小摘录（公告标题），不保存全文。"""
        excerpt = raw_payload.title[:200]
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
            content_excerpt=excerpt,
            content_storage="metadata_and_excerpt",
            language="zh-CN",
            access_status="ok" if raw_payload.fetch_status == "ok" else "failed",
            entities=[],
            raw_category="announcement",
        )
        errors = validate_instance(item.model_dump(), "raw_item")
        if errors:
            raise ValueError(f"RawItem 未通过 Schema 校验: {errors}")
        return [item]

    def rate_limit_policy(self) -> RateLimitPolicy:
        return RateLimitPolicy(requests_per_minute=10, backoff_seconds=3.0,
                               max_retries=2, timeout_seconds=25.0)
