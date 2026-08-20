"""P8-B2-LIVE-01-REPAIR-01: MCP protocol version negotiation regression tests.

The pinned Harness crashes when our stdio MCP server reports a protocol
version the MCP SDK does not support ("Server's protocol version is not
supported: 1"). These deterministic offline tests lock the negotiation.
"""
from __future__ import annotations

import pytest

from research_os.agent_runtime.mcp.contracts import (
    DEFAULT_MCP_PROTOCOL_VERSION,
    SUPPORTED_MCP_PROTOCOL_VERSIONS,
    negotiate_mcp_protocol_version,
)


@pytest.mark.parametrize("version", SUPPORTED_MCP_PROTOCOL_VERSIONS)
def test_supported_client_version_is_echoed(version):
    assert negotiate_mcp_protocol_version(version) == version


def test_legacy_numeric_version_falls_back_to_supported_baseline():
    # The pre-repair server replied "1"; the MCP SDK rejects it.
    negotiated = negotiate_mcp_protocol_version("1")
    assert negotiated in SUPPORTED_MCP_PROTOCOL_VERSIONS
    assert negotiated == DEFAULT_MCP_PROTOCOL_VERSION


def test_missing_client_version_falls_back_to_supported_baseline():
    negotiated = negotiate_mcp_protocol_version(None)
    assert negotiated in SUPPORTED_MCP_PROTOCOL_VERSIONS


def test_unknown_client_version_falls_back_to_supported_baseline():
    negotiated = negotiate_mcp_protocol_version("1999-01-01")
    assert negotiated == DEFAULT_MCP_PROTOCOL_VERSION


def test_default_baseline_is_sdk_supported():
    assert DEFAULT_MCP_PROTOCOL_VERSION in SUPPORTED_MCP_PROTOCOL_VERSIONS
