"""Live HTTP agent adapter: an agent reached over a JSON HTTP API.

This is the generic connector for an agent service that exposes an HTTP
endpoint. ``run`` POSTs a JSON request and parses a JSON response, so it
reaches any agent framework that adopts the small contract below without a
framework-specific SDK.

The request body (``POST`` to the configured URL) is::

    {"tenant": "<tenant uuid>", "task": "<task text>"}

The response body is::

    {"output": "<result text>", "tool_calls": ["<tool name>", ...]}

The ``tool_calls`` list is optional. Only the standard library is used, so this
adapter needs no optional extra.
"""

import json
import urllib.request
from urllib.parse import urlparse
from uuid import UUID

from sectum.adapters.base import AgentAdapter, AgentResult, Capability
from sectum.spec import AdapterError


class HttpAgent(AgentAdapter):
    """An agent reached over a JSON HTTP API."""

    def __init__(
        self,
        url: str,
        *,
        name: str = "http-agent",
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        if urlparse(url).scheme not in ("http", "https"):
            raise AdapterError(f"url must be an http(s) URL: {url!r}")
        super().__init__(name, frozenset({Capability.TOOL_INVOCATION}))
        self._url = url
        self._headers = dict(headers) if headers else {}
        self._timeout = timeout

    def run(self, tenant: UUID, task: str) -> AgentResult:
        payload = json.dumps({"tenant": str(tenant), "task": task}).encode("utf-8")
        request = urllib.request.Request(
            self._url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", **self._headers},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            body = json.loads(response.read())
        if not isinstance(body, dict):
            raise AdapterError(f"agent response must be a JSON object, got {type(body).__name__}")
        tool_calls = tuple(str(call) for call in body.get("tool_calls", []))
        return AgentResult(output=str(body.get("output", "")), tool_calls=tool_calls)
