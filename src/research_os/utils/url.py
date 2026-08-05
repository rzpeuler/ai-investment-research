"""URL 标准化（确定性逻辑，指南 29.1 精确去重使用）。

只做无损规范化：去 fragment、默认端口、尾斜杠、域名小写；
不做参数排序（参数顺序可能携带语义），不做跳转跟随。
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def normalize_url(url: str) -> str:
    """标准化 URL 用于去重哈希。非法输入原样返回（由调用方处理）。"""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    scheme = (parts.scheme or "").lower()
    netloc = parts.netloc.lower()
    # 去默认端口
    if ":" in netloc:
        host, _, port = netloc.rpartition(":")
        if port == _DEFAULT_PORTS.get(scheme):
            netloc = host
    # 去 fragment（fragment 不参与资源标识）
    path = parts.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def normalized_url_hash(url: str) -> str:
    """标准化 URL 的 sha256（去重键之一）。"""
    from research_os.utils.id import content_sha256

    return content_sha256(normalize_url(url))
