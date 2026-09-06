"""Live Phoenix adapter: an observability backend backed by an Arize Phoenix server.

Each tenant maps to its own Phoenix project, so a trace search is scoped to the
tenant's project. Phoenix's client reads spans directly over HTTP, so no
OpenTelemetry SDK is required.

Requires the ``phoenix`` optional dependency: ``pip install sectum-ai-adapters[phoenix]``.
"""

from typing import Any
from uuid import UUID

import httpx
from phoenix.client import Client

from sectum_ai.adapters.base import Capability, ObservabilityAdapter, TraceHit
from sectum_ai.adapters.observability._listing import _refuse_capped
from sectum_ai.spec import ErasureUnsupported, residual_present

_SPAN_LIMIT = 1000
"""How many spans to scan per project when searching for a marker."""


class PhoenixObservability(ObservabilityAdapter):
    """An observability backend backed by an Arize Phoenix server."""

    def __init__(self, base_url: str, *, name: str = "phoenix", prefix: str = "sectum-ai") -> None:
        super().__init__(name, frozenset({Capability.TRACE_SEARCH}))
        self._client = Client(base_url=base_url)
        self._prefix = prefix

    def _project_name(self, tenant: UUID) -> str:
        return f"{self._prefix}-{tenant.hex}"

    def _project_names(self) -> set[str]:
        return {str(project["name"]) for project in self._client.projects.list()}

    def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
        project = self._project_name(tenant)
        if project not in self._project_names():
            return []
        hits: list[TraceHit] = []
        seen = 0
        for span in self._client.spans.get_spans(project_identifier=project, limit=_SPAN_LIMIT):
            seen += 1
            snippet = self._snippet(span)
            if residual_present(marker, snippet):
                hits.append(
                    TraceHit(
                        trace_id=str(span["context"]["trace_id"]),
                        project=project,
                        snippet=snippet,
                    )
                )
        # Only a MISS on a full page is refused: a marker found there is a
        # definite residual, and refusing it would lose a real erasure failure.
        if not hits:
            _refuse_capped("Phoenix", seen, _SPAN_LIMIT)
        return hits

    def fetch_trace(self, tenant: UUID, trace_id: str) -> TraceHit | None:
        """Fetch one of the tenant's traces by id, or ``None`` if it is gone.

        Scans the tenant's own project (like ``search_traces``); a span carrying
        the trace id makes the trace present, so another tenant's - or an erased -
        trace id returns ``None``. The by-id existence primitive for A3.
        """
        project = self._project_name(tenant)
        if project not in self._project_names():
            return None
        seen = 0
        for span in self._client.spans.get_spans(project_identifier=project, limit=_SPAN_LIMIT):
            seen += 1
            if str(span["context"]["trace_id"]) == trace_id:
                return TraceHit(trace_id=trace_id, project=project, snippet=self._snippet(span))
        _refuse_capped("Phoenix", seen, _SPAN_LIMIT)
        return None

    @staticmethod
    def _snippet(span: Any) -> str:
        attributes = span.get("attributes") or {}
        return " ".join([str(span.get("name", "")), *(str(value) for value in attributes.values())])

    def list_projects(self) -> list[str]:
        return sorted(self._project_names())

    def delete(self, tenant: UUID) -> None:
        """Delete the tenant's Phoenix project; a missing project is a no-op.

        A ``404`` is idempotent success only when the project is in fact gone. A
        deployment or router that never implemented the delete route answers 404
        to the method and path too, and swallowing that recorded the surface as
        erasable - so the re-scan's residue read as the customer's erasure flow
        failing rather than as a backend with no per-tenant purge. The OTel
        sibling already re-checks before treating a 404 as success; this is the
        same rule.
        """
        try:
            self._client.projects.delete(project_name=self._project_name(tenant))
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
            if self._project_name(tenant) in self._project_names():
                raise ErasureUnsupported(
                    f"Phoenix answered 404 to the delete while project "
                    f"{self._project_name(tenant)} is still listed: it exposes no "
                    "programmatic per-tenant delete, so erasure is attestable-with-caveat"
                ) from error
