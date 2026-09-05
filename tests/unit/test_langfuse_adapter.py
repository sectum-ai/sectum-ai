"""Mock-backed contract tests for the live Langfuse observability adapter.

Langfuse is a hosted service whose v3 SDK ingests over OpenTelemetry, so the
adapter's read and delete logic is verified here against an in-memory stand-in
for the Langfuse client (the engineering spec, section 13). The live path is
exercised by ``tests/integration/test_langfuse.py``.
"""

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from sectum_ai.adapters.base import Capability, ObservabilityAdapter
from sectum_ai.adapters.observability.langfuse import LangfuseObservability

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


class _FakeTraceApi:
    """In-memory stand-in for ``langfuse.api.trace`` (list / delete_multiple)."""

    def __init__(self) -> None:
        self._traces: dict[str, SimpleNamespace] = {}
        self._sequence = 0

    def record(self, *, user_id: str, text: str) -> str:
        self._sequence += 1
        trace_id = f"trace-{self._sequence:04d}"
        self._traces[trace_id] = SimpleNamespace(
            id=trace_id, user_id=user_id, name="sectum-probe", input=text, output="", metadata={}
        )
        return trace_id

    def add(self, trace: SimpleNamespace) -> None:
        self._traces[str(trace.id)] = trace

    def list(
        self, *, user_id: str | None = None, limit: int = 50, page: int = 1, **_: Any
    ) -> SimpleNamespace:
        data = [t for t in self._traces.values() if user_id is None or t.user_id == user_id]
        return SimpleNamespace(data=data[(page - 1) * limit : page * limit])

    def delete_multiple(self, *, trace_ids: Sequence[str]) -> None:
        for trace_id in trace_ids:
            self._traces.pop(trace_id, None)


class _FakeProjectApi:
    def __init__(self, name: str = "sectum-langfuse") -> None:
        self._name = name

    def get(self) -> SimpleNamespace:
        return SimpleNamespace(data=[SimpleNamespace(id="proj-1", name=self._name)])


class _FakeLangfuse:
    def __init__(self) -> None:
        self.trace_api = _FakeTraceApi()
        self.api = SimpleNamespace(trace=self.trace_api, projects=_FakeProjectApi())


def test_langfuse_conforms_and_reports_trace_search() -> None:
    adapter = LangfuseObservability(_FakeLangfuse())
    assert isinstance(adapter, ObservabilityAdapter)
    assert adapter.supports(Capability.TRACE_SEARCH)


def test_langfuse_search_is_scoped_to_a_tenant_by_user_id() -> None:
    client = _FakeLangfuse()
    a_id = client.trace_api.record(user_id=_TENANT_A.hex, text="output mentions SECTUM-CANARY-AAA")
    client.trace_api.record(user_id=_TENANT_B.hex, text="tenant B also has SECTUM-CANARY-AAA")
    adapter = LangfuseObservability(client)
    a_hits = adapter.search_traces(_TENANT_A, "SECTUM-CANARY-AAA")
    assert [hit.trace_id for hit in a_hits] == [a_id]
    assert "SECTUM-CANARY-AAA" in a_hits[0].snippet
    # the same marker exists under tenant B, but only within B's user_id scope
    assert len(adapter.search_traces(_TENANT_B, "SECTUM-CANARY-AAA")) == 1


def test_langfuse_search_returns_nothing_when_the_marker_is_absent() -> None:
    client = _FakeLangfuse()
    client.trace_api.record(user_id=_TENANT_A.hex, text="a benign trace")
    assert LangfuseObservability(client).search_traces(_TENANT_A, "SECTUM-CANARY-AAA") == []


def test_langfuse_lists_the_bound_project() -> None:
    assert LangfuseObservability(_FakeLangfuse()).list_projects() == ["sectum-langfuse"]


def test_langfuse_delete_purges_a_tenants_traces() -> None:
    client = _FakeLangfuse()
    client.trace_api.record(user_id=_TENANT_A.hex, text="SECTUM-CANARY-DEL")
    client.trace_api.record(user_id=_TENANT_B.hex, text="SECTUM-CANARY-KEEP")
    adapter = LangfuseObservability(client)
    adapter.delete(_TENANT_A)
    assert adapter.search_traces(_TENANT_A, "SECTUM-CANARY-DEL") == []
    # another tenant's traces are untouched
    assert adapter.search_traces(_TENANT_B, "SECTUM-CANARY-KEEP")


def test_langfuse_delete_is_a_no_op_without_traces() -> None:
    adapter = LangfuseObservability(_FakeLangfuse())
    adapter.delete(_TENANT_A)  # must not raise when the tenant has no traces
    assert adapter.search_traces(_TENANT_A, "anything") == []


def test_langfuse_search_tolerates_a_trace_missing_text_fields() -> None:
    client = _FakeLangfuse()
    # a sparse trace with no name/input/output/metadata attributes must not crash
    client.trace_api.add(SimpleNamespace(id="sparse-1", user_id=_TENANT_A.hex))
    assert LangfuseObservability(client).search_traces(_TENANT_A, "SECTUM-CANARY-AAA") == []


def test_langfuse_delete_purges_a_tenant_spanning_several_pages() -> None:
    client = _FakeLangfuse()
    for index in range(250):
        client.trace_api.record(user_id=_TENANT_A.hex, text=f"trace {index}")
    LangfuseObservability(client).delete(_TENANT_A)
    assert client.trace_api.list(user_id=_TENANT_A.hex).data == []


def test_langfuse_refuses_a_listing_that_exhausted_its_budget() -> None:
    # The listing stopped at 1000 traces and the callers went on as if that were
    # the tenant: `delete` purged the first thousand and returned silently, the
    # re-scan (now the older page) showed no marker, and `fetch_trace` read a
    # trace beyond the budget as erased.
    from sectum_ai.spec import AdapterError

    client = _FakeLangfuse()
    for index in range(1001):
        client.trace_api.record(user_id=_TENANT_A.hex, text=f"trace {index}")
    adapter = LangfuseObservability(client)
    with pytest.raises(AdapterError, match="more than 1000"):
        adapter.fetch_trace(_TENANT_A, "trace-1001")
    with pytest.raises(AdapterError, match="more than 1000"):
        adapter.delete(_TENANT_A)


def test_langfuse_delete_that_never_settles_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A settle timeout used to return silently, so the re-scan confirmed a
    # residual the backend was still processing (a wrong-direction HIGH).
    from sectum_ai.spec import AdapterError

    class _StuckTraceApi(_FakeTraceApi):
        def delete_multiple(self, *, trace_ids: Sequence[str]) -> None:
            return None  # accepted, never applied

    client = _FakeLangfuse()
    client.trace_api = _StuckTraceApi()
    client.api = SimpleNamespace(trace=client.trace_api, projects=_FakeProjectApi())
    client.trace_api.record(user_id=_TENANT_A.hex, text="stuck")
    monkeypatch.setattr("sectum_ai.adapters.observability.langfuse.time.sleep", lambda _s: None)
    with pytest.raises(AdapterError, match="cannot be confirmed"):
        LangfuseObservability(client).delete(_TENANT_A)
