"""Live HTTP RAG adapter: a RAG pipeline reached over a JSON HTTP API.

This is the generic connector for a retrieval-augmented-generation service
that exposes an HTTP endpoint. ``ask`` POSTs a JSON request and parses a JSON
response, so it reaches any pipeline that adopts the small contract below
without a backend-specific SDK.

The request body (``POST`` to the configured URL) is::

    {"tenant": "<tenant uuid>", "query": "<query text>"}

The response body is::

    {"answer": "<answer text>",
     "retrieved": [{"doc_id": "<id>", "content": "<text>", "score": <float>}]}

A retrieved item's ``score`` is optional and defaults to ``1.0``. Only the
standard library is used, so this adapter needs no optional extra.
"""

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse
from uuid import UUID

from sectum.adapters.base import RagAnswer, RAGPipelineAdapter, VectorHit
from sectum.spec import AdapterError


class HttpRAGPipeline(RAGPipelineAdapter):
    """A RAG pipeline reached over a JSON HTTP API."""

    def __init__(
        self,
        url: str,
        *,
        name: str = "http-rag",
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        if urlparse(url).scheme not in ("http", "https"):
            raise AdapterError(f"url must be an http(s) URL: {url!r}")
        super().__init__(name)
        self._url = url
        self._headers = dict(headers) if headers else {}
        self._timeout = timeout

    def ask(self, tenant: UUID, query: str) -> RagAnswer:
        payload = json.dumps({"tenant": str(tenant), "query": query}).encode("utf-8")
        request = urllib.request.Request(
            self._url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", **self._headers},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise AdapterError(f"RAG HTTP request to {self._url} failed: {error}") from error
        if not isinstance(body, dict):
            raise AdapterError(f"RAG response must be a JSON object, got {type(body).__name__}")
        retrieved = tuple(self._hit(tenant, item) for item in body.get("retrieved", []))
        return RagAnswer(answer=str(body.get("answer", "")), retrieved=retrieved)

    @staticmethod
    def _hit(tenant: UUID, item: object) -> VectorHit:
        """Parse one retrieved item from the response into a ``VectorHit``."""
        if not isinstance(item, dict):
            raise AdapterError(f"retrieved item must be a JSON object, got {type(item).__name__}")
        return VectorHit(
            doc_id=str(item.get("doc_id", "")),
            tenant_id=tenant,
            score=float(item.get("score", 1.0)),
            content=str(item.get("content", "")),
        )
