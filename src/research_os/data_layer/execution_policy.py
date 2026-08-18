"""Strict read-only P7-D2 Foundation acquisition execution policy."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver


_POLICY_FIELDS = {"enabled", "allowed_actions", "production_collector_ids"}
_FOUNDATION_ACTIONS = ("route_existing_sources",)

# P7-D3：治理批准的 production collector allowlist。
# 只有经治理决策批准的 source_id 才能进入 allowlist；
# allowlist 只是白名单，不代表默认联网（enabled 仍必须为 false）。
_APPROVED_PRODUCTION_COLLECTORS = ("nbs", "cninfo")


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that fails closed on duplicate or non-string mapping keys."""


def _construct_strict_mapping(
    loader: _UniqueKeySafeLoader, node: MappingNode, deep: bool = False,
) -> dict[str, Any]:
    loader.flatten_mapping(node)
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ConstructorError(
                None, None, "YAML mapping keys must be strings", key_node.start_mark,
            )
        if key in mapping:
            raise ConstructorError(
                None, None, f"duplicate YAML mapping key: {key!r}", key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_strict_mapping,
)


@dataclass(frozen=True)
class ExecutionPolicy:
    """Immutable checked-in execution gate values."""

    enabled: bool
    allowed_actions: tuple[str, ...]
    production_collector_ids: tuple[str, ...]


class ExecutionPolicyRegistry:
    """Load and validate the Foundation policy without runtime or network mutation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> ExecutionPolicy:
        try:
            payload = yaml.load(
                self.path.read_text(encoding="utf-8"), Loader=_UniqueKeySafeLoader,
            )
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"invalid execution policy: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("execution policy must be a YAML object")
        if any(not isinstance(key, str) for key in payload):
            raise ValueError("execution policy mapping keys must be strings")
        keys = set(payload)
        if keys != _POLICY_FIELDS:
            missing = sorted(_POLICY_FIELDS - keys)
            unknown = sorted(keys - _POLICY_FIELDS)
            raise ValueError(f"execution policy fields mismatch: missing={missing}, unknown={unknown}")

        enabled = payload["enabled"]
        actions = payload["allowed_actions"]
        collectors = payload["production_collector_ids"]
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        if enabled:
            raise ValueError(
                "enabled must remain false: default live-data execution is OFF; "
                "only explicit --live-data authorization may run real collectors"
            )
        self._validate_string_list(actions, "allowed_actions")
        self._validate_string_list(collectors, "production_collector_ids")
        if tuple(actions) != _FOUNDATION_ACTIONS:
            raise ValueError(f"allowed_actions must equal {list(_FOUNDATION_ACTIONS)!r}")
        if len(collectors) != len(set(collectors)):
            raise ValueError("duplicate production collector IDs are forbidden")
        if tuple(collectors) != _APPROVED_PRODUCTION_COLLECTORS:
            raise ValueError(
                f"production_collector_ids must equal the governance-approved allowlist "
                f"{list(_APPROVED_PRODUCTION_COLLECTORS)!r}"
            )
        return ExecutionPolicy(
            enabled=enabled,
            allowed_actions=tuple(actions),
            production_collector_ids=tuple(collectors),
        )

    @staticmethod
    def _validate_string_list(value: Any, field: str) -> None:
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise ValueError(f"{field} must be a list of nonempty strings")
