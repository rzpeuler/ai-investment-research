"""P7-D2 Foundation execution policy is strict, disabled, and read-only."""
from __future__ import annotations

from pathlib import Path

import pytest

from research_os.data_layer.execution_policy import ExecutionPolicyRegistry


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "data_acquisition_execution.yaml"


def _write_policy(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_checked_in_foundation_policy_is_exact_and_disabled() -> None:
    policy = ExecutionPolicyRegistry(POLICY_PATH).load()
    assert policy.enabled is False
    assert policy.allowed_actions == ("route_existing_sources",)
    # P7-D3：allowlist 恰好为治理批准的 [nbs, cninfo]（enabled 仍 false）
    assert policy.production_collector_ids == ("nbs", "cninfo")


@pytest.mark.parametrize(
    "text",
    [
        "enabled: false\nallowed_actions: [route_existing_sources]\n",
        "enabled: false\nproduction_collector_ids: []\n",
        "allowed_actions: [route_existing_sources]\nproduction_collector_ids: []\n",
    ],
)
def test_all_policy_fields_are_required(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError, match="fields"):
        ExecutionPolicyRegistry(_write_policy(tmp_path, text)).load()


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    path = _write_policy(tmp_path, (
        "enabled: false\nallowed_actions: [route_existing_sources]\n"
        "production_collector_ids: []\nnetwork_enabled: true\n"
    ))
    with pytest.raises(ValueError, match="fields"):
        ExecutionPolicyRegistry(path).load()


@pytest.mark.parametrize(
    "actions", ["[]", "[derive_existing]", "[route_existing_sources, route_existing_sources]"],
)
def test_allowed_actions_are_exact(tmp_path: Path, actions: str) -> None:
    path = _write_policy(tmp_path, (
        f"enabled: false\nallowed_actions: {actions}\nproduction_collector_ids: []\n"
    ))
    with pytest.raises(ValueError, match="allowed_actions"):
        ExecutionPolicyRegistry(path).load()


def test_enabled_true_is_rejected_for_foundation(tmp_path: Path) -> None:
    path = _write_policy(tmp_path, (
        "enabled: true\nallowed_actions: [route_existing_sources]\n"
        "production_collector_ids: []\n"
    ))
    with pytest.raises(ValueError, match="enabled"):
        ExecutionPolicyRegistry(path).load()


def test_duplicate_collector_ids_are_rejected(tmp_path: Path) -> None:
    path = _write_policy(tmp_path, (
        "enabled: false\nallowed_actions: [route_existing_sources]\n"
        "production_collector_ids: [collector_a, collector_a]\n"
    ))
    with pytest.raises(ValueError, match="duplicate"):
        ExecutionPolicyRegistry(path).load()


def test_unapproved_production_collector_is_rejected(tmp_path: Path) -> None:
    # 未治理批准的 source_id 不得进入 allowlist（fail closed）
    path = _write_policy(tmp_path, (
        "enabled: false\nallowed_actions: [route_existing_sources]\n"
        "production_collector_ids: [collector_a]\n"
    ))
    with pytest.raises(ValueError, match="allowlist"):
        ExecutionPolicyRegistry(path).load()


def test_partial_allowlist_is_rejected(tmp_path: Path) -> None:
    # 只批准部分来源也拒绝：本阶段 allowlist 必须恰好为治理批准的完整集合
    path = _write_policy(tmp_path, (
        "enabled: false\nallowed_actions: [route_existing_sources]\n"
        "production_collector_ids: [nbs]\n"
    ))
    with pytest.raises(ValueError, match="allowlist"):
        ExecutionPolicyRegistry(path).load()


def test_registry_only_reads_policy_file_and_returns_immutable_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket
    import urllib.request

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network called"))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("network called"))
    before = POLICY_PATH.read_bytes()
    policy = ExecutionPolicyRegistry(POLICY_PATH).load()
    assert POLICY_PATH.read_bytes() == before
    assert isinstance(policy.allowed_actions, tuple)
    assert isinstance(policy.production_collector_ids, tuple)


@pytest.mark.parametrize("text", ["[]\n", "enabled: false\nallowed_actions: nope\nproduction_collector_ids: []\n"])
def test_yaml_shape_is_strict(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError):
        ExecutionPolicyRegistry(_write_policy(tmp_path, text)).load()


@pytest.mark.parametrize(
    "text",
    [
        (
            "enabled: true\nenabled: false\n"
            "allowed_actions: [route_existing_sources]\nproduction_collector_ids: []\n"
        ),
        (
            "enabled: false\nallowed_actions: [route_existing_sources]\n"
            "allowed_actions: [route_existing_sources]\nproduction_collector_ids: []\n"
        ),
        (
            "enabled: false\nallowed_actions: [route_existing_sources]\n"
            "production_collector_ids: []\nmetadata:\n  key: one\n  key: two\n"
        ),
    ],
)
def test_duplicate_yaml_mapping_keys_are_rejected_at_any_depth(
    tmp_path: Path, text: str,
) -> None:
    with pytest.raises(ValueError, match="duplicate YAML mapping key"):
        ExecutionPolicyRegistry(_write_policy(tmp_path, text)).load()


def test_non_string_yaml_mapping_key_is_normalized_to_value_error(tmp_path: Path) -> None:
    path = _write_policy(tmp_path, (
        "enabled: false\nallowed_actions: [route_existing_sources]\n"
        "production_collector_ids: []\n1: unexpected\nfoo: unexpected\n"
    ))
    with pytest.raises(ValueError, match="mapping keys must be strings"):
        ExecutionPolicyRegistry(path).load()
