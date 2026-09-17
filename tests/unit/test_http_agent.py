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
        elif self.path == "/nulltools":
            payload = {"output": "done", "tool_calls": None}
        elif self.path == "/nulloutput":
            payload = {"output": None}
        elif self.path == "/otherkey":
            payload = {"result": "the answer mentions SECTUM-CANARY-FOREIGN"}
        elif self.path == "/nooutput":
            payload = {"tool_calls": ["search"]}
        elif self.path == "/emptyoutput":
            payload = {"output": ""}
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


def test_http_agent_wraps_a_body_it_cannot_shape_in_adapter_error(agent_url: str) -> None:
    # The catch named three TRANSPORT errors, so a 200 carrying well-formed JSON of
    # the wrong shape - `"tool_calls": null` - escaped as a bare TypeError. That is
    # not this contract's error type, so it escapes the runner's handling of an
    # adapter failure and takes the whole run with it. Six sibling agent adapters
    # wrap broadly for exactly that reason.
    agent = HttpAgent(agent_url + "nulltools")
    with pytest.raises(AdapterError, match="cannot"):
        agent.run(_TENANT, "anything")


def test_http_agent_wraps_a_non_json_response_in_adapter_error(agent_url: str) -> None:
    # A non-JSON body must surface as AdapterError, not a raw json.JSONDecodeError,
    # so the CLI's typed-error exit path is honored rather than an opaque crash.
    agent = HttpAgent(agent_url + "notjson")
    with pytest.raises(AdapterError, match="failed"):
        agent.run(_TENANT, "anything")


@pytest.mark.parametrize(
    ("path", "kind"),
    [("nulloutput", "NoneType"), ("otherkey", "NoneType"), ("nooutput", "NoneType")],
)
def test_an_unreadable_answer_is_refused_and_not_read_as_an_empty_one(
    agent_url: str, path: str, kind: str
) -> None:
    # `str(body.get("output", ""))` made two false verdicts reachable on a 200.
    # `{"output": null}` became the literal string "None" - truthy - so the runner
    # recorded AccessOutcome.RETURNED and Class 7 graded a manufactured string as
    # "the agent answered and surfaced no foreign canary". And a body whose answer
    # sat under another key was dropped whole: the /otherkey stub returns one
    # carrying a foreign canary, which was recorded as a CLEAN agent surface - a
    # missed leak, the failure this product exists to prevent.
    agent = HttpAgent(agent_url + path)
    with pytest.raises(AdapterError, match=f"no string 'output' \\(got {kind}\\)"):
        agent.run(_TENANT, "anything")


def test_a_genuinely_empty_answer_is_still_an_empty_answer(agent_url: str) -> None:
    # The refusal must not swallow the real empty case: `{"output": ""}` is the
    # agent answering with nothing, which the runner records as EMPTY.
    result = HttpAgent(agent_url + "emptyoutput").run(_TENANT, "anything")
    assert result.output == ""
    assert result.tool_calls == ()


def test_the_foreign_canary_under_another_key_is_never_silently_dropped(
    agent_url: str,
) -> None:
    # Stated as its own case because it is the one that costs a finding rather
    # than fabricating one: before the fix this returned output='' at no error.
    agent = HttpAgent(agent_url + "otherkey")
    try:
        result = agent.run(_TENANT, "anything")
    except AdapterError:
        return
    raise AssertionError(
        f"an answer carrying a foreign canary was dropped and read as {result.output!r}"
    )
