"""Mock-backed contract tests for the Helicone + Datadog observability adapters.

Both are hosted services read over documented query APIs, so the adapter
logic (tenant scoping, marker scan, list, erasure-caveat) is verified here
against in-memory stand-ins. The live HTTP path is exercised only opt-in.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from sectum_ai.adapters.base import Capability, ObservabilityAdapter
from sectum_ai.adapters.observability.datadog import DatadogObservability
from sectum_ai.adapters.observability.helicone import HeliconeObservability
from sectum_ai.spec import ErasureUnsupported

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


# --- Helicone ---------------------------------------------------------------


class _FakeHelicone:
    def __init__(self) -> None:
        self._rows: dict[str, list[dict[str, Any]]] = {}

    def add(self, tenant_hex: str, request_body: str, owner: str | None = None) -> None:
        # ``owner`` defaults to the query bucket's tenant (the isolated case);
        # set it to a different tenant to model a leaky backend that returns a
        # foreign tenant's row under this query.
        rows = self._rows.setdefault(tenant_hex, [])
        rows.append(
            {
                "request_id": f"req-{len(rows):04d}",
                "request_body": request_body,
                "properties": {"tenant": owner or tenant_hex},
            }
        )

    def query_requests(self, tenant_value: str) -> list[dict[str, Any]]:
        return self._rows.get(tenant_value, [])

    def tenant_values(self) -> set[str]:
        return set(self._rows)


def test_helicone_conforms_and_reports_trace_search() -> None:
    adapter = HeliconeObservability(_FakeHelicone())
    assert isinstance(adapter, ObservabilityAdapter)
    assert adapter.supports(Capability.TRACE_SEARCH)
    assert adapter.name == "helicone"


def test_helicone_search_is_scoped_to_a_tenant() -> None:
    client = _FakeHelicone()
    client.add(_TENANT_A.hex, "prompt referencing SECTUM-CANARY-AAA")
    adapter = HeliconeObservability(client)
    hits = adapter.search_traces(_TENANT_A, "SECTUM-CANARY-AAA")
    assert hits
    assert hits[0].project == _TENANT_A.hex
    assert "SECTUM-CANARY-AAA" in hits[0].snippet
    assert adapter.search_traces(_TENANT_B, "SECTUM-CANARY-AAA") == []


def test_helicone_attributes_a_leaked_row_to_its_true_owner() -> None:
    # A leaky backend returns tenant B's request under tenant A's query; the
    # hit must name B (the owner), not A (the querier), so the evidence shows
    # observed-in != owner. The owner is read from the row's tenant property.
    client = _FakeHelicone()
    client.add(_TENANT_A.hex, "leaked SECTUM-CANARY-BBB", owner=_TENANT_B.hex)
    hits = HeliconeObservability(client).search_traces(_TENANT_A, "SECTUM-CANARY-BBB")
    assert hits
    assert hits[0].project == _TENANT_B.hex


def test_helicone_search_returns_nothing_when_marker_absent() -> None:
    client = _FakeHelicone()
    client.add(_TENANT_A.hex, "a benign request")
    assert HeliconeObservability(client).search_traces(_TENANT_A, "SECTUM-CANARY-AAA") == []


def test_helicone_fetch_trace_finds_a_request_by_id() -> None:
    client = _FakeHelicone()
    client.add(_TENANT_A.hex, "a recorded request")
    adapter = HeliconeObservability(client)
    hit = adapter.fetch_trace(_TENANT_A, "req-0000")
    assert hit is not None and hit.trace_id == "req-0000"
    assert adapter.fetch_trace(_TENANT_A, "req-9999") is None
    assert adapter.fetch_trace(_TENANT_B, "req-0000") is None


def test_helicone_lists_tenant_values() -> None:
    client = _FakeHelicone()
    client.add(_TENANT_A.hex, "a")
    client.add(_TENANT_B.hex, "b")
    assert HeliconeObservability(client).list_projects() == sorted([_TENANT_A.hex, _TENANT_B.hex])


def test_helicone_delete_raises_erasure_unsupported() -> None:
    adapter = HeliconeObservability(_FakeHelicone())
    with pytest.raises(ErasureUnsupported, match="helicone exposes no programmatic"):
        adapter.delete(_TENANT_A)


# --- Datadog ----------------------------------------------------------------


class _FakeDatadog:
    def __init__(self) -> None:
        self._events: dict[str, list[dict[str, Any]]] = {}

    def add(
        self,
        tenant_hex: str,
        resource_name: str,
        owner: str | None = None,
        meta: dict[str, str] | None = None,
    ) -> None:
        # ``owner`` defaults to the query bucket's tenant; ``meta`` models the
        # Datadog span-I/O bag where prompt/completion text (and a planted
        # marker) actually lands.
        events = self._events.setdefault(tenant_hex, [])
        attributes: dict[str, Any] = {
            "resource_name": resource_name,
            "custom": {"tenant": owner or tenant_hex},
        }
        if meta is not None:
            attributes["meta"] = meta
        events.append({"id": f"span-{len(events):04d}", "attributes": attributes})

    def search_spans(self, tenant_value: str) -> list[dict[str, Any]]:
        return self._events.get(tenant_value, [])

    def tenant_values(self) -> set[str]:
        return set(self._events)


def test_datadog_conforms_and_reports_trace_search() -> None:
    adapter = DatadogObservability(_FakeDatadog())
    assert isinstance(adapter, ObservabilityAdapter)
    assert adapter.supports(Capability.TRACE_SEARCH)
    assert adapter.name == "datadog"


def test_datadog_search_is_scoped_to_a_tenant() -> None:
    client = _FakeDatadog()
    client.add(_TENANT_A.hex, "llm.completion SECTUM-CANARY-AAA")
    adapter = DatadogObservability(client)
    hits = adapter.search_traces(_TENANT_A, "SECTUM-CANARY-AAA")
    assert hits
    assert hits[0].project == _TENANT_A.hex
    assert "SECTUM-CANARY-AAA" in hits[0].snippet
    assert adapter.search_traces(_TENANT_B, "SECTUM-CANARY-AAA") == []


def test_datadog_attributes_a_leaked_span_to_its_true_owner() -> None:
    # Same as the Helicone case: a leaked foreign span is attributed to its
    # owning tenant (read from the span's tenant tag), not the querier.
    client = _FakeDatadog()
    client.add(_TENANT_A.hex, "llm.completion SECTUM-CANARY-BBB", owner=_TENANT_B.hex)
    hits = DatadogObservability(client).search_traces(_TENANT_A, "SECTUM-CANARY-BBB")
    assert hits
    assert hits[0].project == _TENANT_B.hex


def test_datadog_scans_the_meta_bag_where_span_io_lives() -> None:
    # Datadog APM / LLM Observability stores prompt/completion text under
    # attributes.meta - a marker living only there must still be found, or a
    # residual canary would yield a false erasure PASS.
    client = _FakeDatadog()
    client.add(_TENANT_A.hex, "llm.completion", meta={"output": "see SECTUM-CANARY-AAA"})
    hits = DatadogObservability(client).search_traces(_TENANT_A, "SECTUM-CANARY-AAA")
    assert hits
    assert "SECTUM-CANARY-AAA" in hits[0].snippet


def test_datadog_fetch_trace_finds_a_span_by_id() -> None:
    client = _FakeDatadog()
    client.add(_TENANT_A.hex, "a recorded span")
    adapter = DatadogObservability(client)
    hit = adapter.fetch_trace(_TENANT_A, "span-0000")
    assert hit is not None and hit.trace_id == "span-0000"
    assert adapter.fetch_trace(_TENANT_A, "span-9999") is None
    assert adapter.fetch_trace(_TENANT_B, "span-0000") is None


def test_datadog_lists_tenant_values() -> None:
    client = _FakeDatadog()
    client.add(_TENANT_A.hex, "a")
    client.add(_TENANT_B.hex, "b")
    assert DatadogObservability(client).list_projects() == sorted([_TENANT_A.hex, _TENANT_B.hex])


def test_datadog_delete_raises_erasure_unsupported() -> None:
    adapter = DatadogObservability(_FakeDatadog())
    with pytest.raises(ErasureUnsupported, match="datadog governs deletion"):
        adapter.delete(_TENANT_A)


def test_erasure_unsupported_is_an_adapter_error() -> None:
    # It must subclass AdapterError so existing broad adapter-error handling
    # still catches it where a caller does not special-case the caveat.
    from sectum_ai.spec import AdapterError

    assert issubclass(ErasureUnsupported, AdapterError)


def test_helicone_http_client_wraps_a_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A URLError/timeout from the HTTP layer must surface as a typed AdapterError,
    # not a raw urllib error, so a hung/unreachable backend fails the run cleanly.
    import urllib.error

    from sectum_ai.adapters.observability.helicone import _HttpHeliconeClient
    from sectum_ai.spec import AdapterError

    def boom(request: Any, timeout: float) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("sectum_ai.adapters.observability.helicone.urllib.request.urlopen", boom)
    client = _HttpHeliconeClient("k", base_url="http://x", tenant_property="tenant")
    with pytest.raises(AdapterError, match="helicone request"):
        client.query_requests("tenant-a")


def test_datadog_http_client_wraps_a_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    from sectum_ai.adapters.observability.datadog import _HttpDatadogClient
    from sectum_ai.spec import AdapterError

    def boom(request: Any, timeout: float) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("sectum_ai.adapters.observability.datadog.urllib.request.urlopen", boom)
    client = _HttpDatadogClient("k", "app", base_url="http://x", tenant_tag="tenant")
    with pytest.raises(AdapterError, match="datadog request"):
        client._post("@tenant:tenant-a")
