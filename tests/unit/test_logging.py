"""结构化错误记录测试（Phase 0.1 / 2.4）。

验证 errors.log JSONL 记录：exception_type / 时间 / 组件 / retryable /
attempt / stacktrace，以及敏感字段过滤（API Key、Cookie、Authorization 等）。
"""
from __future__ import annotations

import pytest

from research_os.utils.logging import ErrorLog, redact_text, redact_value


@pytest.fixture()
def log(tmp_path):
    return ErrorLog(tmp_path / "errors.log", task_id="task-1")


def test_record_basic_fields(log):
    log.error("orchestrator", "任务失败")
    entries = log.read()
    assert len(entries) == 1
    e = entries[0]
    assert e["timestamp"]
    assert e["task_id"] == "task-1"
    assert e["component"] == "orchestrator"
    assert e["level"] == "ERROR"
    assert e["message"] == "任务失败"


def test_record_exception_type_and_stacktrace(log):
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        log.record_exception("collector", "采集失败", exc, module="cninfo",
                             retryable=True, attempt=2)
    entries = log.read()
    e = entries[0]
    assert e["exception_type"] == "RuntimeError"
    assert e["module"] == "cninfo"
    assert e["retryable"] is True
    assert e["attempt"] == 2
    assert e["stacktrace"] is not None
    assert "RuntimeError" in e["stacktrace"]


def test_sensitive_context_fields_redacted(log):
    log.error("collector", "请求失败", {
        "api_key": "sk-123456",
        "Authorization": "Bearer abc.def.ghi",
        "cookie": "session=SECRET_VALUE",
        "password": "p@ssw0rd",
        "token": "tok123",
        "url": "https://example.com/data",
    })
    e = log.read()[0]
    ctx = e["context"]
    assert ctx["api_key"] == "[REDACTED]"
    assert ctx["Authorization"] == "[REDACTED]"
    assert ctx["cookie"] == "[REDACTED]"
    assert ctx["password"] == "[REDACTED]"
    assert ctx["token"] == "[REDACTED]"
    # 非敏感字段保留
    assert ctx["url"] == "https://example.com/data"


def test_sensitive_value_in_message_redacted(log):
    log.error("collector", "failed with api_key=sk-live-999 and token=tok123 ok")
    e = log.read()[0]
    assert "sk-live-999" not in e["message"]
    assert "[REDACTED]" in e["message"]
    assert "tok123" not in e["message"]


def test_nested_sensitive_fields_redacted(log):
    log.error("collector", "错误", {"headers": {"Authorization": "Bearer x.y.z",
                                                "Accept": "application/json"}})
    ctx = log.read()[0]["context"]
    assert ctx["headers"]["Authorization"] == "[REDACTED]"
    assert ctx["headers"]["Accept"] == "application/json"


def test_backward_compatible_record(log):
    """旧调用形式 error(component, message, details) 仍工作，且结构化。"""
    log.error("orchestrator", "旧格式调用", {"detail": 1})
    e = log.read()[0]
    assert e["component"] == "orchestrator"
    assert e["context"] == {"detail": 1}
    assert e["exception_type"] is None


def test_redact_text_unit():
    assert "api_key" in redact_text("api_key=abc123")
    assert "abc123" not in redact_text("api_key=abc123")
    assert "password: secret" not in redact_text("password: secret")
    assert "[REDACTED]" in redact_text("password: secret")


def test_redact_value_recursive():
    assert redact_value({"a": {"cookie": "x"}}) == {"a": {"cookie": "[REDACTED]"}}
    assert redact_value(["a", {"token": "t"}]) == ["a", {"token": "[REDACTED]"}]
    assert redact_value("plain text") == "plain text"
