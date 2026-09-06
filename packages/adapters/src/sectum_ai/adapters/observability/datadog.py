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

Every search is bounded by a time window (``search_window``, default
``now-15d`` to match Datadog's default span retention). The bound is a
correctness concern, not a tuning knob: a span *outside* the window reads
back as absent, and the A3 erasure check treats an absent span as erased, so
a window narrower than the data's age turns still-present spans into a false
ERASED. Widen it to cover the retention actually configured on the account.

Erasure: Datadog governs deletion through retention policies, not a
programmatic per-tenant span-delete API, so ``delete`` raises
:class:`~sectum_ai.spec.ErasureUnsupported`. The Class 11 probe records the
surface as *attestable-with-caveat* (spec §7, hiding place #8) rather than a
false erasure success — the spans are presumed retained until they age out
of the configured retention window.

The live HTTP path uses the standard library, so the adapter and its
mock-backed unit tests need no optional extra; the injectable
``_DatadogClient`` below is the test seam.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol, Self
from uuid import UUID

from sectum_ai.adapters.base import Capability, ObservabilityAdapter, TraceHit
from sectum_ai.adapters.observability._listing import _data_list, _refuse_capped
from sectum_ai.spec import AdapterError, ErasureUnsupported, residual_present

_SPAN_LIMIT = 1000
"""How many of a tenant's most recent spans to scan when searching for a marker."""

_HTTP_TIMEOUT_S = 30.0
"""Socket timeout for a Datadog HTTP call - without it a hung server blocks the run."""

DEFAULT_SEARCH_WINDOW = "now-15d"
"""How far back a span search looks, as a Datadog relative-time expression.

Datadog's search API defaults this to ``now-15m``; that default is unsafe here.
A span older than the window returns no data, ``fetch_trace`` reports it gone,
and the erasure probe records the tracing surface as ERASED - a still-retained
subject attested as deleted. Datadog's own erasure is retention-driven (see
``delete``), so the horizon is inherently days, never minutes. The default
matches Datadog's default 15-day span retention; accounts retaining longer must
widen it, since absence outside the window is not evidence of erasure.
"""


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
        search_window: str = DEFAULT_SEARCH_WINDOW,
    ) -> Self:
        """Build the live Datadog HTTP client and return the adapter.

        ``search_window`` must cover the account's span retention: spans older
        than it read back as absent, which the erasure check cannot distinguish
        from erased. See :data:`DEFAULT_SEARCH_WINDOW`.
        """
        client = _HttpDatadogClient(
            api_key,
            application_key,
            base_url=base_url,
            tenant_tag=tenant_tag,
            search_window=search_window,
        )
        return cls(client, name=name, tenant_tag=tenant_tag)

    def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
        hits: list[TraceHit] = []
        events = self._client.search_spans(tenant.hex)
        for event in events:
            snippet = _event_snippet(event)
            if residual_present(marker, snippet):
                hits.append(
                    TraceHit(
                        trace_id=str(event.get("id") or ""),
                        # Attribute the hit to the span's *own* tenant tag, not the
                        # querying tenant: a leaky backend that surfaces a foreign
                        # span must name its true owner so observed-in != owner is
                        # visible. Falls back to the querier when the tag is absent.
                        project=self._event_owner(event, tenant.hex),
                        snippet=snippet,
                    )
                )
        # The Class 11 primitive reads the same single page as `fetch_trace`: a
        # retained canary past the cap came back as "no trace", and a soft-delete
        # backend whose post-erasure page no longer holds it attested ERASED. A
        # marker FOUND on a full page is a definite residual, so only a miss is
        # refused - refusing the hit would lose a real erasure failure.
        if not hits:
            _refuse_capped("Datadog", len(events), _SPAN_LIMIT)
        return hits

    def fetch_trace(self, tenant: UUID, trace_id: str) -> TraceHit | None:
        """Fetch one of the tenant's spans by id, or ``None`` if it is gone.

        Lists the tenant's own spans (like ``search_traces``) and matches the span
        id, so another tenant's - or an erased - id returns ``None``: the by-id
        existence primitive for the A3 subject-erasure check.

        ``None`` means "not found *within the configured search window*". A span
        older than that window is indistinguishable from an erased one, so the
        window must cover the account's retention or this reports a false ERASED.
        """
        events = self._client.search_spans(tenant.hex)
        for event in events:
            if str(event.get("id") or "") == trace_id:
                return TraceHit(
                    trace_id=trace_id,
                    project=self._event_owner(event, tenant.hex),
                    snippet=_event_snippet(event),
                )
        _refuse_capped("Datadog", len(events), _SPAN_LIMIT)
        return None

    def _event_owner(self, event: dict[str, Any], default: str) -> str:
        attributes = event.get("attributes") or {}
        if not isinstance(attributes, dict):
            return default
        tags = attributes.get("custom") or attributes.get("tags") or {}
        if isinstance(tags, dict) and self._tenant_tag in tags:
            return str(tags[self._tenant_tag])
        return default

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
        self,
        api_key: str,
        application_key: str,
        *,
        base_url: str,
        tenant_tag: str,
        search_window: str = DEFAULT_SEARCH_WINDOW,
    ) -> None:
        if not api_key or not application_key:
            raise AdapterError("datadog api_key and application_key must not be empty")
        if not search_window.strip():
            # An empty window would let Datadog fall back to its own now-15m
            # default, silently reintroducing the false-ERASED bound.
            raise AdapterError("datadog search_window must not be empty")
        self._search_window = search_window
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
                    "filter": {"query": query, "from": self._search_window, "to": "now"},
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
        try:
            with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_S) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError) as error:
            raise AdapterError(f"datadog request to {self._url} failed: {error}") from error
        data = _data_list(payload, "datadog")
        return [event for event in data if isinstance(event, dict)]

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
    """Concatenate a span event's name + attribute values into a searchable string.

    Scans both ``custom`` (Sectum's tenant tag + caller-set attributes) and
    ``meta`` - Datadog APM / LLM Observability stores span I/O (prompt and
    completion text) under ``meta``, which is exactly where a planted marker in
    a logged prompt would surface, so missing it would be a false erasure PASS.
    """
    attributes = event.get("attributes")
    if not isinstance(attributes, dict):
        return ""
    parts: list[str] = []
    for key in ("resource_name", "service", "name"):
        value = attributes.get(key)
        if value:
            parts.append(str(value))
    for bag_key in ("custom", "meta"):
        bag = attributes.get(bag_key)
        if isinstance(bag, dict):
            parts.extend(str(value) for value in bag.values())
    return " ".join(parts)
