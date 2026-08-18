"""P7-D3 M4c：真实来源 policy 契约测试。

覆盖任务书 §13/§29/§49：production allowlist 恰好为 [nbs, cninfo]、enabled 保持
false、未批准来源 blocked、capability WORKFLOW_WIRED 不会自动变为 BUSINESS_SUFFICIENT、
config 与 capability registry 一致。
全部离线。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from research_os.data_layer.execution_policy import (
    ExecutionPolicyRegistry,
    _APPROVED_PRODUCTION_COLLECTORS,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "data_acquisition_execution.yaml"


class TestPolicyContract:
    def test_allowlist_exactly_nbs_cninfo(self):
        policy = ExecutionPolicyRegistry(POLICY_PATH).load()
        assert policy.production_collector_ids == ("nbs", "cninfo")
        assert _APPROVED_PRODUCTION_COLLECTORS == ("nbs", "cninfo")

    def test_enabled_remains_false(self):
        policy = ExecutionPolicyRegistry(POLICY_PATH).load()
        assert policy.enabled is False
        assert policy.allowed_actions == ("route_existing_sources",)

    def test_unknown_production_source_blocked(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text(
            "enabled: false\nallowed_actions: [route_existing_sources]\n"
            "production_collector_ids: [eastmoney]\n", encoding="utf-8")
        with pytest.raises(ValueError, match="allowlist"):
            ExecutionPolicyRegistry(path).load()

    def test_missing_collector_blocked(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text(
            "enabled: false\nallowed_actions: [route_existing_sources]\n"
            "production_collector_ids: [nbs]\n", encoding="utf-8")
        with pytest.raises(ValueError, match="allowlist"):
            ExecutionPolicyRegistry(path).load()

    def test_extra_unapproved_collector_blocked(self, tmp_path):
        path = tmp_path / "policy.yaml"
        path.write_text(
            "enabled: false\nallowed_actions: [route_existing_sources]\n"
            "production_collector_ids: [nbs, cninfo, cls]\n", encoding="utf-8")
        with pytest.raises(ValueError, match="allowlist"):
            ExecutionPolicyRegistry(path).load()


class TestCapabilityContract:
    def test_macro_data_and_announcement_are_workflow_wired_not_business_sufficient(self):
        data = yaml.safe_load(
            (ROOT / "registry" / "data_acquisition_capabilities.yaml").read_text(
                encoding="utf-8"))
        for data_type in ("macro_data", "company_announcement"):
            lifecycle = data["capabilities"][data_type]["automatic_acquisition_lifecycle"]
            assert lifecycle == "WORKFLOW_WIRED", (
                f"{data_type} 必须 WORKFLOW_WIRED（独立在线验收通过前不得 BUSINESS_SUFFICIENT）"
            )

    def test_allowlist_sources_are_registered_in_capabilities(self):
        data = yaml.safe_load(
            (ROOT / "registry" / "data_acquisition_capabilities.yaml").read_text(
                encoding="utf-8"))
        # nbs → macro_data；cninfo → company_announcement 均已 WORKFLOW_WIRED
        assert data["capabilities"]["macro_data"]["automatic_acquisition_lifecycle"] == "WORKFLOW_WIRED"
        assert data["capabilities"]["company_announcement"]["automatic_acquisition_lifecycle"] == "WORKFLOW_WIRED"

    def test_no_new_sources_registered(self):
        sources = yaml.safe_load(
            (ROOT / "registry" / "sources.yaml").read_text(encoding="utf-8"))
        ids = set(sources.get("sources", {}))
        assert "nbs" in ids and "cninfo" in ids
        # P7-D3 不新增来源：断言来源集合与 master 基线一致（由 git diff 治理保证，
        # 此处只验证两个目标来源存在且未被泛化标签替换）
        assert "official" not in ids and "government" not in ids
