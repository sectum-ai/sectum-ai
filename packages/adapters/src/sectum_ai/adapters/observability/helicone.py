"""Live Helicone adapter: trace search over the Helicone request-query API.

Helicone logs every LLM request/response and tags it with caller-supplied
custom properties. Sectum scopes by a custom property (default ``tenant``,
sent at request time as the ``Helicone-Property-Tenant`` header), so a trace
search reads back only the tenant's requests and scans their bodies for the
marker.

Read path (the documented Helicone request-query API):
``POST {base_url}/v1/request/query`` with ``Authorization: Bearer <api_key>``
and a body filtering on the tenant property; the response is
``{"data": [{request rows}]}`` where each row carries ``request_body`` /
``response_body`` and its custom ``properties``.

Erasure: Helicone exposes no documented programmatic per-tenant bulk-delete,
so ``delete`` raises :class:`~sectum_ai.spec.ErasureUnsupported`. The Class 11
probe records the surface as *attestable-with-caveat* (spec §7, hiding place
#8) rather than a false erasure success — the data is presumed retained until
purged via Helicone's retention settings.

The live HTTP path uses the standard library, so the adapter and its
mock-backed unit tests need no optional extra; the ``requests``-free contract
is the injectable ``_HeliconeClient`` below.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol, Self
from uuid import UUID

from sectum_ai.adapters.base import Capability, ObservabilityAdapter, TraceHit
from sectum_ai.adapters.observability._listing import _data_list, _refuse_capped
from sectum_ai.spec import AdapterError, ErasureUnsupported

_REQUEST_LIMIT = 1000
"""How many of a tenant's most recent requests to scan when searching for a marker."""

_HTTP_TIMEOUT_S = 30.0
"""Socket timeout for a Helicone HTTP call - without it a hung server blocks the run."""


class _HeliconeClient(Protocol):
    """The minimal Helicone surface ``HeliconeObservability`` consumes."""

    def query_requests(self, tenant_value: str) -> list[dict[str, Any]]:
        """Return the tenant's logged request rows (most recent first)."""

    def tenant_values(self) -> set[str]:
        """Return every distinct value seen for the tenant custom property."""


class HeliconeObservability(ObservabilityAdapter):
    """A Helicone observability backend scoped by a per-tenant custom property.

    Construct it with an open ``_HeliconeClient`` so the adapter can be tested
    against an in-memory stand-in without a live key. Use :meth:`connect` to
    build the live HTTP-backed client from an API key.
    """

    def __init__(
        self,
        client: _HeliconeClient,
        *,
        name: str = "helicone",
        tenant_property: str = "tenant",
    ) -> None:
        super().__init__(name, frozenset({Capability.TRACE_SEARCH}))
        self._client = client
        self._tenant_property = tenant_property

    @classmethod
    def connect(
        cls,
        api_key: str,
        *,
        base_url: str = "https://api.helicone.ai",
        tenant_property: str = "tenant",
        name: str = "helicone",
    ) -> Self:
        """Build the live Helicone HTTP client and return the adapter."""
        client = _HttpHeliconeClient(
            api_key,
            base_url=base_url,
            tenant_property=tenant_property,
        )
        return cls(client, name=name, tenant_property=tenant_property)

    def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
        hits: list[TraceHit] = []
        rows = self._client.query_requests(tenant.hex)
        # As in `fetch_trace`: a marker past the page cap is not "absent".
        _refuse_capped("Helicone", len(rows), _REQUEST_LIMIT)
        for row in rows:
            snippet = _row_snippet(row)
            if marker in snippet:
                hits.append(
                    TraceHit(
                        trace_id=str(row.get("request_id") or row.get("id") or ""),
                        # Attribute the hit to the row's *own* tenant property, not
                        # the querying tenant: on a leaky backend that surfaces a
                        # foreign request, the hit must name its true owner so the
                        # evidence shows observed-in (querier) != owner. Falls back
                        # to the querier when the row carries no tenant property.
                        project=self._row_owner(row, tenant.hex),
                        snippet=snippet,
                    )
                )
        return hits

    def fetch_trace(self, tenant: UUID, trace_id: str) -> TraceHit | None:
        """Fetch one of the tenant's requests by id, or ``None`` if it is gone.

        Lists the tenant's own requests (like ``search_traces``) and matches the
        request id, so another tenant's - or an erased - id returns ``None``: the
        by-id existence primitive for the A3 subject-erasure check.
        """
        rows = self._client.query_requests(tenant.hex)
        for row in rows:
            if str(row.get("request_id") or row.get("id") or "") == trace_id:
                return TraceHit(
                    trace_id=trace_id,
                    project=self._row_owner(row, tenant.hex),
                    snippet=_row_snippet(row),
                )
        _refuse_capped("Helicone", len(rows), _REQUEST_LIMIT)
        return None

    def _row_owner(self, row: dict[str, Any], default: str) -> str:
        properties = row.get("properties") or row.get("request_properties") or {}
        if isinstance(properties, dict) and self._tenant_property in properties:
            return str(properties[self._tenant_property])
        return default

    def list_projects(self) -> list[str]:
        return sorted(self._client.tenant_values())

    def delete(self, tenant: UUID) -> None:
        raise ErasureUnsupported(
            "helicone exposes no programmatic per-tenant erasure API; purge the "
            "tenant's logged requests via Helicone's retention settings or console"
        )


class _HttpHeliconeClient:
    """Helicone request-query client backed by the standard-library HTTP client."""

    def __init__(self, api_key: str, *, base_url: str, tenant_property: str) -> None:
        if not api_key:
            raise AdapterError("helicone api_key must not be empty")
        self._url = base_url.rstrip("/") + "/v1/request/query"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._tenant_property = tenant_property

    def _post(self, body: dict[str, Any]) -> list[dict[str, Any]]:
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
            raise AdapterError(f"helicone request to {self._url} failed: {error}") from error
        data = _data_list(payload, "helicone")
        return [row for row in data if isinstance(row, dict)]

    def query_requests(self, tenant_value: str) -> list[dict[str, Any]]:
        body = {
            "filter": {
                "properties": {
                    self._tenant_property: {"equals": tenant_value},
                }
            },
            "limit": _REQUEST_LIMIT,
        }
        return self._post(body)

    def tenant_values(self) -> set[str]:
        rows = self._post({"filter": "all", "limit": _REQUEST_LIMIT})
        values: set[str] = set()
        for row in rows:
            properties = row.get("properties") or row.get("request_properties") or {}
            if isinstance(properties, dict) and self._tenant_property in properties:
                values.add(str(properties[self._tenant_property]))
        return values


def _row_snippet(row: dict[str, Any]) -> str:
    """Concatenate a request row's bodies + property values into a searchable string."""
    parts: list[str] = []
    for key in ("request_body", "response_body", "request_path", "model"):
        value = row.get(key)
        if value:
            parts.append(str(value))
    properties = row.get("properties") or row.get("request_properties") or {}
    if isinstance(properties, dict):
        parts.extend(str(value) for value in properties.values())
    return " ".join(parts)
