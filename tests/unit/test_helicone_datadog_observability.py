"""Mock-backed contract tests for the Helicone + Datadog observability adapters.

Both are hosted services read over documented query APIs, so the adapter
logic (tenant scoping, marker scan, list, erasure-caveat) is verified here
against in-memory stand-ins. The live HTTP path is exercised only opt-in.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from sectum.adapters.base import Capability, ObservabilityAdapter
from sectum.adapters.observability.datadog import DatadogObservability
from sectum.adapters.observability.helicone import HeliconeObservability
from sectum.spec import ErasureUnsupported

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


# --- Helicone ---------------------------------------------------------------


class _FakeHelicone:
    def __init__(self) -> None:
        self._rows: dict[str, list[dict[str, Any]]] = {}

    def add(self, tenant_hex: str, request_body: str) -> None:
        rows = self._rows.setdefault(tenant_hex, [])
        rows.append(
            {
                "request_id": f"req-{len(rows):04d}",
                "request_body": request_body,
                "properties": {"tenant": tenant_hex},
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


def test_helicone_search_returns_nothing_when_marker_absent() -> None:
    client = _FakeHelicone()
    client.add(_TENANT_A.hex, "a benign request")
    assert HeliconeObservability(client).search_traces(_TENANT_A, "SECTUM-CANARY-AAA") == []


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

    def add(self, tenant_hex: str, resource_name: str) -> None:
        events = self._events.setdefault(tenant_hex, [])
        events.append(
            {
                "id": f"span-{len(events):04d}",
                "attributes": {
                    "resource_name": resource_name,
                    "custom": {"tenant": tenant_hex},
                },
            }
        )

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
    from sectum.spec import AdapterError

    assert issubclass(ErasureUnsupported, AdapterError)
