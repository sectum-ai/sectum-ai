"""Tests for the live HTTP MCP client adapter against an in-memory stub server.

The streamable-HTTP transport is monkeypatched to a pair of in-memory streams
wired to a FastMCP server running in the same process, so the tests are
hermetic - no HTTP server is spawned and no network is touched. The adapter's
own logic (initialise the session, list tools, call a tool, forward the tenant
under ``tenant_argument``, surface a tool failure as ``AdapterError``) is what
this test verifies; the streamable-HTTP wire format is the SDK's responsibility.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from uuid import UUID

import anyio
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_client_server_memory_streams

from sectum_ai.adapters.base import Capability
from sectum_ai.adapters.mcp.http import HttpMCPClient
from sectum_ai.spec import AdapterError

_TENANT = UUID(int=0xA)
_URL = "http://stub.invalid/mcp"


def _server() -> FastMCP:
    server = FastMCP("sectum-http-stub")

    @server.tool()
    def echo(text: str) -> str:
        return text

    @server.tool()
    def whoami(tenant: str = "anonymous", user: str | None = None) -> str:
        return f"tenant={tenant}" + (f" user={user}" if user is not None else "")

    return server


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Route ``streamablehttp_client`` calls to an in-memory FastMCP server.

    Each `async with` opens a fresh memory-stream pair and a new server task,
    matching the real HTTP transport's one-session-per-context lifecycle.
    """

    @asynccontextmanager
    async def fake_streamablehttp_client(
        url: str, headers: dict[str, str] | None = None, timeout: float = 30.0
    ) -> AsyncIterator[tuple[object, object, object]]:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            client_read, client_write = client_streams
            server_read, server_write = server_streams
            server = _server()._mcp_server
            async with anyio.create_task_group() as tg:
                tg.start_soon(
                    lambda: server.run(
                        server_read,
                        server_write,
                        server.create_initialization_options(),
                        raise_exceptions=False,
                    )
                )
                try:
                    yield client_read, client_write, lambda: None
                finally:
                    tg.cancel_scope.cancel()

    monkeypatch.setattr(
        "sectum_ai.adapters.mcp.http.streamablehttp_client", fake_streamablehttp_client
    )
    yield


def _client(*, tenant_argument: str | None = None) -> HttpMCPClient:
    return HttpMCPClient(_URL, tenant_argument=tenant_argument)


def test_http_mcp_conforms_and_lists_tools(patched: None) -> None:
    client = _client()
    assert client.supports(Capability.TOOL_INVOCATION)
    assert client.list_tools() == ["echo", "whoami"]


def test_http_mcp_invokes_a_tool(patched: None) -> None:
    result = _client().invoke(_TENANT, "echo", {"text": "the canary is here"})
    assert result.tool == "echo"
    assert result.output == "the canary is here"


def test_http_mcp_does_not_forward_the_tenant_by_default(patched: None) -> None:
    # a generic MCP call carries no tenant identity - the Class 7 confused-deputy
    # gap the probes are built to catch
    result = _client().invoke(_TENANT, "whoami", {})
    assert result.output == "tenant=anonymous"


def test_http_mcp_forwards_the_tenant_when_configured(patched: None) -> None:
    # the adapter must faithfully transmit tenant context so the Class 7 probes
    # can find a server that drops it
    client = _client(tenant_argument="tenant")
    result = client.invoke(_TENANT, "whoami", {})
    assert result.output == f"tenant={_TENANT}"


def test_http_mcp_raises_on_a_failed_tool_call(patched: None) -> None:
    with pytest.raises(AdapterError, match="failed"):
        _client().invoke(_TENANT, "nonexistent", {})


def test_http_mcp_forwards_the_user_only_when_configured(patched: None) -> None:
    # `invoke(..., user=)` was accepted and dropped, so a probe's user-level step
    # reached the server as the tenant and was judged as the user. The adapter
    # declares whether it carries the user, and does so only via `user_argument`.
    user = UUID(int=0xB1)
    default = _client()
    assert not default.carries_user
    assert default.invoke(_TENANT, "whoami", {}, user=user).output == "tenant=anonymous"
    client = HttpMCPClient(_URL, tenant_argument="tenant", user_argument="user")
    assert client.carries_user
    assert client.invoke(_TENANT, "whoami", {}, user=user).output == f"tenant={_TENANT} user={user}"
