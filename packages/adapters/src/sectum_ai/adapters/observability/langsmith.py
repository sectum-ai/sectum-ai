"""Live LangSmith adapter: an observability backend backed by a LangSmith server.

Each tenant maps to its own LangSmith tracing project, so a trace search is
scoped to the tenant's project and erasure deletes that project. The public
LangSmith SDK supports per-project delete but no bulk delete-by-metadata, which
makes the per-project model the clean fit (like the Phoenix adapter).

The ``langsmith`` package is imported only on the live ``connect`` path, so the
adapter and its mock-backed test need no dependency. The live path requires the
``langsmith`` optional dependency: ``pip install sectum-ai-adapters[langsmith]``.
"""

from typing import Any, Self
from uuid import UUID

from sectum_ai.adapters.base import Capability, ObservabilityAdapter, TraceHit

_RUN_LIMIT = 1000
"""How many of a project's most recent runs to scan when searching for a marker."""


class LangSmithObservability(ObservabilityAdapter):
    """An observability backend backed by LangSmith, one project per tenant."""

    def __init__(self, client: Any, *, name: str = "langsmith", prefix: str = "sectum-ai") -> None:
        super().__init__(name, frozenset({Capability.TRACE_SEARCH}))
        self._client = client
        self._prefix = prefix

    @classmethod
    def connect(
        cls,
        api_key: str,
        api_url: str | None = None,
        *,
        name: str = "langsmith",
        prefix: str = "sectum-ai",
    ) -> Self:
        """Open a LangSmith client and return the adapter.

        The ``langsmith`` package is imported here, on the live path only, so the
        adapter module and its mock-backed test do not require it.
        """
        from langsmith import Client

        client = Client(api_url=api_url, api_key=api_key)
        return cls(client, name=name, prefix=prefix)

    def _project_name(self, tenant: UUID) -> str:
        return f"{self._prefix}-{tenant.hex}"

    def _project_names(self) -> set[str]:
        return {str(project.name) for project in self._client.list_projects()}

    @staticmethod
    def _snippet(run: Any) -> str:
        # Read each field defensively with getattr: a run may omit any of them,
        # and inputs/outputs are dicts whose string form carries the marker.
        parts = (
            getattr(run, "name", None),
            getattr(run, "inputs", None),
            getattr(run, "outputs", None),
        )
        return " ".join(str(part) for part in parts if part)

    def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
        project = self._project_name(tenant)
        if project not in self._project_names():
            return []
        hits: list[TraceHit] = []
        for run in self._client.list_runs(project_name=project, limit=_RUN_LIMIT):
            snippet = self._snippet(run)
            if marker in snippet:
                hits.append(TraceHit(trace_id=str(run.id), project=project, snippet=snippet))
        return hits

    def fetch_trace(self, tenant: UUID, trace_id: str) -> TraceHit | None:
        """Fetch one of the tenant's runs by id, or ``None`` if it is gone.

        Scoped to the tenant's own project (like ``search_traces``), so another
        tenant's run id - or an erased one - returns ``None``: the by-id existence
        primitive for the A3 subject-erasure check.
        """
        project = self._project_name(tenant)
        if project not in self._project_names():
            return None
        for run in self._client.list_runs(project_name=project, limit=_RUN_LIMIT):
            if str(run.id) == trace_id:
                return TraceHit(trace_id=trace_id, project=project, snippet=self._snippet(run))
        return None

    def list_projects(self) -> list[str]:
        return sorted(self._project_names())

    def delete(self, tenant: UUID) -> None:
        # Idempotent: only delete a project that exists, so erasure of a tenant
        # that never accumulated traces is a no-op (no exception to swallow).
        project = self._project_name(tenant)
        if project in self._project_names():
            self._client.delete_project(project_name=project)
