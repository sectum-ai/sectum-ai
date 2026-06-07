"""Live Langfuse adapter: an observability backend backed by a Langfuse server.

Langfuse's public SDK binds one project per credential pair and cannot enumerate
or provision projects, so - unlike the per-project Phoenix adapter - each tenant
is scoped within a single project by the trace ``user_id`` (set to the tenant's
hex id when the trace is recorded). A search lists that tenant's traces and
substring-matches the marker in their text; erasure lists the tenant's trace ids
and bulk-deletes them.

Targets the Langfuse v3 Python SDK (``langfuse>=3,<4``); the package is imported
only on the live ``connect`` path, so the adapter and its mock-backed test need
no dependency. The live path requires the ``langfuse`` optional dependency:
``pip install sectum-ai-adapters[langfuse]``.
"""

import time
from typing import Any, Self
from uuid import UUID

from sectum_ai.adapters.base import Capability, ObservabilityAdapter, TraceHit

_TRACE_LIMIT = 1000
"""How many of a tenant's most recent traces to scan or purge per call."""

_TRACE_PAGE = 100
"""Max page size the Langfuse public trace-list API accepts (it rejects >100)."""

_DELETE_SETTLE_TRIES = 60
"""Bounded polls to confirm Langfuse's asynchronous trace deletion completed."""

_DELETE_SETTLE_INTERVAL = 2.0
"""Seconds between deletion-settle polls."""


class LangfuseObservability(ObservabilityAdapter):
    """An observability backend backed by Langfuse (one project, tenant-scoped
    by the trace ``user_id``)."""

    def __init__(self, client: Any, *, name: str = "langfuse") -> None:
        super().__init__(name, frozenset({Capability.TRACE_SEARCH}))
        self._client = client
        self._project: str | None = None

    @classmethod
    def connect(
        cls, public_key: str, secret_key: str, host: str, *, name: str = "langfuse"
    ) -> Self:
        """Open a Langfuse client and return the adapter.

        The ``langfuse`` package is imported here, on the live path only, so the
        adapter module and its mock-backed test do not require it.
        """
        from langfuse import Langfuse

        client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        return cls(client, name=name)

    def _project_name(self) -> str:
        if self._project is None:
            projects = self._client.api.projects.get().data
            self._project = str(projects[0].name) if projects else "langfuse"
        return self._project

    @staticmethod
    def _snippet(trace: Any) -> str:
        # Read each field defensively with getattr: Langfuse v3 declares these
        # as optional trace fields (default None), and a non-standard trace
        # object may omit them entirely - either way this never raises.
        parts = (
            getattr(trace, "name", None),
            getattr(trace, "input", None),
            getattr(trace, "output", None),
            getattr(trace, "metadata", None),
        )
        return " ".join(str(part) for part in parts if part)

    def _tenant_traces(self, tenant: UUID) -> list[Any]:
        # Page through the tenant's traces: Langfuse caps the list page size at
        # _TRACE_PAGE (rejecting larger limits with HTTP 400), so request
        # fixed-size pages until a short/empty page or the _TRACE_LIMIT scan
        # budget is reached.
        traces: list[Any] = []
        page = 1
        while len(traces) < _TRACE_LIMIT:
            batch = self._client.api.trace.list(
                user_id=tenant.hex, limit=_TRACE_PAGE, page=page
            ).data
            if not batch:
                break
            traces.extend(batch)
            if len(batch) < _TRACE_PAGE:
                break
            page += 1
        return traces[:_TRACE_LIMIT]

    def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
        project = self._project_name()
        hits: list[TraceHit] = []
        for trace in self._tenant_traces(tenant):
            snippet = self._snippet(trace)
            if marker in snippet:
                hits.append(TraceHit(trace_id=str(trace.id), project=project, snippet=snippet))
        return hits

    def list_projects(self) -> list[str]:
        return sorted(str(project.name) for project in self._client.api.projects.get().data)

    def delete(self, tenant: UUID) -> None:
        trace_ids = [str(trace.id) for trace in self._tenant_traces(tenant)]
        if not trace_ids:
            return
        self._client.api.trace.delete_multiple(trace_ids=trace_ids)
        # Langfuse processes trace deletion asynchronously, so a caller that
        # re-scans immediately would see the not-yet-purged traces and wrongly
        # report residual data. Wait, bounded, until the tenant's traces are no
        # longer listed before returning.
        for _ in range(_DELETE_SETTLE_TRIES):
            if not self._tenant_traces(tenant):
                return
            time.sleep(_DELETE_SETTLE_INTERVAL)
