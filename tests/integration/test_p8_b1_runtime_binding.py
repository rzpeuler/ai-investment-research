from __future__ import annotations

import pytest

from research_os.agent_runtime.production_runtime import HarnessProcessFactory, ProductionEvidenceProbe
from research_os.agent_runtime.runtime_supervisor import HarnessRuntimeSupervisor


def _installed() -> bool:
    return ProductionEvidenceProbe().dsh.exists()


def test_observed_rc7_profile_and_stdio_catalog():
    if not _installed():
        pytest.skip("P8-B1 local runtime package is not installed")
    evidence = ProductionEvidenceProbe().observe()
    assert evidence["evidence_source"] == "observed_runtime"
    assert evidence["version"] == "0.1.0-rc.7"
    assert evidence["mcp_handshake"]["connected"] is True
    assert evidence["mcp_namespace"] == "research-os-mcp/v1"
    assert tuple(evidence["tools"]) == ("check_data_readiness", "get_company_profile")


def test_owned_rc7_process_reaches_ready_only_after_evidence_and_cleans_up():
    if not _installed():
        pytest.skip("P8-B1 local runtime package is not installed")
    factory = HarnessProcessFactory()
    evidence = factory.observed_evidence()
    supervisor = HarnessRuntimeSupervisor(process_factory=factory)
    supervisor.start(evidence, require_credential=False)
    try:
        assert supervisor.status().process_alive is True
        assert supervisor.ready is False
        supervisor.complete_mcp_handshake(evidence["mcp_handshake"])
        assert supervisor.ready is True
    finally:
        supervisor.stop()
    assert supervisor.status().state.value == "STOPPED"
