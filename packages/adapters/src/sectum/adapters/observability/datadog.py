"""Live Datadog APM adapter: trace search over the Datadog spans-search API.

Datadog ingests LLM spans (APM / LLM Observability); Sectum scopes by a span
tag (default ``tenant``, set to the ``tenant.hex`` on each span), so a trace
search reads back only the tenant's spans and scans their attributes for the
marker.

Read path (the documented Datadog spans-search API):
``POST {base_url}/api/v2/spans/events/search`` with ``DD-API-KEY`` and
``DD-APPLICATION-KEY`` headers and a body whose ``filter.query`` selects the
tenant tag; the response is ``{"data": [{span events}]}`` whose
``attributes`` carry the span name + custom attributes.

Erasure: Datadog governs deletion through retention policies, not a
programmatic per-tenant span-delete API, so ``delete`` raises
:class:`~sectum.spec.ErasureUnsupported`. The Class 11 probe records the
surface as *attestable-with-caveat* (spec §7, hiding place #8) rather than a
false erasure success — the spans are presumed retained until they age out
of the configured retention window.

The live HTTP path uses the standard library, so the adapter and its
mock-backed unit tests need no optional extra; the injectable
``_DatadogClient`` below is the test seam.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Protocol, Self
from uuid import UUID

from sectum.adapters.base import Capability, ObservabilityAdapter, TraceHit
from sectum.spec import AdapterError, ErasureUnsupported

_SPAN_LIMIT = 1000
"""How many of a tenant's most recent spans to scan when searching for a marker."""


class _DatadogClient(Protocol):
    """The minimal Datadog surface ``DatadogObservability`` consumes."""

    def search_spans(self, tenant_value: str) -> list[dict[str, Any]]:
        """Return the tenant's span events (most recent first)."""

    def tenant_values(self) -> set[str]:
        """Return every distinct value seen for the tenant span tag."""


class DatadogObservability(ObservabilityAdapter):
    """A Datadog APM observability backend scoped by a per-tenant span tag.

    Construct it with an open ``_DatadogClient`` so the adapter can be tested
    against an in-memory stand-in without live keys. Use :meth:`connect` to
    build the live HTTP-backed client from an API key + application key.
    """

    def __init__(
        self,
        client: _DatadogClient,
        *,
        name: str = "datadog",
        tenant_tag: str = "tenant",
    ) -> None:
        super().__init__(name, frozenset({Capability.TRACE_SEARCH}))
        self._client = client
        self._tenant_tag = tenant_tag

    @classmethod
    def connect(
        cls,
        api_key: str,
        application_key: str,
        *,
        base_url: str = "https://api.datadoghq.com",
        tenant_tag: str = "tenant",
        name: str = "datadog",
    ) -> Self:
        """Build the live Datadog HTTP client and return the adapter."""
        client = _HttpDatadogClient(
            api_key,
            application_key,
            base_url=base_url,
            tenant_tag=tenant_tag,
        )
        return cls(client, name=name, tenant_tag=tenant_tag)

    def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
        hits: list[TraceHit] = []
        for event in self._client.search_spans(tenant.hex):
            snippet = _event_snippet(event)
            if marker in snippet:
                hits.append(
                    TraceHit(
                        trace_id=str(event.get("id") or ""),
                        project=tenant.hex,
                        snippet=snippet,
                    )
                )
        return hits

    def list_projects(self) -> list[str]:
        return sorted(self._client.tenant_values())

    def delete(self, tenant: UUID) -> None:
        raise ErasureUnsupported(
            "datadog governs deletion through retention policies, not a "
            "programmatic per-tenant span-delete API; purge the tenant's spans "
            "via the retention window or a Datadog support data-deletion request"
        )


class _HttpDatadogClient:
    """Datadog spans-search client backed by the standard-library HTTP client."""

    def __init__(
        self, api_key: str, application_key: str, *, base_url: str, tenant_tag: str
    ) -> None:
        if not api_key or not application_key:
            raise AdapterError("datadog api_key and application_key must not be empty")
        self._url = base_url.rstrip("/") + "/api/v2/spans/events/search"
        self._headers = {
            "DD-API-KEY": api_key,
            "DD-APPLICATION-KEY": application_key,
            "Content-Type": "application/json",
        }
        self._tenant_tag = tenant_tag

    def _post(self, query: str) -> list[dict[str, Any]]:
        body = {
            "data": {
                "attributes": {
                    "filter": {"query": query, "from": "now-15m", "to": "now"},
                    "page": {"limit": _SPAN_LIMIT},
                },
                "type": "search_request",
            }
        }
        request = urllib.request.Request(
            self._url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers=self._headers,
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read())
        data = payload.get("data") if isinstance(payload, dict) else None
        return (
            [event for event in data if isinstance(event, dict)] if isinstance(data, list) else []
        )

    def search_spans(self, tenant_value: str) -> list[dict[str, Any]]:
        return self._post(f"@{self._tenant_tag}:{tenant_value}")

    def tenant_values(self) -> set[str]:
        values: set[str] = set()
        for event in self._post(f"@{self._tenant_tag}:*"):
            attributes = event.get("attributes") or {}
            tags = attributes.get("custom") or attributes.get("tags") or {}
            if isinstance(tags, dict) and self._tenant_tag in tags:
                values.add(str(tags[self._tenant_tag]))
        return values


def _event_snippet(event: dict[str, Any]) -> str:
    """Concatenate a span event's name + attribute values into a searchable string."""
    attributes = event.get("attributes")
    if not isinstance(attributes, dict):
        return ""
    parts: list[str] = []
    for key in ("resource_name", "service", "name"):
        value = attributes.get(key)
        if value:
            parts.append(str(value))
    custom = attributes.get("custom")
    if isinstance(custom, dict):
        parts.extend(str(value) for value in custom.values())
    return " ".join(parts)
