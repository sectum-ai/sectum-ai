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
from uuid import UUID

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import TextContent

from sectum.adapters.base import Capability, MCPAdapter, McpResult
from sectum.spec import AdapterError


class HttpMCPClient(MCPAdapter):
    """A Model Context Protocol client that speaks to a streamable HTTP server.

    Scopes by tenant. ``user`` is accepted on ``invoke`` for interface
    conformance (ADR-0008) but not yet enforced - per-user tool scoping is a
    follow-on - so this adapter does not report ``USER_SCOPED``.
    """

    def __init__(
        self,
        url: str,
        *,
        name: str = "mcp",
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        tenant_argument: str | None = None,
    ) -> None:
        super().__init__(name, frozenset({Capability.TOOL_INVOCATION}))
        self._url = url
        self._headers = dict(headers) if headers else None
        self._timeout = timeout
        self._tenant_argument = tenant_argument

    def list_tools(self) -> list[str]:
        return asyncio.run(self._list_tools())

    def invoke(
        self, tenant: UUID, tool: str, arguments: dict[str, str], *, user: UUID | None = None
    ) -> McpResult:
        return asyncio.run(self._invoke(tenant, tool, arguments))

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

    async def _invoke(self, tenant: UUID, tool: str, arguments: dict[str, str]) -> McpResult:
        call_arguments: dict[str, str] = dict(arguments)
        if self._tenant_argument is not None:
            call_arguments[self._tenant_argument] = str(tenant)
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
