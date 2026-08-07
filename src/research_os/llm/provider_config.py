"""真实 LLM Provider 的配置加载和校验。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


@dataclass(frozen=True)
class RetryPolicy:
    max_transient_retries: int
    retryable_errors: tuple[str, ...]


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    display_name: str
    enabled: bool
    adapter: str
    api_key_env: str
    base_url_env: str
    default_base_url: str
    timeout_seconds: int
    flash_model: str
    pro_model: str
    supports_json_schema: bool
    supports_json_object: bool
    max_input_chars: int
    max_output_tokens: int
    retry_policy: RetryPolicy

    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")

    def base_url(self) -> str:
        return (os.environ.get(self.base_url_env) or self.default_base_url).rstrip("/")

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.api_key())

    def model_for(self, model_class: str) -> str:
        if model_class == "flash":
            return self.flash_model
        if model_class == "pro":
            return self.pro_model
        raise ValueError(f"未知模型等级: {model_class}")


def _require_text(data: Dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Provider 配置字段 {field} 必须为非空字符串")
    return value.strip()


def _parse_provider(data: Dict[str, Any]) -> ProviderConfig:
    retry = data.get("retry_policy")
    if not isinstance(retry, dict):
        raise ValueError("Provider 配置缺少 retry_policy")
    max_retries = retry.get("max_transient_retries")
    if not isinstance(max_retries, int) or not 0 <= max_retries <= 3:
        raise ValueError("max_transient_retries 必须为 0-3 的整数")
    retryable = retry.get("retryable_errors")
    if not isinstance(retryable, list) or not all(isinstance(x, str) for x in retryable):
        raise ValueError("retryable_errors 必须为字符串列表")
    timeout = data.get("timeout_seconds")
    max_input = data.get("max_input_chars")
    max_output = data.get("max_output_tokens")
    if not isinstance(timeout, int) or not 1 <= timeout <= 600:
        raise ValueError("timeout_seconds 必须为 1-600 的整数")
    if not isinstance(max_input, int) or max_input <= 0:
        raise ValueError("max_input_chars 必须为正整数")
    if not isinstance(max_output, int) or max_output <= 0:
        raise ValueError("max_output_tokens 必须为正整数")
    return ProviderConfig(
        provider_id=_require_text(data, "provider_id"),
        display_name=_require_text(data, "display_name"),
        enabled=bool(data.get("enabled")),
        adapter=_require_text(data, "adapter"),
        api_key_env=_require_text(data, "api_key_env"),
        base_url_env=_require_text(data, "base_url_env"),
        default_base_url=_require_text(data, "default_base_url"),
        timeout_seconds=timeout,
        flash_model=_require_text(data, "flash_model"),
        pro_model=_require_text(data, "pro_model"),
        supports_json_schema=bool(data.get("supports_json_schema")),
        supports_json_object=bool(data.get("supports_json_object")),
        max_input_chars=max_input,
        max_output_tokens=max_output,
        retry_policy=RetryPolicy(max_retries, tuple(retryable)),
    )


def load_provider_configs(path: Path) -> Dict[str, ProviderConfig]:
    """加载全部 Provider；映射键必须与 provider_id 一致。"""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    providers = payload.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ValueError("llm_providers.yaml 缺少 providers")
    result: Dict[str, ProviderConfig] = {}
    for key, value in providers.items():
        if not isinstance(value, dict):
            raise ValueError(f"Provider {key} 配置必须为对象")
        config = _parse_provider(value)
        if config.provider_id != key:
            raise ValueError(f"Provider 键 {key} 与 provider_id {config.provider_id} 不一致")
        result[key] = config
    return result


def load_provider_config(path: Path, provider_id: str) -> ProviderConfig:
    configs = load_provider_configs(path)
    if provider_id not in configs:
        raise KeyError(f"未登记 LLM Provider: {provider_id}")
    return configs[provider_id]
