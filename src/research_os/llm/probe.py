"""显式 LLM Provider 在线探测。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict

from research_os.llm.client import LlmClient
from research_os.llm.provider_factory import create_provider, get_provider_config
from research_os.llm.redaction import redact_text


@dataclass(frozen=True)
class ProviderProbeResult:
    provider_id: str
    configured: bool
    reachable: bool
    authentication_status: str
    flash_model_resolved: str
    pro_model_resolved: str
    json_mode: str
    latency_seconds: float
    sanitized_error: str
    checked_at: str

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)


def probe_provider(
    project_root: Path,
    *,
    provider_id: str = "deepseek",
    model_class: str = "flash",
    live: bool = False,
    urlopen=None,
) -> ProviderProbeResult:
    config = get_provider_config(project_root, provider_id)
    checked_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    common = {
        "provider_id": config.provider_id,
        "configured": config.configured,
        "flash_model_resolved": config.flash_model,
        "pro_model_resolved": config.pro_model,
        "json_mode": "json_object" if config.supports_json_object else "none",
        "checked_at": checked_at,
    }
    if not live:
        return ProviderProbeResult(
            **common, reachable=False, authentication_status="not_checked",
            latency_seconds=0.0, sanitized_error="live_required",
        )
    if not config.configured:
        return ProviderProbeResult(
            **common, reachable=False, authentication_status="not_configured",
            latency_seconds=0.0, sanitized_error="provider_not_configured",
        )
    provider = create_provider(
        project_root, provider_id=provider_id, live=True, urlopen=urlopen)
    request = LlmClient.make_request(
        task_id="provider-probe", module="llm.probe",
        prompt='返回 JSON 对象：{"status":"ok"}',
        output_schema_name="provider_probe_inline",
        requested_model_class=model_class,
    )
    started = perf_counter()
    result = provider.complete_json(
        request,
        {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"const": "ok"}},
            "additionalProperties": False,
        },
    )
    latency = round(perf_counter() - started, 6)
    ok = bool(result.get("ok")) and result.get("output", {}).get("status") == "ok"
    error_type = str(result.get("error_type") or "")
    auth = "ok" if ok else (
        "failed" if error_type in {"authentication_error", "authorization_error"} else "unknown"
    )
    return ProviderProbeResult(
        **common, reachable=ok, authentication_status=auth,
        latency_seconds=latency,
        sanitized_error="" if ok else redact_text(result.get("error") or error_type),
    )
