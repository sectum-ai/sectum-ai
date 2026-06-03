"""Live MCP adapters.

Each module here connects to one real Model Context Protocol backend and is
imported explicitly (for example
``from sectum_ai.adapters.mcp.client import StdioMCPClient`` for a stdio server
or ``from sectum_ai.adapters.mcp.http import HttpMCPClient`` for a streamable
HTTP one).
"""
