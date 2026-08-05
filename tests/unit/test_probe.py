"""来源探测引擎测试（Phase 1 任务 11.3 节）。

覆盖：探测成功 / 登录要求 / JS 依赖 / 被阻止 / 超时 / 未知状态 /
探测证据不保存完整正文。全部离线（mock curl 层）。
"""
from __future__ import annotations

import pytest

from research_os.source_probe import engine
from research_os.source_probe.engine import HttpProbeResult, probe_source
from research_os.source_probe.spec import ProbeSpec, ProbeUrl


def _make_spec(urls=None, **kw):
    if urls is None:
        urls = [ProbeUrl(url="https://example.com/", purpose="主页")]
    return ProbeSpec(source_id="test", name="测试源", group="official",
                     urls=urls, **kw)


def _result(url="https://example.com/", http_status=200, title="测试页",
            excerpt="<html><script src='/app.js'></script>正文</html>",
            error=None):
    return HttpProbeResult(url, url, http_status, 120.5, 0, title, excerpt, error)


def test_probe_success(monkeypatch):
    monkeypatch.setattr(engine, "_run_curl", lambda *a, **k: _result())
    probe = probe_source(_make_spec(expected_fields=["测试页"]))
    assert probe.status == "success"
    assert probe.http_status == 200
    assert probe.access_level_detected == "public"
    assert probe.evidence and probe.evidence[0]["title"] == "测试页"


def test_probe_blocked_403(monkeypatch):
    monkeypatch.setattr(engine, "_run_curl",
                        lambda *a, **k: _result(http_status=403, title="403"))
    probe = probe_source(_make_spec())
    assert probe.status == "blocked"
    assert probe.access_level_detected == "unavailable"
    assert any("403" in e for e in probe.errors)


def test_probe_timeout(monkeypatch):
    monkeypatch.setattr(engine, "_run_curl",
                        lambda *a, **k: _result(http_status=None, error="timeout"))
    probe = probe_source(_make_spec())
    assert probe.status == "partial"
    assert any("超时" in e for e in probe.errors)


def test_probe_login_required(monkeypatch):
    monkeypatch.setattr(engine, "_run_curl",
                        lambda *a, **k: _result(title="请登录后查看"))
    probe = probe_source(_make_spec())
    assert probe.requires_login is True
    assert probe.status in ("login_required", "partial")


def test_probe_js_dependency(monkeypatch):
    monkeypatch.setattr(engine, "_run_curl", lambda *a, **k: _result())
    probe = probe_source(_make_spec(check_js_dependency=True))
    assert probe.requires_javascript is True
    assert any("脚本" in n for n in probe.notes)


def test_probe_fields_not_confirmed_partial(monkeypatch):
    """字段未在静态内容确认 -> partial，不得冒充 success。"""
    monkeypatch.setattr(engine, "_run_curl",
                        lambda *a, **k: _result(title="页面", excerpt="无目标字段"))
    probe = probe_source(_make_spec(expected_fields=["announcementTitle"]))
    assert probe.status == "partial"
    assert probe.fields_detected == []


def test_probe_evidence_no_full_body(monkeypatch):
    """探测证据不保存完整正文：text_hint 截断为 200 字符。"""
    big = "x" * 5000
    monkeypatch.setattr(engine, "_run_curl",
                        lambda *a, **k: _result(excerpt=f"<html>{big}</html>"))
    probe = probe_source(_make_spec())
    text_hint = probe.evidence[0].get("text_hint", "")
    assert len(text_hint) <= 200
    assert probe.storage_policy_recommendation == "metadata_and_excerpt"


def test_probe_unknown_source_state():
    """无 URL 规格：自动化等级 unknown，状态不冒充 success 的完整确认。"""
    probe = probe_source(_make_spec(urls=[]))
    assert probe.automation_level_detected == "unknown"
    assert probe.status == "partial"  # 无可确认字段
