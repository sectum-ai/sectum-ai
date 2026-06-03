"""Tests for the live HTTP agent adapter against a loopback stub server.

The stub is a standard-library HTTP server on 127.0.0.1, so the tests are
hermetic - no docker backend and no external network.
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import UUID

import pytest
from sectum_ai.adapters.agent.http import HttpAgent
from sectum_ai.spec import AdapterError

_TENANT = UUID(int=0xA)


class _StubHandler(BaseHTTPRequestHandler):
    """An agent endpoint stub: it echoes the request and reports two tool calls.

    ``POST /notools`` omits the optional ``tool_calls`` list, and
    ``POST /badresponse`` returns a JSON array instead of an object - both
    exercise the adapter's response handling.
    """

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if self.path == "/notjson":
            raw = b"<html>not json</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path == "/badresponse":
            payload: object = ["not", "an", "object"]
        elif self.path == "/notools":
            payload = {"output": "done"}
        else:
            auth = self.headers.get("Authorization", "none")
            output = f"tenant={request['tenant']} task={request['task']} auth={auth}"
            payload = {"output": output, "tool_calls": ["search", "summarize"]}
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def agent_url() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_agent_runs_a_task(agent_url: str) -> None:
    agent = HttpAgent(agent_url)
    result = agent.run(_TENANT, "summarize the backlog")
    assert "summarize the backlog" in result.output
    assert str(_TENANT) in result.output
    assert result.tool_calls == ("search", "summarize")


def test_http_agent_sends_configured_headers(agent_url: str) -> None:
    agent = HttpAgent(agent_url, headers={"Authorization": "Bearer token"})
    result = agent.run(_TENANT, "ping")
    assert "auth=Bearer token" in result.output


def test_http_agent_defaults_tool_calls_to_empty(agent_url: str) -> None:
    agent = HttpAgent(agent_url + "notools")
    result = agent.run(_TENANT, "anything")
    assert result.output == "done"
    assert result.tool_calls == ()


def test_http_agent_rejects_a_non_http_url() -> None:
    with pytest.raises(AdapterError, match="http"):
        HttpAgent("file:///etc/passwd")


def test_http_agent_rejects_a_non_object_response(agent_url: str) -> None:
    agent = HttpAgent(agent_url + "badresponse")
    with pytest.raises(AdapterError, match="JSON object"):
        agent.run(_TENANT, "anything")


def test_http_agent_wraps_a_non_json_response_in_adapter_error(agent_url: str) -> None:
    # A non-JSON body must surface as AdapterError, not a raw json.JSONDecodeError,
    # so the CLI's typed-error exit path is honored rather than an opaque crash.
    agent = HttpAgent(agent_url + "notjson")
    with pytest.raises(AdapterError, match="failed"):
        agent.run(_TENANT, "anything")
