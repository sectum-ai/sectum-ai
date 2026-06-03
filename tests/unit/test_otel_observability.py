"""Mock-backed contract tests for the live generic OpenTelemetry adapter.

The OTel backend is read over an OTLP-JSON HTTP query endpoint, so the
adapter's scoping / scan / delete logic is verified here against an in-memory
stand-in for the trace store. The live HTTP path is exercised only opt-in.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NoReturn
from uuid import UUID

from sectum_ai.adapters.base import Capability, ObservabilityAdapter
from sectum_ai.adapters.observability.otel import OtelObservability

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


def _span(
    name: str, attributes: dict[str, str] | None = None, trace_id: str = "t-1"
) -> dict[str, Any]:
    attrs = [
        {"key": key, "value": {"stringValue": value}} for key, value in (attributes or {}).items()
    ]
    return {"traceId": trace_id, "name": name, "attributes": attrs}


def _resource_spans(tenant_hex: str, spans: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "tenant.id", "value": {"stringValue": tenant_hex}}]
                },
                "scopeSpans": [{"spans": spans}],
            }
        ]
    }


class _FakeOtelStore:
    """In-memory OTLP-JSON trace store: spans keyed by tenant hex."""

    def __init__(self) -> None:
        self._spans: dict[str, list[dict[str, Any]]] = {}
        self.purged: list[str] = []
        self.leak_all: bool = False

    def add(self, tenant_hex: str, span: dict[str, Any]) -> None:
        self._spans.setdefault(tenant_hex, []).append(span)

    def query(self, tenant_hex: str, marker: str) -> dict[str, Any]:
        # A tenant-scoped store returns only the caller's spans. With leak_all
        # on it returns *every* tenant's spans (the leaky backend), each still
        # tagged with its true owning tenant's resource attribute.
        owners = self._spans if self.leak_all else {tenant_hex: self._spans.get(tenant_hex, [])}
        resource_spans = [
            _resource_spans(owner, spans)["resourceSpans"][0]
            for owner, spans in owners.items()
            if spans
        ]
        return {"resourceSpans": resource_spans}

    def tenant_values(self) -> set[str]:
        return set(self._spans)

    def purge(self, tenant_hex: str) -> None:
        self.purged.append(tenant_hex)
        self._spans.pop(tenant_hex, None)


def test_otel_conforms_and_reports_trace_search() -> None:
    adapter = OtelObservability(_FakeOtelStore())
    assert isinstance(adapter, ObservabilityAdapter)
    assert adapter.supports(Capability.TRACE_SEARCH)
    assert adapter.name == "otel"


def test_otel_search_is_scoped_to_a_tenant() -> None:
    store = _FakeOtelStore()
    store.add(_TENANT_A.hex, _span("llm.call", {"prompt": "see SECTUM-CANARY-AAA"}))
    adapter = OtelObservability(store)
    hits = adapter.search_traces(_TENANT_A, "SECTUM-CANARY-AAA")
    assert hits
    assert hits[0].project == _TENANT_A.hex
    assert "SECTUM-CANARY-AAA" in hits[0].snippet
    # tenant B has no spans, so the marker never surfaces in B's scope
    assert adapter.search_traces(_TENANT_B, "SECTUM-CANARY-AAA") == []


def test_otel_search_returns_nothing_when_marker_absent() -> None:
    store = _FakeOtelStore()
    store.add(_TENANT_A.hex, _span("llm.call", {"prompt": "a benign span"}))
    assert OtelObservability(store).search_traces(_TENANT_A, "SECTUM-CANARY-AAA") == []


def test_otel_leaky_backend_surfaces_a_foreign_tenants_span() -> None:
    # A backend that ignores the tenant filter returns tenant A's span to a
    # tenant B query; the hit carries A's resource tenant value, so the
    # detector can flag observed_in (B) != owner (A).
    store = _FakeOtelStore()
    store.leak_all = True
    store.add(_TENANT_A.hex, _span("llm.call", {"prompt": "leak SECTUM-CANARY-AAA"}))
    hits = OtelObservability(store).search_traces(_TENANT_B, "SECTUM-CANARY-AAA")
    assert hits
    assert hits[0].project == _TENANT_A.hex  # the span's true owner


def test_otel_lists_tenant_projects() -> None:
    store = _FakeOtelStore()
    store.add(_TENANT_A.hex, _span("a"))
    store.add(_TENANT_B.hex, _span("b"))
    assert OtelObservability(store).list_projects() == sorted([_TENANT_A.hex, _TENANT_B.hex])


def test_otel_delete_purges_a_tenant() -> None:
    store = _FakeOtelStore()
    store.add(_TENANT_A.hex, _span("llm.call", {"prompt": "SECTUM-CANARY-DEL"}))
    adapter = OtelObservability(store)
    adapter.delete(_TENANT_A)
    assert store.purged == [_TENANT_A.hex]
    assert adapter.search_traces(_TENANT_A, "SECTUM-CANARY-DEL") == []


def test_otel_search_tolerates_a_malformed_response() -> None:
    class _BadStore:
        def query(self, tenant_hex: str, marker: str) -> dict[str, Any]:
            return {"resourceSpans": "not-a-list"}

        def tenant_values(self) -> set[str]:
            return set()

        def purge(self, tenant_hex: str) -> None:
            pass

    assert OtelObservability(_BadStore()).search_traces(_TENANT_A, "x") == []


def test_otel_honours_a_custom_tenant_attribute() -> None:
    # Build a resource span whose tenant lives under a custom attribute key.
    custom = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.tenant", "value": {"stringValue": _TENANT_A.hex}}
                    ]
                },
                "scopeSpans": [{"spans": [_span("llm.call", {"p": "SECTUM-CANARY-AAA"})]}],
            }
        ]
    }

    class _CustomStore:
        def query(self, tenant_hex: str, marker: str) -> dict[str, Any]:
            return custom

        def tenant_values(self) -> set[str]:
            return {_TENANT_A.hex}

        def purge(self, tenant_hex: str) -> None:
            pass

    adapter = OtelObservability(_CustomStore(), tenant_attribute="service.tenant")
    hits = adapter.search_traces(_TENANT_A, "SECTUM-CANARY-AAA")
    assert hits and hits[0].project == _TENANT_A.hex


# --- the live HTTP trace store: URL guard + erasure (purge) branches ----------
# These exercise _HttpOtelTraceStore directly (the production path used when a
# real OTLP-JSON endpoint is configured) by monkeypatching urllib's urlopen, so
# the erasure-critical 404/405/501-swallow-vs-raise logic and the base_url guard
# are covered without a live server. The 85% coverage gate excludes
# adapters/observability, so this branch would otherwise ship untested.

import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

import pytest  # noqa: E402

from sectum_ai.adapters.observability.otel import _HttpOtelTraceStore  # noqa: E402
from sectum_ai.spec import AdapterError, ErasureUnsupported  # noqa: E402


def _http_store() -> _HttpOtelTraceStore:
    return _HttpOtelTraceStore(
        "https://otel.example.com",
        query_path="/v1/traces/query",
        headers=None,
        timeout=5.0,
        tenant_attribute="tenant.id",
    )


def _raise_http_error(code: int) -> Callable[..., NoReturn]:
    def _urlopen(*_args: object, **_kwargs: object) -> NoReturn:
        raise urllib.error.HTTPError(
            url="https://otel.example.com/v1/traces/query",
            code=code,
            msg=f"HTTP {code}",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )

    return _urlopen


def test_http_store_rejects_a_non_http_base_url() -> None:
    with pytest.raises(AdapterError, match="must be an http"):
        _HttpOtelTraceStore(
            "ftp://otel.example.com",
            query_path="/q",
            headers=None,
            timeout=5.0,
            tenant_attribute="tenant.id",
        )


def test_http_purge_swallows_404_as_idempotent_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 404 means the tenant's spans are already absent, so erasure is an
    # idempotent no-op success - purge must NOT raise.
    monkeypatch.setattr(urllib.request, "urlopen", _raise_http_error(404))
    _http_store().purge(_TENANT_A.hex)  # must not raise


@pytest.mark.parametrize("code", [405, 501])
def test_http_purge_raises_caveat_when_no_delete_api(
    code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 405 (Method Not Allowed) / 501 (Not Implemented) mean the store exposes no
    # programmatic delete - the same "no per-tenant erasure API" condition the
    # Helicone/Datadog adapters report. purge must raise ErasureUnsupported so
    # Class 11 records the surface as attestable-with-caveat, not a false
    # erasure success (which is what swallowing these codes would produce).
    monkeypatch.setattr(urllib.request, "urlopen", _raise_http_error(code))
    with pytest.raises(ErasureUnsupported, match="no programmatic"):
        _http_store().purge(_TENANT_A.hex)


@pytest.mark.parametrize("code", [403, 500, 502])
def test_http_purge_propagates_other_http_errors(
    code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real failure (auth, server error) must surface as AdapterError, never be
    # silently swallowed into a false-clean erasure verdict.
    monkeypatch.setattr(urllib.request, "urlopen", _raise_http_error(code))
    with pytest.raises(AdapterError, match="OTel trace purge failed"):
        _http_store().purge(_TENANT_A.hex)


def test_http_query_wraps_a_transport_error_in_adapter_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A failed trace query (here a 500, an HTTPError which is a URLError) must
    # surface as AdapterError, not a raw urllib error, so the CLI's typed-error
    # exit path is honored rather than an opaque crash mid-scan.
    monkeypatch.setattr(urllib.request, "urlopen", _raise_http_error(500))
    with pytest.raises(AdapterError, match="OTel trace query"):
        _http_store().query(_TENANT_A.hex, "SECTUM-CANARY-AAA")
