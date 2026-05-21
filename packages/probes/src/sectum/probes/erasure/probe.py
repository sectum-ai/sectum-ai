"""Class 11 - GDPR Article 17 erasure verification (the engineering spec, section 7).

The wedge SKU. It confirms a target tenant's hard canaries are present on each
configured surface, runs the erasure flow, then re-scans every surface; any
marker still observable post-erasure is an itemized erasure failure.

Unlike the catalog's attack probes, Class 11 is a pre/erase/post workflow rather
than a plan/detect probe, so it exposes its own ``run`` entry point and returns
an ``ErasureReport`` instead of a flat finding list.
"""

from dataclasses import dataclass
from uuid import UUID

from sectum.adapters import MemoryAdapter, ObservabilityAdapter, VectorStoreAdapter
from sectum.spec import Finding, FindingStatus, Marker, MarkerType, Severity, Substrate, Surface


@dataclass(frozen=True)
class SurfaceErasure:
    """The erasure outcome for one surface: markers seen before vs residual after."""

    surface: Surface
    markers_before: int
    residual_after: int

    @property
    def erased(self) -> bool:
        """True when a baseline was established and no marker survived erasure.

        A surface with no markers before erasure yields no baseline, so its
        erasure cannot be attested - ``erased`` is ``False`` rather than
        vacuously ``True``.
        """
        return self.markers_before > 0 and self.residual_after == 0

    @property
    def verdict(self) -> str:
        """A human-readable verdict: ERASED, RESIDUAL DATA, or NO BASELINE."""
        if self.markers_before == 0:
            return "NO BASELINE"
        if self.residual_after == 0:
            return "ERASED"
        return "RESIDUAL DATA"


@dataclass(frozen=True)
class ErasureReport:
    """The result of an erasure-verification run for one target tenant."""

    target_tenant: UUID
    surfaces: tuple[SurfaceErasure, ...]
    findings: tuple[Finding, ...]

    @property
    def erased(self) -> bool:
        """True when every surface established a baseline and is now clear."""
        return bool(self.surfaces) and all(surface.erased for surface in self.surfaces)


class ErasureProbe:
    """Class 11: verify a tenant's data has left every configured surface."""

    id = "gdpr-erasure-verification"
    name = "GDPR Article 17 erasure verification"
    owasp_llm = "LLM08:2025"

    def __init__(
        self,
        substrate: Substrate,
        *,
        vector: VectorStoreAdapter,
        observability: ObservabilityAdapter | None = None,
        memory: MemoryAdapter | None = None,
    ) -> None:
        self._substrate = substrate
        self._vector = vector
        self._observability = observability
        self._memory = memory
        self._documents = {document.doc_id: document for document in substrate.documents}

    def run(self, target: UUID) -> ErasureReport:
        """Confirm the target's markers, run the erasure, and re-scan every surface."""
        markers = tuple(
            marker
            for marker in self._substrate.manifest.markers
            if marker.owner_tenant_id == target and marker.marker_type is MarkerType.HARD_CANARY
        )
        surfaces: list[SurfaceErasure] = []
        findings: list[Finding] = []

        vector_before = self._scan_vector(target, markers)
        self._vector.delete(target)
        vector_residual = self._scan_vector(target, markers)
        surfaces.append(
            SurfaceErasure(
                surface=Surface.VECTOR_DB,
                markers_before=len(vector_before),
                residual_after=len(vector_residual),
            )
        )
        findings.extend(
            self._residual_finding(target, marker, Surface.VECTOR_DB) for marker in vector_residual
        )

        if self._observability is not None:
            obs_before = self._scan_observability(target, markers)
            self._observability.delete(target)
            obs_residual = self._scan_observability(target, markers)
            surfaces.append(
                SurfaceErasure(
                    surface=Surface.TRACING,
                    markers_before=len(obs_before),
                    residual_after=len(obs_residual),
                )
            )
            findings.extend(
                self._residual_finding(target, marker, Surface.TRACING) for marker in obs_residual
            )

        if self._memory is not None:
            mem_before = self._scan_memory(target, markers)
            self._memory.delete(target)
            mem_residual = self._scan_memory(target, markers)
            surfaces.append(
                SurfaceErasure(
                    surface=Surface.AGENT_MEMORY,
                    markers_before=len(mem_before),
                    residual_after=len(mem_residual),
                )
            )
            findings.extend(
                self._residual_finding(target, marker, Surface.AGENT_MEMORY)
                for marker in mem_residual
            )

        return ErasureReport(
            target_tenant=target, surfaces=tuple(surfaces), findings=tuple(findings)
        )

    def _scan_vector(self, target: UUID, markers: tuple[Marker, ...]) -> list[Marker]:
        """Return the target's hard-canary markers still observable on the vector store."""
        return [marker for marker in markers if self._marker_observable(target, marker)]

    def _scan_observability(self, target: UUID, markers: tuple[Marker, ...]) -> list[Marker]:
        """Return the target's hard-canary markers still observable in tracing."""
        if self._observability is None:
            return []
        observability = self._observability
        return [
            marker for marker in markers if observability.search_traces(target, marker.plaintext)
        ]

    def _scan_memory(self, target: UUID, markers: tuple[Marker, ...]) -> list[Marker]:
        """Return the target's hard-canary markers still recallable from memory."""
        if self._memory is None:
            return []
        memory = self._memory
        return [
            marker
            for marker in markers
            if any(marker.plaintext in entry for entry in memory.recall(target, marker.plaintext))
        ]

    def _marker_observable(self, target: UUID, marker: Marker) -> bool:
        for location in marker.planted_locations:
            document = self._documents.get(location.doc_id)
            if document is None:
                continue
            hits = self._vector.query(target, document.title, k=10)
            if any(marker.plaintext in hit.content for hit in hits):
                return True
        return False

    def _residual_finding(self, target: UUID, marker: Marker, surface: Surface) -> Finding:
        remediation = {
            Surface.VECTOR_DB: "data survived an Article 17 erasure; purge orphaned vectors",
            Surface.TRACING: (
                "data survived an Article 17 erasure; purge the tenant's traces from the "
                "observability backend"
            ),
            Surface.AGENT_MEMORY: (
                "data survived an Article 17 erasure; purge the tenant's entries from the "
                "agent/long-term memory store"
            ),
        }.get(surface, "data survived an Article 17 erasure; purge it from this surface")
        return Finding(
            finding_id=f"erasure-residual-{surface.value}-{marker.marker_id}",
            probe_id=self.id,
            severity=Severity.HIGH,
            confidence=1.0,
            status=FindingStatus.CONFIRMED,
            owner_tenant_id=target,
            observed_in_tenant_id=target,
            surface=surface,
            marker_id=marker.marker_id,
            evidence_span=marker.plaintext,
            owasp_llm=self.owasp_llm,
            remediation_pointer=remediation,
        )
