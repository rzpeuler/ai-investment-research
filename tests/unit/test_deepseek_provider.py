"""DeepSeek Provider 配置、HTTP 契约、错误分类、脱敏和 probe（全部离线）。"""
from __future__ import annotations

import io
import json
import socket
import urllib.error
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli
from research_os.llm.client import LlmClient, is_provider_configured
from research_os.llm.provider import FakeLlmProvider
from research_os.llm.provider_config import load_provider_config
from research_os.llm.provider_factory import create_provider
from research_os.llm.probe import probe_provider
from research_os.llm.redaction import REDACTED, contains_sensitive_label, redact_text, redact_value


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _request(prompt="返回 JSON"):
    return LlmClient.make_request(
        "task-1", "test.deepseek", prompt, "data_route", requested_model_class="flash")


def _success_payload(output=None, model="deepseek-v4-flash"):
    return {
        "model": model,
        "choices": [{"message": {"content": json.dumps(output or {"status": "ok"})}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }


def test_config_loads_without_secret(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = load_provider_config(_root() / "config" / "llm_providers.yaml", "deepseek")
    assert config.provider_id == "deepseek"
    assert config.flash_model == "deepseek-v4-flash"
    assert config.pro_model == "deepseek-v4-pro"
    assert config.configured is False
    text = (_root() / "config" / "llm_providers.yaml").read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY" in text
    assert "sk-test" not in text


def test_factory_requires_explicit_live(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")
    assert create_provider(_root(), live=False) is None
    assert create_provider(_root(), live=True) is not None


def test_deepseek_success_contract_and_model_mapping(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")
    captured = {}

    def urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeHttpResponse(_success_payload())

    provider = create_provider(_root(), live=True, urlopen=urlopen)
    result = provider.complete_json(
        _request(), {"type": "object", "properties": {"status": {"type": "string"}}})
    assert result["ok"] is True
    assert result["provider"] == "deepseek"
    assert result["model_id"] == "deepseek-v4-flash"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["body"]["model"] == "deepseek-v4-flash"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in captured["body"]["messages"][0]["content"]
    assert captured["headers"]["Authorization"] == "Bearer sk-test-secret"


@pytest.mark.parametrize(
    ("status", "error_type", "retryable"),
    [(401, "authentication_error", False), (403, "authorization_error", False),
     (429, "rate_limited", True), (500, "provider_5xx", True),
     (400, "invalid_response", False)],
)
def test_http_error_classification(monkeypatch, status, error_type, retryable):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")

    def urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, status, "failure", {}, io.BytesIO())

    result = create_provider(_root(), live=True, urlopen=urlopen).complete_json(_request(), {})
    assert result["ok"] is False
    assert result["error_type"] == error_type
    assert result["retryable"] is retryable
    assert "sk-test-secret" not in result["error"]


def test_timeout_and_invalid_json(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")

    def timeout_open(request, timeout):
        raise socket.timeout("sk-test-secret")

    timeout_result = create_provider(
        _root(), live=True, urlopen=timeout_open).complete_json(_request(), {})
    assert timeout_result["error_type"] == "timeout"
    assert timeout_result["retryable"] is True

    class BadResponse(FakeHttpResponse):
        def read(self):
            return b"not-json"

    invalid = create_provider(
        _root(), live=True, urlopen=lambda request, timeout: BadResponse({})
    ).complete_json(_request(), {})
    assert invalid["error_type"] == "invalid_response"


def test_sensitive_prompt_rejected_before_http(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")
    called = False

    def urlopen(request, timeout):
        nonlocal called
        called = True
        return FakeHttpResponse(_success_payload())

    result = create_provider(_root(), live=True, urlopen=urlopen).complete_json(
        _request("Authorization: Bearer sk-test-secret"), {})
    assert result["error_type"] == "invalid_response"
    assert called is False
    assert "sk-test-secret" not in json.dumps(result, ensure_ascii=False)


def test_redaction_filters_nested_and_inline_secrets():
    fake = "sk-live-super-secret"
    value = {
        "authorization": f"Bearer {fake}",
        "nested": [f"api_key={fake}", {"password": "p@ss"}],
    }
    redacted = redact_value(value, secrets=[fake])
    blob = json.dumps(redacted)
    assert fake not in blob and "p@ss" not in blob
    assert REDACTED in blob
    assert fake not in redact_text(f"network error token={fake}", secrets=[fake])
    assert contains_sensitive_label("cookie: abc")


def test_configured_state_recognizes_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")
    assert is_provider_configured() is True


def test_client_redacts_secret_from_provider_exception(monkeypatch):
    secret = "sk-test-secret-in-exception"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    provider = FakeLlmProvider(
        behavior=lambda request, schema: (_ for _ in ()).throw(RuntimeError(secret)))
    response = LlmClient(provider=provider, configured=True).generate_json(_request(), {})
    blob = json.dumps(response.model_dump(), ensure_ascii=False)
    assert secret not in blob
    assert REDACTED in blob


def test_probe_without_live_never_calls_network(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")
    result = probe_provider(
        _root(), live=False,
        urlopen=lambda *args, **kwargs: pytest.fail("offline probe must not call network"),
    )
    assert result.configured is True
    assert result.reachable is False
    assert result.authentication_status == "not_checked"
    assert result.sanitized_error == "live_required"


def test_live_probe_success_is_minimal_and_sanitized(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")
    result = probe_provider(
        _root(), live=True,
        urlopen=lambda request, timeout: FakeHttpResponse(_success_payload()),
    )
    assert result.reachable is True
    assert result.authentication_status == "ok"
    assert result.sanitized_error == ""
    assert "sk-test-secret" not in json.dumps(result.model_dump())


def test_cli_probe_without_live(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret")
    monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(_root()))
    result = CliRunner().invoke(cli, ["llm", "probe"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["configured"] is True
    assert payload["reachable"] is False
    assert "sk-test-secret" not in result.output
