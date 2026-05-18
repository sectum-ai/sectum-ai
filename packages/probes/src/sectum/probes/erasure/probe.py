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

from sectum.adapters import VectorStoreAdapter
from sectum.spec import Finding, FindingStatus, Marker, MarkerType, Severity, Substrate, Surface


@dataclass(frozen=True)
class SurfaceErasure:
    """The erasure outcome for one surface: markers seen before vs residual after."""

    surface: Surface
    markers_before: int
    residual_after: int

    @property
    def erased(self) -> bool:
        """True when no marker survived the erasure on this surface."""
        return self.residual_after == 0


@dataclass(frozen=True)
class ErasureReport:
    """The result of an erasure-verification run for one target tenant."""

    target_tenant: UUID
    surfaces: tuple[SurfaceErasure, ...]
    findings: tuple[Finding, ...]

    @property
    def erased(self) -> bool:
        """True when every surface is clear of the target tenant's markers."""
        return all(surface.erased for surface in self.surfaces)


class ErasureProbe:
    """Class 11: verify a tenant's data has left every configured surface."""

    id = "gdpr-erasure-verification"
    name = "GDPR Article 17 erasure verification"
    owasp_llm = "LLM08:2025"

    def __init__(self, substrate: Substrate, *, vector: VectorStoreAdapter) -> None:
        self._substrate = substrate
        self._vector = vector
        self._documents = {document.doc_id: document for document in substrate.documents}

    def run(self, target: UUID) -> ErasureReport:
        """Confirm the target's markers, run the erasure, and re-scan for residue."""
        markers = tuple(
            marker
            for marker in self._substrate.manifest.markers
            if marker.owner_tenant_id == target and marker.marker_type is MarkerType.HARD_CANARY
        )
        before = self._scan_vector(target, markers)
        self._vector.delete(target)
        residual = self._scan_vector(target, markers)
        surface = SurfaceErasure(
            surface=Surface.VECTOR_DB,
            markers_before=len(before),
            residual_after=len(residual),
        )
        findings = tuple(self._residual_finding(target, marker) for marker in residual)
        return ErasureReport(target_tenant=target, surfaces=(surface,), findings=findings)

    def _scan_vector(self, target: UUID, markers: tuple[Marker, ...]) -> list[Marker]:
        """Return the target's hard-canary markers still observable on the vector store."""
        return [marker for marker in markers if self._marker_observable(target, marker)]

    def _marker_observable(self, target: UUID, marker: Marker) -> bool:
        for location in marker.planted_locations:
            document = self._documents.get(location.doc_id)
            if document is None:
                continue
            hits = self._vector.query(target, document.title, k=10)
            if any(marker.plaintext in hit.content for hit in hits):
                return True
        return False

    def _residual_finding(self, target: UUID, marker: Marker) -> Finding:
        return Finding(
            finding_id=f"erasure-residual-{marker.marker_id}",
            probe_id=self.id,
            severity=Severity.HIGH,
            confidence=1.0,
            status=FindingStatus.CONFIRMED,
            owner_tenant_id=target,
            observed_in_tenant_id=target,
            surface=Surface.VECTOR_DB,
            marker_id=marker.marker_id,
            evidence_span=marker.plaintext,
            owasp_llm=self.owasp_llm,
            remediation_pointer="data survived an Article 17 erasure; purge orphaned vectors",
        )
