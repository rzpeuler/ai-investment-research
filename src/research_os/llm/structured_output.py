"""Capability detection for provider-level structured output probes.

This module is probe-only. It does not change provider routing or enable a
structured mode by default; a provider must explicitly expose the adapter
method required by the capability being measured.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class StructuredOutputCapability:
    provider: str
    model: str
    structured_output_supported: bool
    mode: str
    status: str
    configuration: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_structured_output_capability(provider: Any, model: str | None = None) -> StructuredOutputCapability:
    """Detect an explicit provider-level structured-output adapter seam.

    Merely accepting a schema in a prompt is not capability evidence. The
    adapter must expose ``send_structured_message``; otherwise the result is
    explicitly unsupported and no provider call is attempted.
    """
    provider_name = str(getattr(provider, "provider_id", type(provider).__name__))
    resolved_model = str(model or getattr(provider, "resolved_model_id", "UNKNOWN"))
    adapter = getattr(provider, "adapter", None)
    supported = callable(getattr(adapter, "send_structured_message", None))
    return StructuredOutputCapability(
        provider=provider_name,
        model=resolved_model,
        structured_output_supported=supported,
        mode="structured",
        status="SUPPORTED" if supported else "UNSUPPORTED",
        configuration={
            "transport": "provider_level",
            "adapter_method": "send_structured_message",
            "schema_passed_to_adapter": True,
        },
    )
