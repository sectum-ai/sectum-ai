"""Mock-backed contract tests for the live LangSmith observability adapter.

LangSmith is a hosted service, so the adapter's read/delete logic is verified
here against an in-memory stand-in for the LangSmith client (the engineering
spec, section 13). The live path is exercised by
``tests/integration/test_langsmith.py``.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sectum_ai.adapters.base import Capability, ObservabilityAdapter
from sectum_ai.adapters.observability.langsmith import LangSmithObservability

_PREFIX = "sectum"
_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


def _project(tenant: UUID) -> str:
    return f"{_PREFIX}-{tenant.hex}"


class _FakeLangSmith:
    """In-memory stand-in for a LangSmith ``Client`` (per-project runs)."""

    def __init__(self) -> None:
        self._projects: dict[str, list[SimpleNamespace]] = {}

    def create_run(
        self, name: str, inputs: dict[str, Any], run_type: str, *, project_name: str, **kwargs: Any
    ) -> None:
        runs = self._projects.setdefault(project_name, [])
        runs.append(
            SimpleNamespace(
                id=f"run-{len(runs):04d}",
                name=name,
                inputs=inputs,
                outputs=kwargs.get("outputs", {}),
            )
        )

    def add(self, project_name: str, run: SimpleNamespace) -> None:
        self._projects.setdefault(project_name, []).append(run)

    def list_runs(
        self, *, project_name: str | None = None, limit: int | None = None, **_: Any
    ) -> Iterator[SimpleNamespace]:
        runs = self._projects.get(project_name or "", [])
        return iter(runs[:limit] if limit is not None else runs)

    def list_projects(self, **_: Any) -> Iterator[SimpleNamespace]:
        return iter(SimpleNamespace(name=name, id=name) for name in self._projects)

    def delete_project(self, *, project_name: str) -> None:
        self._projects.pop(project_name, None)


def _seed(client: _FakeLangSmith, tenant: UUID, text: str) -> None:
    client.create_run(
        name="sectum-probe", inputs={"text": text}, run_type="chain", project_name=_project(tenant)
    )


def test_langsmith_conforms_and_reports_trace_search() -> None:
    adapter = LangSmithObservability(_FakeLangSmith())
    assert isinstance(adapter, ObservabilityAdapter)
    assert adapter.supports(Capability.TRACE_SEARCH)


def test_langsmith_search_is_scoped_to_a_tenants_project() -> None:
    client = _FakeLangSmith()
    _seed(client, _TENANT_A, "the output mentions SECTUM-CANARY-AAA")
    adapter = LangSmithObservability(client)
    hits = adapter.search_traces(_TENANT_A, "SECTUM-CANARY-AAA")
    assert hits
    assert all(hit.project == _project(_TENANT_A) for hit in hits)
    assert "SECTUM-CANARY-AAA" in hits[0].snippet
    # tenant B has no project, so the marker never surfaces in B's scope
    assert adapter.search_traces(_TENANT_B, "SECTUM-CANARY-AAA") == []


def test_langsmith_search_returns_nothing_when_the_marker_is_absent() -> None:
    client = _FakeLangSmith()
    _seed(client, _TENANT_A, "a benign run")
    assert LangSmithObservability(client).search_traces(_TENANT_A, "SECTUM-CANARY-AAA") == []


def test_langsmith_lists_projects() -> None:
    client = _FakeLangSmith()
    _seed(client, _TENANT_A, "a recorded run")
    _seed(client, _TENANT_B, "another run")
    assert LangSmithObservability(client).list_projects() == sorted(
        [_project(_TENANT_A), _project(_TENANT_B)]
    )


def test_langsmith_delete_clears_a_tenants_project() -> None:
    client = _FakeLangSmith()
    _seed(client, _TENANT_A, "SECTUM-CANARY-DEL")
    _seed(client, _TENANT_B, "SECTUM-CANARY-KEEP")
    adapter = LangSmithObservability(client)
    adapter.delete(_TENANT_A)
    assert adapter.search_traces(_TENANT_A, "SECTUM-CANARY-DEL") == []
    # another tenant's project is untouched
    assert adapter.search_traces(_TENANT_B, "SECTUM-CANARY-KEEP")


def test_langsmith_delete_is_idempotent_when_no_project_exists() -> None:
    adapter = LangSmithObservability(_FakeLangSmith())
    adapter.delete(_TENANT_A)  # must not raise when the tenant has no project
    assert adapter.search_traces(_TENANT_A, "anything") == []


def test_langsmith_search_tolerates_a_run_missing_fields() -> None:
    client = _FakeLangSmith()
    # a sparse run with no name/inputs/outputs attributes must not crash
    client.add(_project(_TENANT_A), SimpleNamespace(id="sparse-1"))
    assert LangSmithObservability(client).search_traces(_TENANT_A, "SECTUM-CANARY-AAA") == []
