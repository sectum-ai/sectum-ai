"""Live LangSmith adapter: an observability backend backed by a LangSmith server.

Each tenant maps to its own LangSmith tracing project, so a trace search is
scoped to the tenant's project and erasure deletes that project. The public
LangSmith SDK supports per-project delete but no bulk delete-by-metadata, which
makes the per-project model the clean fit (like the Phoenix adapter).

The ``langsmith`` package is imported only on the live ``connect`` path, so the
adapter and its mock-backed test need no dependency. The live path requires the
``langsmith`` optional dependency: ``pip install sectum-ai-adapters[langsmith]``.
"""

import time
from typing import Any, Self
from uuid import UUID

from sectum_ai.adapters.base import Capability, ObservabilityAdapter, TraceHit
from sectum_ai.adapters.observability._listing import _refuse_capped
from sectum_ai.spec import AdapterError, residual_present

_RUN_LIMIT = 1000

# Matching the Langfuse sibling: a bounded wait for the delete to take effect,
# and a refusal rather than a silent return when it does not.
_DELETE_SETTLE_TRIES = 60
_DELETE_SETTLE_INTERVAL = 2.0
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
        #
        # `extra`, `tags` and `error` as well, which this was the ONE trace backend
        # not to read. `@traceable(metadata=...)` lands in `extra`, and every
        # sibling reads its own equivalent bag - Langfuse takes `metadata`, Datadog
        # takes `custom` AND `meta` with a comment saying missing it "would be a
        # false erasure PASS", and helicone/phoenix/otel each read their attribute
        # map. A marker carried in metadata was invisible here, so the surface
        # signed TRACING: ERASED over content the read path never looked at, and
        # reported no cross-tenant leak for the same reason. The test double
        # modelled only id/name/inputs/outputs, so no test could have caught it.
        parts = (
            getattr(run, "name", None),
            getattr(run, "inputs", None),
            getattr(run, "outputs", None),
            getattr(run, "extra", None),
            getattr(run, "tags", None),
            getattr(run, "error", None),
        )
        return " ".join(str(part) for part in parts if part)

    def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
        project = self._project_name(tenant)
        if project not in self._project_names():
            return []
        hits: list[TraceHit] = []
        seen = 0
        for run in self._client.list_runs(project_name=project, limit=_RUN_LIMIT):
            seen += 1
            snippet = self._snippet(run)
            if residual_present(marker, snippet):
                hits.append(TraceHit(trace_id=str(run.id), project=project, snippet=snippet))
        # Only a MISS on a full page is refused: a marker found there is a
        # definite residual, and refusing it would lose a real erasure failure.
        if not hits:
            _refuse_capped("LangSmith", seen, _RUN_LIMIT)
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
        seen = 0
        for run in self._client.list_runs(project_name=project, limit=_RUN_LIMIT):
            seen += 1
            if str(run.id) == trace_id:
                return TraceHit(trace_id=trace_id, project=project, snippet=self._snippet(run))
        _refuse_capped("LangSmith", seen, _RUN_LIMIT)
        return None

    def list_projects(self) -> list[str]:
        return sorted(self._project_names())

    def delete(self, tenant: UUID) -> None:
        """Delete the tenant's project, and confirm it is gone before returning.

        Idempotent: only delete a project that exists, so erasure of a tenant that
        never accumulated traces is a no-op (no exception to swallow).

        The CONFIRMATION is what this was missing. Every other trace backend
        verifies its own purge - Langfuse polls until the traces are no longer
        listed and raises on the timeout, with a comment recording that "returning
        silently on the timeout let the re-scan confirm a residual"; Phoenix and
        OTel re-check on a 404. This returned the moment the API accepted the
        call, and `search_traces` / `fetch_trace` then report absence from the
        project row alone (`project not in self._project_names()`), without
        reading a run - so a delete the backend accepted and did not apply read
        back as `TRACING: ERASED`.

        Bounded, like the sibling, because a project row may take a moment to
        disappear. What this CANNOT establish is whether LangSmith retains runs
        server-side after the project row is gone: the listing is project-scoped,
        so once the project is deleted there is nothing left to query. That limit
        is a property of the API, and it is recorded in `docs/coverage.md` rather
        than papered over here.
        """
        project = self._project_name(tenant)
        if project not in self._project_names():
            return
        self._client.delete_project(project_name=project)
        for _ in range(_DELETE_SETTLE_TRIES):
            if project not in self._project_names():
                return
            time.sleep(_DELETE_SETTLE_INTERVAL)
        raise AdapterError(
            f"LangSmith still lists project {project!r} "
            f"{_DELETE_SETTLE_TRIES * _DELETE_SETTLE_INTERVAL:.0f} s after the delete was "
            "accepted; the purge cannot be confirmed"
        )
