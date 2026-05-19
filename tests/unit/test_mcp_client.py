"""Tests for the live MCP client adapter against a stdio stub server.

The stub (``mcp_server_stub.py``) is launched as a subprocess, so the tests are
hermetic - no docker backend and no external network.
"""

import sys
from pathlib import Path
from uuid import UUID

import pytest

from sectum.adapters.base import Capability
from sectum.adapters.mcp.client import StdioMCPClient
from sectum.spec import AdapterError

_TENANT = UUID(int=0xA)
_STUB = str(Path(__file__).parent / "mcp_server_stub.py")


def _client() -> StdioMCPClient:
    return StdioMCPClient(sys.executable, [_STUB])


def test_mcp_lists_the_server_tools() -> None:
    client = _client()
    assert client.list_tools() == ["echo", "whoami"]
    assert client.supports(Capability.TOOL_INVOCATION)


def test_mcp_invokes_a_tool() -> None:
    result = _client().invoke(_TENANT, "echo", {"text": "the canary is here"})
    assert result.tool == "echo"
    assert result.output == "the canary is here"


def test_mcp_does_not_forward_the_tenant_by_default() -> None:
    # a generic MCP call carries no tenant identity
    result = _client().invoke(_TENANT, "whoami", {})
    assert result.output == "tenant=anonymous"


def test_mcp_forwards_the_tenant_when_configured() -> None:
    client = StdioMCPClient(sys.executable, [_STUB], tenant_argument="tenant")
    result = client.invoke(_TENANT, "whoami", {})
    assert result.output == f"tenant={_TENANT}"


def test_mcp_raises_on_a_failed_tool_call() -> None:
    with pytest.raises(AdapterError, match="failed"):
        _client().invoke(_TENANT, "nonexistent", {})
