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
import urllib.error
import urllib.request
from urllib.parse import urlparse
from uuid import UUID

from sectum_ai.adapters.base import AgentAdapter, AgentResult, Capability
from sectum_ai.spec import AdapterError


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
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read())
        # `UnicodeDecodeError` is a sibling of `JSONDecodeError`, not a subclass,
        # so a non-UTF-8 body escaped this tuple - and the broad wrap added for
        # exactly that case starts AFTER this block, so it never caught it either.
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as error:
            raise AdapterError(f"agent HTTP request to {self._url} failed: {error}") from error
        if not isinstance(body, dict):
            raise AdapterError(f"agent response must be a JSON object, got {type(body).__name__}")
        # A 200 carrying an error envelope is not a run: read as an empty one, the
        # step recorded "the agent invoked no foreign tool", which is a verdict the
        # probe never obtained.
        for key in ("error", "errors"):
            if body.get(key):
                raise AdapterError(
                    f"agent endpoint at {self._url} returned an error: {str(body[key])[:200]}"
                )
        # Any failure SHAPING the response is an adapter failure too, not a crash.
        # The catch above named three transport errors, so a 200 whose body is
        # well-formed JSON of the wrong shape - `"tool_calls": null`, a non-UTF-8
        # body - escaped as a bare `TypeError`/`UnicodeDecodeError`, which is not
        # this contract's error type and so escapes the runner's handling of it. Six
        # sibling agent adapters wrap broadly for exactly that reason.
        # `output` is the declared key and the only thing the probe pipeline reads.
        # Defaulting it made an UNREADABLE answer indistinguishable from an empty
        # one, in both directions: `{"output": null}` became the literal string
        # "None", which is truthy, so the runner recorded RETURNED and Class 7
        # graded a manufactured string as "the agent answered and surfaced no
        # foreign canary"; and a body whose answer sat under another key was
        # dropped whole - including one carrying a foreign canary, recorded as a
        # clean agent surface. Every sibling field in this method is already
        # refused rather than defaulted, each with a comment naming this exact
        # consequence; `output` was the one left lenient. `{"output": ""}` is a
        # genuine empty answer and still passes.
        output = body.get("output")
        if not isinstance(output, str):
            raise AdapterError(
                f"agent endpoint at {self._url} returned no string 'output' "
                f"(got {type(output).__name__}); an unreadable answer is not an empty one"
            )
        try:
            tool_calls = tuple(str(call) for call in body.get("tool_calls", []))
            return AgentResult(output=output, tool_calls=tool_calls)
        except AdapterError:
            raise
        except Exception as error:
            raise AdapterError(
                f"agent endpoint at {self._url} returned a body this adapter cannot read: {error}"
            ) from error
