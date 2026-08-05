"""新浪行情适配器（Phase 1 任务 6.3 节行情候选）。

基于真实探测验证：https://hq.sinajs.cn/list=sh600519 （需 Referer:
https://finance.sina.com.cn）返回 GBK 编码：
var hq_str_sh600519="贵州茅台,1328.360,1328.360,1306.450,1333.800,...";

字段序（实测）：0=名称 1=今开 2=昨收 3=当前价 4=最高 5=最低
6=买一价 7=卖一价 8=成交量(股) 9=成交额(元) ... 30=日期 31=时间

约束：本适配器仅验证实时报价元数据；日级 OHLCV 需历史接口（Phase 1 结论：
可得性已验证，接口实现留待行情模块）。禁止承诺分钟级实时。
"""
from __future__ import annotations

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

QUOTE_URL = "https://hq.sinajs.cn/list={symbol}"
REFERER = "https://finance.sina.com.cn"
# 字段名映射（实测顺序）
_FIELDS = ["name", "open", "prev_close", "price", "high", "low", "bid1", "ask1",
           "volume", "amount", "date", "time"]


class SinaQuoteCollector(CollectorAdapter):
    """新浪行情适配器（source_id: sina_quote，行情候选）。"""

    source_id = "sina_quote"
    version = "1.0.0"

    def _fetch_quote(self, symbol: str, timeout: float = 15.0) -> Optional[str]:
        cmd = ["curl.exe", "-sS", "--max-time", str(int(timeout)),
               "-e", REFERER, "-A", "Mozilla/5.0",
               QUOTE_URL.format(symbol=symbol)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10,
                                  encoding="gbk", errors="replace")
        except subprocess.TimeoutExpired:
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout

    def healthcheck(self) -> HealthStatus:
        raw = self._fetch_quote("sh000001")
        ok = raw is not None and "hq_str" in raw and '"' in raw
        return HealthStatus(
            source_id=self.source_id,
            ok=ok,
            access="public" if ok else "public_but_unstable",
            message="新浪行情接口可用" if ok else "新浪行情接口不可用/结构异常",
            checked_at=now_iso(),
        )

    def discover(self, query: Dict[str, Any],
                 time_window: Dict[str, Optional[str]]) -> List[ItemRef]:
        symbols = query.get("symbols") or [query.get("symbol")]
        symbols = [s for s in symbols if s]
        if not symbols:
            raise ValueError("sina_quote 需要 symbols 或 symbol 查询参数")
        return [ItemRef(
            source_id=self.source_id,
            external_id=s,
            url=QUOTE_URL.format(symbol=s),
            title=f"实时报价 {s}",
        ) for s in symbols]

    def fetch(self, item_ref: ItemRef) -> RawPayload:
        raw = self._fetch_quote(item_ref.external_id)
        ok = raw is not None and "=" in raw
        return RawPayload(
            source_id=self.source_id,
            external_id=item_ref.external_id,
            url=item_ref.url,
            title=item_ref.title,
            publisher="新浪财经",
            author=None,
            published_at=now_iso(),
            content=raw or "",  # 临时；normalize 后仅保留最小摘录
            retrieved_at=now_iso(),
            fetch_status="ok" if ok else "failed",
            error_message="" if ok else "行情接口无响应",
        )

    def normalize(self, raw_payload: RawPayload) -> List[RawItem]:
        """解析报价文本 -> RawItem（仅最小摘录：名称+价格+日期）。"""
        excerpt = ""
        if "=" in raw_payload.content:
            fields = raw_payload.content.split('"', 2)[1].split(",")
            if len(fields) >= 6:
                excerpt = (f"{fields[0]} 现价{fields[3]} 开{fields[1]} 高{fields[4]} "
                           f"低{fields[5]} 日期{fields[30] if len(fields) > 30 else '?'}")
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
            content_hash=content_sha256(raw_payload.content or ""),
            content_excerpt=excerpt[:300],
            content_storage="metadata_and_excerpt",
            language="zh-CN",
            access_status="ok" if raw_payload.fetch_status == "ok" and excerpt else "failed",
            entities=[],
            raw_category="quote",
        )
        errors = validate_instance(item.model_dump(), "raw_item")
        if errors:
            raise ValueError(f"RawItem 未通过 Schema 校验: {errors}")
        return [item]

    def rate_limit_policy(self) -> RateLimitPolicy:
        return RateLimitPolicy(requests_per_minute=10, backoff_seconds=2.0,
                               max_retries=2, timeout_seconds=15.0)
