"""Live MCP adapter: a generic Model Context Protocol client over HTTP.

This adapter opens a streamable HTTP session against a remote MCP server (the
transport the ``mcp`` Python SDK exposes as ``streamablehttp_client``), so a
hosted MCP integration is reachable without a stdio subprocess. ``list_tools``
enumerates the server's tools and ``invoke`` calls one.

A generic MCP call carries no tenant identity: the protocol has no tenant
channel, which is exactly the confused-deputy gap Class 7 examines. When a
server does accept a tenant-scoping argument, set ``tenant_argument`` so
``invoke`` forwards the calling tenant under that key; the adapter must
faithfully transmit tenant context so the Class 7 probes can find a server
that drops it.

Requires the ``mcp`` optional dependency: ``pip install sectum-ai-adapters[mcp]``.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse
from uuid import UUID

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import TextContent

from sectum_ai.adapters.base import Capability, MCPAdapter, McpResult
from sectum_ai.spec import AdapterError


class HttpMCPClient(MCPAdapter):
    """A Model Context Protocol client that speaks to a streamable HTTP server.

    Scopes by tenant. ``user`` is forwarded to the server when ``user_argument``
    names the tool argument that carries it (ADR-0008), and ``carries_user``
    reports whether it does. Left unconfigured, the adapter transmits no user and
    the runner DROPS user-level steps rather than running them as the tenant.
    """

    def __init__(
        self,
        url: str,
        *,
        name: str = "mcp",
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        tenant_argument: str | None = None,
        user_argument: str | None = None,
    ) -> None:
        # The third HTTP adapter, and the one that took any string: `file:///...`,
        # `ftp://...` and a bare word were all accepted, to fail later inside the
        # transport as an opaque error rather than at the point the operator made
        # the typo. Both siblings refuse at construction.
        if urlparse(url).scheme not in ("http", "https"):
            raise AdapterError(f"url must be an http(s) URL: {url!r}")
        super().__init__(name, frozenset({Capability.TOOL_INVOCATION}))
        # A generic MCP call carries no user identity; the probes' user-level
        # steps used to run as the tenant and be judged as the user. Only with a
        # ``user_argument`` does a call reach the server as the user.
        self._user_argument = user_argument
        self.carries_user = user_argument is not None
        self._url = url
        self._headers = dict(headers) if headers else None
        self._timeout = timeout
        self._tenant_argument = tenant_argument

    def list_tools(self) -> list[str]:
        # Only the TOOL-level `isError` became an `AdapterError`; a transport or
        # protocol failure - a refused connection, a TLS error, a malformed frame -
        # came out as whatever the MCP SDK raised. That is not this contract's error
        # type, so it escapes the runner's handling of an adapter failure and takes
        # the whole run with it, where every agent adapter wraps instead.
        with _as_adapter_error(f"MCP server at {self._url}"):
            return asyncio.run(self._list_tools())

    def invoke(
        self, tenant: UUID, tool: str, arguments: dict[str, str], *, user: UUID | None = None
    ) -> McpResult:
        with _as_adapter_error(f"MCP server at {self._url}"):
            return asyncio.run(self._invoke(tenant, tool, arguments, user))

    async def _list_tools(self) -> list[str]:
        async with (
            streamablehttp_client(self._url, headers=self._headers, timeout=self._timeout) as (
                read,
                write,
                _,
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.list_tools()
        return sorted(tool.name for tool in result.tools)

    async def _invoke(
        self, tenant: UUID, tool: str, arguments: dict[str, str], user: UUID | None
    ) -> McpResult:
        call_arguments: dict[str, str] = dict(arguments)
        if self._tenant_argument is not None:
            call_arguments[self._tenant_argument] = str(tenant)
        if self._user_argument is not None and user is not None:
            call_arguments[self._user_argument] = str(user)
        async with (
            streamablehttp_client(self._url, headers=self._headers, timeout=self._timeout) as (
                read,
                write,
                _,
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(tool, dict(call_arguments))
        output = "".join(block.text for block in result.content if isinstance(block, TextContent))
        if result.isError:
            raise AdapterError(f"MCP tool {tool!r} failed: {output}")
        return McpResult(tool=tool, output=output)


@contextmanager
def _as_adapter_error(what: str) -> Iterator[None]:
    """Re-raise anything the MCP SDK throws as the adapter contract's error."""
    try:
        yield
    except AdapterError:
        raise
    except Exception as error:
        raise AdapterError(f"{what} failed: {error}") from error
