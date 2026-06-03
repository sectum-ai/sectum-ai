"""Opt-in live integration test for the streamable-HTTP MCP client adapter.

Skipped unless ``SECTUM_MCP_HTTP_URL`` is set (the engineering spec, section 13:
opt-in live). The target server must expose a tool named in
``SECTUM_MCP_HTTP_TOOL`` (default: ``echo``) that returns the value of its
``text`` argument unchanged - matching the stdio stub used in the unit tests.

Enable with ``pip install sectum-ai-adapters[mcp]`` and the env vars; the
adapter logic itself is covered offline by
``tests/unit/test_mcp_http_client.py``.
"""

import os
from collections.abc import Iterator
from uuid import UUID

import pytest
from sectum_ai.adapters.mcp.http import HttpMCPClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("SECTUM_MCP_HTTP_URL"),
        reason="set SECTUM_MCP_HTTP_URL to run the live HTTP MCP test",
    ),
]

_TENANT = UUID(int=0xA)
_TOOL = os.environ.get("SECTUM_MCP_HTTP_TOOL", "echo")
_TEXT = "the canary is here"


@pytest.fixture
def client() -> Iterator[HttpMCPClient]:
    url = os.environ["SECTUM_MCP_HTTP_URL"]
    instance = HttpMCPClient(url)
    try:
        # confirm reachability before the test exercises the tool
        if _TOOL not in instance.list_tools():
            pytest.skip(f"server at {url!r} does not expose tool {_TOOL!r}")
    except Exception as error:
        pytest.skip(f"HTTP MCP backend not reachable: {error}")
    yield instance


def test_http_mcp_round_trips_a_tool_call(client: HttpMCPClient) -> None:
    result = client.invoke(_TENANT, _TOOL, {"text": _TEXT})
    assert result.tool == _TOOL
    assert _TEXT in result.output
