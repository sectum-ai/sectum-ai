"""Live generic OpenTelemetry adapter: trace search over an OTLP-JSON query endpoint.

OpenTelemetry's SDK is export-only - it has no standard *read* API - so a
generic OTel observability backend is read through whatever trace store sits
behind the collector (Jaeger, Tempo, Grafana, a vendor backend, or a thin
shim). This adapter targets any endpoint that speaks a small OTLP-JSON query
contract, so one connector reaches every OTel-compatible backend without a
backend-specific SDK.

The query contract (``POST {base_url}{query_path}``) request body is::

    {"tenant": "<tenant.hex>", "marker": "<marker text>"}

and the response body is OTLP-JSON ``resourceSpans`` (the standard
trace-export shape)::

    {"resourceSpans": [
       {"resource": {"attributes": [
            {"key": "tenant.id", "value": {"stringValue": "<tenant.hex>"}}]},
        "scopeSpans": [
           {"spans": [
              {"traceId": "<hex>", "name": "<span name>",
               "attributes": [{"key": "...", "value": {"stringValue": "..."}}]}]}]}]}

The backend is expected to scope by the ``tenant`` field, but the adapter
re-checks the per-resource tenant attribute (default ``tenant.id``) and
re-scans every span's name + attribute values for the marker, so a backend
that ignores the tenant filter is itself caught as a leak (defense in depth,
the same posture the other observability adapters take).

Erasure: ``delete`` issues ``DELETE {base_url}{query_path}?tenant=<hex>``.
A 404 is an idempotent no-op success only when a follow-up empty-marker query
shows no spans for the tenant; with spans remaining it is treated as "no delete
API" (a router answers 404 for an unimplemented method+path too). A 405 (Method
Not Allowed) or 501 (Not Implemented) means the
trace store exposes no programmatic delete at all - the same "no per-tenant
erasure API" condition the Helicone and Datadog adapters report - so ``delete``
raises ``ErasureUnsupported`` and Class 11 itemizes the surface as
*attestable-with-caveat* (data presumed retained) rather than a false erasure
success. Only the standard library is used, so this adapter needs no optional
extra.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol, Self
from uuid import UUID

from sectum_ai.adapters.base import Capability, ObservabilityAdapter, TraceHit
from sectum_ai.spec import AdapterError, ErasureUnsupported

_DEFAULT_QUERY_PATH = "/v1/traces/query"


class _OtelTraceStore(Protocol):
    """The minimal trace-store surface ``OtelObservability`` consumes.

    The live backend is an OTLP-JSON HTTP query endpoint; the unit suite
    stand-in is a deterministic in-memory mirror of the same operations.
    """

    def query(self, tenant_hex: str, marker: str) -> dict[str, Any]:
        """Return OTLP-JSON ``{"resourceSpans": [...]}`` for the tenant + marker.

        An empty ``marker`` matches every span of the tenant: ``purge`` asks it
        after a ``404`` to tell an already-empty tenant from a store that never
        implemented DELETE. A store that answers nothing to it reads as purged.
        """

    def tenant_values(self) -> set[str]:
        """Return every distinct tenant attribute value the store has seen."""

    def purge(self, tenant_hex: str) -> None:
        """Delete the tenant's spans.

        Idempotent when the spans are already absent; raises
        ``ErasureUnsupported`` when the store exposes no delete API at all.
        """


class OtelObservability(ObservabilityAdapter):
    """A generic OpenTelemetry observability backend read over an OTLP-JSON query API.

    Construct it with an open ``_OtelTraceStore`` so the adapter can be
    tested against an in-memory stand-in without a live endpoint. Use
    :meth:`connect` to build the live HTTP-backed store from a base URL.

    Scopes by tenant via the resource attribute ``tenant_attribute`` (default
    ``tenant.id``), whose value is the ``tenant.hex``. A trace whose resource
    carries a *different* tenant value but still surfaces in a tenant's query
    is reported - the cross-tenant leak the substrate verifies.
    """

    def __init__(
        self,
        store: _OtelTraceStore,
        *,
        name: str = "otel",
        tenant_attribute: str = "tenant.id",
    ) -> None:
        super().__init__(name, frozenset({Capability.TRACE_SEARCH}))
        self._store = store
        self._tenant_attribute = tenant_attribute

    @classmethod
    def connect(
        cls,
        base_url: str,
        *,
        query_path: str = _DEFAULT_QUERY_PATH,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        tenant_attribute: str = "tenant.id",
        name: str = "otel",
    ) -> Self:
        """Build the live OTLP-JSON HTTP trace store and return the adapter."""
        store = _HttpOtelTraceStore(
            base_url,
            query_path=query_path,
            headers=headers,
            timeout=timeout,
            tenant_attribute=tenant_attribute,
        )
        return cls(store, name=name, tenant_attribute=tenant_attribute)

    def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
        body = self._store.query(tenant.hex, marker)
        if "resourceSpans" not in body:
            # A 200 with an error envelope (or the wrong shape) read as "no traces"
            # - in the A3 check, as the subject's trace having been erased.
            detail = body.get("error") or body.get("errors") or sorted(body)
            raise AdapterError(f"OTel query returned no resourceSpans: {str(detail)[:200]}")
        hits: list[TraceHit] = []
        for resource_span in _as_list(body.get("resourceSpans")):
            resource = resource_span.get("resource") or {}
            tenant_value = _attribute_value(resource.get("attributes"), self._tenant_attribute)
            for scope_span in _as_list(resource_span.get("scopeSpans")):
                for span in _as_list(scope_span.get("spans")):
                    snippet = _span_snippet(span)
                    if marker in snippet:
                        hits.append(
                            TraceHit(
                                trace_id=str(span.get("traceId", "")),
                                project=tenant_value or tenant.hex,
                                snippet=snippet,
                            )
                        )
        return hits

    def list_projects(self) -> list[str]:
        return sorted(self._store.tenant_values())

    def delete(self, tenant: UUID) -> None:
        self._store.purge(tenant.hex)


class _HttpOtelTraceStore:
    """OTLP-JSON HTTP trace store backed by the standard-library HTTP client."""

    def __init__(
        self,
        base_url: str,
        *,
        query_path: str,
        headers: dict[str, str] | None,
        timeout: float,
        tenant_attribute: str,
    ) -> None:
        if urllib.parse.urlparse(base_url).scheme not in ("http", "https"):
            raise AdapterError(f"base_url must be an http(s) URL: {base_url!r}")
        self._url = base_url.rstrip("/") + query_path
        self._headers = dict(headers) if headers else {}
        self._timeout = timeout
        self._tenant_attribute = tenant_attribute

    def query(self, tenant_hex: str, marker: str) -> dict[str, Any]:
        payload = json.dumps({"tenant": tenant_hex, "marker": marker}).encode("utf-8")
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
            raise AdapterError(f"OTel trace query to {self._url} failed: {error}") from error
        if not isinstance(body, dict):
            raise AdapterError(
                f"OTel query response must be a JSON object, got {type(body).__name__}"
            )
        return body

    def tenant_values(self) -> set[str]:
        request = urllib.request.Request(self._url, method="GET", headers=self._headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise AdapterError(f"OTel tenant listing at {self._url} failed: {error}") from error
        values = body.get("tenants") if isinstance(body, dict) else None
        return {str(value) for value in values} if isinstance(values, list) else set()

    def purge(self, tenant_hex: str) -> None:
        url = f"{self._url}?{urllib.parse.urlencode({'tenant': tenant_hex})}"
        request = urllib.request.Request(url, method="DELETE", headers=self._headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout):
                return
        except urllib.error.HTTPError as error:
            # 404 is idempotent success only when the spans are in fact gone. A
            # router that never implemented DELETE answers 404 for the method+path
            # too, and reading that as a purge recorded the surface erasable and
            # the re-scan's residue as an erasure FAILURE instead of a caveat.
            if error.code == 404:
                remaining = self.query(tenant_hex, "")
                if "resourceSpans" not in remaining:
                    # The same guard `search_traces` applies to this exact call: a
                    # 200 carrying an error envelope is not "the spans are gone",
                    # and reading it as one recorded the surface erasable off a
                    # response that answered nothing.
                    detail = remaining.get("error") or remaining.get("errors") or sorted(remaining)
                    raise AdapterError(
                        f"OTel post-delete re-scan returned no resourceSpans, so the 404 "
                        f"cannot be read as a purge: {str(detail)[:200]}"
                    ) from error
                if any(
                    _as_list(scope.get("spans"))
                    for resource in _as_list(remaining.get("resourceSpans"))
                    for scope in _as_list(resource.get("scopeSpans"))
                ):
                    raise ErasureUnsupported(
                        f"OTel trace store at {self._url} answered 404 to DELETE while the "
                        "tenant's spans remain: it exposes no programmatic delete, so "
                        "erasure is attestable-with-caveat"
                    ) from error
                return
            # 405 (Method Not Allowed) / 501 (Not Implemented) mean the store
            # exposes no programmatic delete - the same "no per-tenant erasure
            # API" condition Helicone/Datadog report. Signal the caveat so
            # Class 11 itemizes the surface as attestable-with-caveat (data
            # presumed retained) instead of a false erasure success.
            if error.code in (405, 501):
                raise ErasureUnsupported(
                    f"OTel trace store at {self._url} exposes no programmatic "
                    f"delete (HTTP {error.code}); erasure is attestable-with-caveat"
                ) from error
            raise AdapterError(f"OTel trace purge failed: {error}") from error


def _as_list(value: Any) -> list[dict[str, Any]]:
    """Return ``value`` as a list of dicts, or an empty list for any other shape."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _attribute_value(attributes: Any, key: str) -> str:
    """Pull an OTLP-JSON attribute's string value by key, or ``""`` if absent."""
    if not isinstance(attributes, list):
        return ""
    for attribute in attributes:
        if isinstance(attribute, dict) and attribute.get("key") == key:
            value = attribute.get("value")
            if isinstance(value, dict):
                return str(value.get("stringValue", ""))
            return str(value) if value is not None else ""
    return ""


def _span_snippet(span: dict[str, Any]) -> str:
    """Concatenate a span's name + every attribute value into a searchable string."""
    parts: list[str] = [str(span.get("name", ""))]
    for attribute in _as_list(span.get("attributes")):
        value = attribute.get("value")
        if isinstance(value, dict):
            parts.extend(str(item) for item in value.values())
        elif value is not None:
            parts.append(str(value))
    return " ".join(part for part in parts if part)
