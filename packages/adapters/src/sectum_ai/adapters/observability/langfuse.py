"""Live Langfuse adapter: an observability backend backed by a Langfuse server.

Langfuse's public SDK binds one project per credential pair and cannot enumerate
or provision projects, so - unlike the per-project Phoenix adapter - each tenant
is scoped within a single project by the trace ``user_id`` (set to the tenant's
hex id when the trace is recorded). A search lists that tenant's traces and
substring-matches the marker in their text; erasure lists the tenant's trace ids
and bulk-deletes them.

Targets the Langfuse v4 Python SDK (``langfuse>=4,<5``); it uses the generated
``client.api.{trace,projects}`` surface, which is unchanged from v3. The package
is imported only on the live ``connect`` path, so the adapter and its mock-backed
test need no dependency. The live path requires the ``langfuse`` optional
dependency: ``pip install sectum-ai-adapters[langfuse]``.
"""

import time
from typing import Any, Self
from uuid import UUID

from sectum_ai.adapters.base import Capability, ObservabilityAdapter, TraceHit
from sectum_ai.spec import AdapterError

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

    def _tenant_traces(self, tenant: UUID) -> tuple[list[Any], bool]:
        """The tenant's traces, and whether the scan budget ran out first.

        Returns the truncation flag rather than raising on it, because what a
        truncated listing means depends on the question: a marker FOUND on a
        partial listing is a definite residual, and refusing it would lose a real
        erasure failure. Only the callers that read *absence* off the listing
        refuse - the same rule the Datadog, Helicone, LangSmith and Phoenix
        backends follow.
        """
        traces: list[Any] = []
        page = 1
        while True:
            batch = self._client.api.trace.list(
                user_id=tenant.hex, limit=_TRACE_PAGE, page=page
            ).data
            if not batch:
                break
            traces.extend(batch)
            if len(batch) < _TRACE_PAGE:
                break
            if len(traces) >= _TRACE_LIMIT:
                return traces, True
            page += 1
        return traces, False

    def _refuse_truncated(self, tenant: UUID) -> None:
        raise AdapterError(
            f"tenant {tenant.hex} has more than {_TRACE_LIMIT} Langfuse traces; "
            "the listing budget was exhausted before the tenant's traces were, "
            "so no verdict about them can be complete"
        )

    def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
        project = self._project_name()
        traces, truncated = self._tenant_traces(tenant)
        hits: list[TraceHit] = []
        for trace in traces:
            snippet = self._snippet(trace)
            if marker in snippet:
                hits.append(TraceHit(trace_id=str(trace.id), project=project, snippet=snippet))
        # A marker found on a partial listing is a definite residual; only a MISS
        # on one is unknowable.
        if not hits and truncated:
            self._refuse_truncated(tenant)
        return hits

    def fetch_trace(self, tenant: UUID, trace_id: str) -> TraceHit | None:
        """Fetch one of the tenant's traces by id, or ``None`` if it is gone.

        Reuses the tenant-scoped ``_tenant_traces`` listing (``user_id ==
        tenant.hex``) rather than a bare ``trace.get``, so another tenant's trace
        id - or an erased one - returns ``None``. The by-id existence primitive
        for the A3 subject-erasure check.
        """
        traces, truncated = self._tenant_traces(tenant)
        for trace in traces:
            if str(trace.id) == trace_id:
                return TraceHit(
                    trace_id=trace_id, project=self._project_name(), snippet=self._snippet(trace)
                )
        # `None` is read as "the trace is gone", which a truncated listing cannot
        # establish.
        if truncated:
            self._refuse_truncated(tenant)
        return None

    def list_projects(self) -> list[str]:
        return sorted(str(project.name) for project in self._client.api.projects.get().data)

    def delete(self, tenant: UUID) -> None:
        """Erase the tenant's traces (the tracing surface) within the bound project.

        Scope: this deletes the tenant's traces — their nested observations and
        scores cascade with them — within the one bound project. It does NOT
        erase project-level objects (prompts, datasets, dataset items): those are
        not user-scoped, so full GDPR Article 17 erasure of a whole Langfuse
        tenant (= a project) requires deleting the project itself. The erasure
        report therefore attests the tracing surface, not project-level objects.

        Langfuse deletes asynchronously, so this waits (bounded) for the tenant's
        traces to disappear before returning so a post-erasure re-scan is
        accurate.
        """
        traces, truncated = self._tenant_traces(tenant)
        # A purge over a partial listing leaves the rest and reports the tenant
        # clean, so `delete` refuses regardless of what it found.
        if truncated:
            self._refuse_truncated(tenant)
        trace_ids = [str(trace.id) for trace in traces]
        if not trace_ids:
            return
        self._client.api.trace.delete_multiple(trace_ids=trace_ids)
        # Langfuse processes trace deletion asynchronously, so a caller that
        # re-scans immediately would see the not-yet-purged traces and wrongly
        # report residual data. Wait, bounded, until the tenant's traces are no
        # longer listed before returning - and say so if they never are: returning
        # silently on the timeout let the re-scan confirm a residual the backend
        # was still processing.
        for _ in range(_DELETE_SETTLE_TRIES):
            remaining, _still_truncated = self._tenant_traces(tenant)
            if not remaining:
                return
            time.sleep(_DELETE_SETTLE_INTERVAL)
        raise AdapterError(
            f"Langfuse still lists traces for tenant {tenant.hex} "
            f"{_DELETE_SETTLE_TRIES * _DELETE_SETTLE_INTERVAL:.0f} s after the delete was "
            "accepted; the purge cannot be confirmed"
        )
