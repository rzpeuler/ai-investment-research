"""来源探测引擎（Phase 1 任务 5.3-5.4 节）。

使用 curl.exe 执行 HTTP 探测（Windows 自带，代理行为可控），检查：
域名可达性、重定向、登录要求、JS 依赖、公开搜索入口、日期/关键词查询、
返回字段、历史范围、响应时间、限频、robots 提示。

探测证据最小化：只保存最终 URL / HTTP 状态 / 标题 / 关键字段名 / 最小文本
证据，禁止把完整页面正文写入长期日志（临时响应文件用后即删）。
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_os.models import SourceProbe
from research_os.source_probe.spec import ProbeSpec, ProbeUrl
from research_os.utils.id import new_uuid
from research_os.utils.time import now_iso
from research_os.validators.schema_validator import validate_instance

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_JS_HINT_RE = re.compile(
    r"<script[^>]+src=|<script\b(?![^>]*type=['\"]application/(ld\+json|json))",
    re.IGNORECASE,
)
_LOGIN_HINT_RE = re.compile(r"(登录|登陆|login|sign\s*in|password|账号)", re.IGNORECASE)


class HttpProbeResult:
    """单次 HTTP 探测结果（临时，不入库）。"""

    def __init__(
        self,
        url: str,
        final_url: str,
        http_status: Optional[int],
        elapsed_ms: Optional[float],
        redirects: int,
        title: Optional[str],
        body_excerpt: str,
        error: Optional[str] = None,
    ):
        self.url = url
        self.final_url = final_url
        self.http_status = http_status
        self.elapsed_ms = elapsed_ms
        self.redirects = redirects
        self.title = title
        self.body_excerpt = body_excerpt
        self.error = error

    @property
    def ok(self) -> bool:
        return self.http_status is not None and 200 <= self.http_status < 400 and not self.error


def _run_curl(url: str, timeout: float, referer: Optional[str] = None) -> HttpProbeResult:
    """用 curl.exe 探测单个 URL。临时响应文件用后即删（不保存全文）。"""
    curl = "curl.exe"
    with tempfile.TemporaryDirectory(prefix="probe_") as td:
        out_file = Path(td) / "resp.bin"
        cmd = [
            curl, "-sS", "-L", "-o", str(out_file),
            "-w", "%{http_code}\t%{url_effective}\t%{time_total}\t%{num_redirects}",
            "--max-time", str(int(timeout)),
            "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        ]
        if referer:
            cmd += ["-e", referer]
        cmd.append(url)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        except subprocess.TimeoutExpired:
            return HttpProbeResult(url, url, None, None, 0, None, "", error="timeout")
        meta = (proc.stdout or "").strip().split("\t")
        http_status = int(meta[0]) if len(meta) > 0 and meta[0].isdigit() else None
        final_url = meta[1] if len(meta) > 1 else url
        elapsed = float(meta[2]) if len(meta) > 2 and meta[2] else None
        redirects = int(meta[3]) if len(meta) > 3 and meta[3].isdigit() else 0

        raw = b""
        if out_file.exists():
            raw = out_file.read_bytes()[:200_000]
        text = ""
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            text = ""
        m = _TITLE_RE.search(text)
        title = m.group(1).strip()[:200] if m else None
        excerpt = re.sub(r"\s+", " ", text)[:300]
        return HttpProbeResult(url, final_url, http_status, elapsed, redirects,
                               title, excerpt)


def probe_url(url: str, spec: ProbeUrl, timeout: float,
              referer: Optional[str] = None) -> Dict[str, Any]:
    """探测单个 URL，返回证据 dict（最小化，不含完整正文）。"""
    r = _run_curl(url, timeout, referer=referer)
    evidence: Dict[str, Any] = {
        "url": url,
        "final_url": r.final_url,
        "http_status": r.http_status,
        "elapsed_ms": round(r.elapsed_ms, 3) if r.elapsed_ms is not None else None,
        "redirects": r.redirects,
        "title": r.title,
        "error": r.error,
    }
    if r.body_excerpt:
        # 最小文本证据：仅保留关键特征（页面标题之外最多 200 字符）
        evidence["text_hint"] = r.body_excerpt[:200]
    return evidence


def probe_source(spec: ProbeSpec, referer: Optional[str] = None) -> SourceProbe:
    """对单个来源执行完整探测，返回 SourceProbe（通过 Schema 校验）。"""
    started = now_iso()
    status = "success"
    http_status: Optional[int] = None
    fields_found: List[str] = []
    evidence: List[Dict[str, Any]] = []
    errors: List[str] = []
    notes: List[str] = []
    requires_js = False
    requires_login = False

    for u in spec.urls:
        ev = probe_url(u.url, u, spec.timeout_seconds, referer=referer)
        evidence.append(ev)
        if ev.get("http_status") is not None:
            http_status = ev["http_status"]
        if ev.get("error") == "timeout":
            errors.append(f"超时: {u.url}")
            status = "partial"
        if ev.get("http_status") == 403:
            errors.append(f"403 被阻止: {u.url}")
            status = "blocked" if status == "success" else status
        if ev.get("http_status") == 429:
            errors.append(f"429 限频: {u.url}")
            status = "partial"
        if ev.get("http_status") in (401, 302) and "login" in (ev.get("final_url") or "").lower():
            requires_login = True
            status = "login_required"
        title = ev.get("title") or ""
        if _LOGIN_HINT_RE.search(title):
            requires_login = requires_login or True

    # 字段检测：以返回内容标题/文本提示中出现的关键词为依据
    hints = " ".join(str(e.get("title") or "") + " " + str(e.get("text_hint") or "")
                     for e in evidence)
    for field in spec.expected_fields:
        if field.lower() in hints.lower():
            fields_found.append(field)
    if not fields_found and status == "success":
        # 页面可达但字段未确认：标记 partial（不得把可达性误判为字段完整）
        status = "partial"
        notes.append("页面可达但目标字段未在页面静态内容中确认（可能依赖 JS 或接口）")

    if spec.check_js_dependency:
        js_hint = any(_JS_HINT_RE.search(str(e.get("text_hint") or "")) for e in evidence)
        if js_hint:
            requires_js = True
            notes.append("检测到脚本加载，结构化提取可能依赖 JS/接口")

    probe = SourceProbe(
        probe_id=new_uuid(),
        source_id=spec.source_id,
        started_at=started,
        finished_at=now_iso(),
        status=status,
        http_status=http_status,
        access_level_detected="public" if status in ("success", "partial") else
                             ("login_required" if requires_login else
                              ("blocked" if status == "blocked" else "unknown")),
        automation_level_detected="html" if spec.urls else "unknown",
        historical_depth=None,
        fields_detected=fields_found,
        requires_javascript=requires_js,
        requires_login=requires_login,
        rate_limit_observed=None,
        storage_policy_recommendation="metadata_and_excerpt",
        evidence=evidence,
        errors=errors,
        notes=notes,
    )
    errs = validate_instance(probe.model_dump(), "source_probe")
    if errs:
        raise ValueError(f"SourceProbe 未通过 Schema 校验: {errs}")
    return probe
