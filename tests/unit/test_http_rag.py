"""Tests for the live HTTP RAG adapter against a loopback stub server.

The stub is a standard-library HTTP server on 127.0.0.1, so the tests are
hermetic - no docker backend and no external network.
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import UUID

import pytest

from sectum.adapters.rag.http import HttpRAGPipeline

_TENANT = UUID(int=0xA)


class _StubHandler(BaseHTTPRequestHandler):
    """A RAG endpoint stub: it echoes the request and returns two hits.

    ``POST /badresponse`` returns a JSON array instead of an object, and
    ``POST /baditem`` returns a retrieved item that is not an object - both
    exercise the adapter's response validation.
    """

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if self.path == "/badresponse":
            payload: object = ["not", "an", "object"]
        elif self.path == "/baditem":
            payload = {"answer": "x", "retrieved": ["not-an-object"]}
        else:
            auth = self.headers.get("Authorization", "none")
            answer = f"tenant={request['tenant']} query={request['query']} auth={auth}"
            payload = {
                "answer": answer,
                "retrieved": [
                    {"doc_id": "d-1", "content": "first hit", "score": 0.9},
                    {"doc_id": "d-2", "content": "second hit"},
                ],
            }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def rag_url() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_rag_round_trips_a_query(rag_url: str) -> None:
    rag = HttpRAGPipeline(rag_url)
    answer = rag.ask(_TENANT, "find the canary")
    assert "find the canary" in answer.answer
    assert str(_TENANT) in answer.answer
    assert [hit.doc_id for hit in answer.retrieved] == ["d-1", "d-2"]
    assert all(hit.tenant_id == _TENANT for hit in answer.retrieved)
    assert answer.retrieved[0].score == 0.9
    assert answer.retrieved[1].score == 1.0


def test_http_rag_sends_configured_headers(rag_url: str) -> None:
    rag = HttpRAGPipeline(rag_url, headers={"Authorization": "Bearer token"})
    answer = rag.ask(_TENANT, "ping")
    assert "auth=Bearer token" in answer.answer


def test_http_rag_rejects_a_non_http_url() -> None:
    with pytest.raises(ValueError, match="http"):
        HttpRAGPipeline("file:///etc/passwd")


def test_http_rag_rejects_a_non_object_response(rag_url: str) -> None:
    rag = HttpRAGPipeline(rag_url + "badresponse")
    with pytest.raises(ValueError, match="JSON object"):
        rag.ask(_TENANT, "anything")


def test_http_rag_rejects_a_non_object_retrieved_item(rag_url: str) -> None:
    rag = HttpRAGPipeline(rag_url + "baditem")
    with pytest.raises(ValueError, match="JSON object"):
        rag.ask(_TENANT, "anything")
