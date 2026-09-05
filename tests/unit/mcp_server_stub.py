"""A minimal stdio MCP server for the MCP client adapter tests.

It exposes an ``echo`` tool and a tenant-aware ``whoami`` tool, and is launched
as a subprocess by ``test_mcp_client.py``. This module is a test fixture, not a
test module - pytest does not collect it.
"""

from mcp.server.fastmcp import FastMCP

server = FastMCP("sectum-stub")


@server.tool()
def echo(text: str) -> str:
    """Return ``text`` unchanged."""
    return text


@server.tool()
def whoami(tenant: str = "anonymous", user: str | None = None) -> str:
    """Return the tenant (and user, when passed) the caller identified as."""
    return f"tenant={tenant}" + (f" user={user}" if user is not None else "")


if __name__ == "__main__":
    server.run()
