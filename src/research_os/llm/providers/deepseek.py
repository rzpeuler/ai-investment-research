"""DeepSeek OpenAI-compatible Chat Completions Provider。"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional

from research_os.llm.provider_config import ProviderConfig
from research_os.llm.redaction import contains_sensitive_label, redact_text

UrlOpen = Callable[..., Any]


class DeepSeekChatCompletionsProvider:
    """一次 `complete_json` 对应恰好一次 HTTP 尝试。"""

    provider_id = "deepseek"

    def __init__(self, config: ProviderConfig, *, urlopen: Optional[UrlOpen] = None):
        if config.adapter != "deepseek_chat_completions":
            raise ValueError(f"不支持的 DeepSeek adapter: {config.adapter}")
        self.config = config
        self._urlopen = urlopen or urllib.request.urlopen

    def complete_json(self, request, output_schema: Dict[str, Any]) -> Dict[str, Any]:
        api_key = self.config.api_key()
        if not api_key:
            return self._error("provider_not_configured", "DEEPSEEK_API_KEY 未配置", False)
        if contains_sensitive_label(request.prompt):
            return self._error("invalid_response", "Prompt 包含敏感字段名称，拒绝发送", False)
        if len(request.prompt) > self.config.max_input_chars:
            return self._error("invalid_response", "Prompt 超过 Provider 输入字符上限", False)

        try:
            model_id = self.config.model_for(request.requested_model_class)
        except ValueError as exc:
            return self._error("invalid_response", str(exc), False)
        schema_text = json.dumps(output_schema, ensure_ascii=False, separators=(",", ":"))
        body = {
            "model": model_id,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "只输出一个 JSON 对象，不要输出 Markdown。输出必须符合此 JSON Schema："
                        + schema_text
                    ),
                },
                {"role": "user", "content": request.prompt},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self.config.max_output_tokens,
            "stream": False,
        }
        raw_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.config.base_url()}/chat/completions",
            data=raw_body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "research-os/0.1",
            },
        )
        timeout = min(request.timeout_seconds, self.config.timeout_seconds)
        try:
            with self._urlopen(http_request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return self._http_error(exc.code)
        except (TimeoutError, socket.timeout):
            return self._error("timeout", "Provider 请求超时", True)
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", "network unavailable")
            if isinstance(reason, (TimeoutError, socket.timeout)):
                return self._error("timeout", "Provider 请求超时", True)
            return self._error("network_error", redact_text(reason, secrets=[api_key]), True)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._error("invalid_response", "Provider 返回非 JSON 响应", False)
        except Exception as exc:  # noqa: BLE001
            return self._error("network_error", redact_text(exc, secrets=[api_key]), True)

        try:
            choice = payload["choices"][0]
            message = choice["message"]
            content = message["content"]
            output = json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return self._error("invalid_response", "Provider 响应缺少有效 JSON content", False)
        if not isinstance(output, dict):
            return self._error("invalid_response", "Provider content 不是 JSON 对象", False)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return {
            "ok": True,
            "provider": self.provider_id,
            "model_id": payload.get("model") or model_id,
            "output": output,
            "error": None,
            "error_type": None,
            "retryable": False,
            "usage": usage,
        }

    def _http_error(self, status: int) -> Dict[str, Any]:
        if status == 401:
            return self._error("authentication_error", "Provider 认证失败 (HTTP 401)", False)
        if status == 403:
            return self._error("authorization_error", "Provider 授权失败 (HTTP 403)", False)
        if status == 429:
            return self._error("rate_limited", "Provider 限流 (HTTP 429)", True)
        if 500 <= status <= 599:
            return self._error("provider_5xx", f"Provider 服务错误 (HTTP {status})", True)
        return self._error("invalid_response", f"Provider 请求失败 (HTTP {status})", False)

    @staticmethod
    def _error(error_type: str, message: str, retryable: bool) -> Dict[str, Any]:
        return {
            "ok": False,
            "provider": "deepseek",
            "model_id": None,
            "output": None,
            "error": redact_text(message),
            "error_type": error_type,
            "retryable": retryable,
        }
