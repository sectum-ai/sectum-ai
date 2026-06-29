"""A3 Phase 0 - data-subject erasure verification by record id.

Class 11's :class:`~sectum_ai.probes.erasure.probe.ErasureProbe` verifies erasure
with planted synthetic canaries on a seeded substrate. This verifies a **real**
data subject's erasure: given the record ids that belong to the subject on each
surface, it confirms each id is gone **by id** after the customer's own deletion
has already run. It is therefore a post-deletion *check* (no plant/erase step) -
the structural verification model of the DSR connector (see
``internal/specs/a3-dsr-connector.md``).

Only surfaces with a by-id existence primitive in the adapter SDK are verifiable
today: the vector store (:meth:`VectorStoreAdapter.fetch`) and the semantic cache
(:meth:`CacheAdapter.get`). Every other erasure surface is reported
``NOT_COVERED`` - the same anti-over-claim contract as ``ErasureProbe`` (the
attestation never implies coverage it did not verify). A surface whose adapter is
not configured, or for which the subject manifest supplies no ids, is likewise
``NOT_COVERED`` - never a vacuous ``ERASED``. Additional surfaces become
verifiable as their adapters gain a by-id accessor.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from sectum_ai.adapters import CacheAdapter, VectorStoreAdapter
from sectum_ai.probes.erasure import ErasureReport, SurfaceErasure
from sectum_ai.spec import Finding, FindingStatus, Severity, Surface

# The erasure surfaces with a by-id existence primitive in the adapter SDK today.
# A subject's ids on any other surface cannot be checked by id yet, so they read
# NOT_COVERED until that adapter family gains a by-id accessor.
SUBJECT_VERIFIABLE_SURFACES: tuple[Surface, ...] = (Surface.VECTOR_DB, Surface.SEMANTIC_CACHE)

_REMEDIATION = {
    Surface.VECTOR_DB: (
        "a record named in the subject's erasure request is still fetchable by id; "
        "purge the orphaned vector(s)"
    ),
    Surface.SEMANTIC_CACHE: (
        "a record named in the subject's erasure request is still present in the cache; "
        "evict the entry"
    ),
}


@dataclass(frozen=True)
class SubjectManifest:
    """The record ids that belong to one data subject, per surface.

    ``subject_ref`` is an opaque, customer-chosen reference for the DSR; the
    manifest carries record **ids only**, never subject content, so it holds no
    PII. ``records`` maps an erasure surface to the subject's record ids on it
    (a vector ``doc_id``, a cache key, ...).
    """

    subject_ref: str
    records: Mapping[Surface, tuple[str, ...]]


class SubjectErasureProbe:
    """Verify a real data subject's records are gone by id (A3 Phase 0)."""

    id = "gdpr-subject-erasure-verification"
    name = "GDPR Article 17 data-subject erasure verification (by record id)"
    owasp_llm = "LLM08:2025"
    owasp_secondary: tuple[str, ...] = ("LLM02:2025",)
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)

    def __init__(
        self,
        *,
        vector: VectorStoreAdapter | None = None,
        cache: CacheAdapter | None = None,
    ) -> None:
        self._vector = vector
        self._cache = cache

    def verify(self, target: UUID, manifest: SubjectManifest) -> ErasureReport:
        """Check each supplied record id is gone by id; return an erasure report.

        For a surface with both a configured adapter and supplied ids, the report
        records ``markers_before`` = ids supplied and ``residual_after`` = ids
        still present, so the verdict is ``ERASED`` only when every supplied id is
        gone, ``RESIDUAL`` if any remain, and ``NOT_COVERED`` when the surface was
        not (or could not be) checked.
        """
        surfaces: list[SurfaceErasure] = []
        findings: list[Finding] = []

        vector = self._vector
        if vector is not None:
            ids = manifest.records.get(Surface.VECTOR_DB, ())
            if ids:
                present = [rid for rid in ids if vector.fetch(target, rid) is not None]
                surfaces.append(self._surface(Surface.VECTOR_DB, ids, present))
                findings.extend(
                    self._residual_finding(target, Surface.VECTOR_DB, manifest.subject_ref, rid)
                    for rid in present
                )

        cache = self._cache
        if cache is not None:
            ids = manifest.records.get(Surface.SEMANTIC_CACHE, ())
            if ids:
                present = [rid for rid in ids if cache.get(target, rid) is not None]
                surfaces.append(self._surface(Surface.SEMANTIC_CACHE, ids, present))
                findings.extend(
                    self._residual_finding(
                        target, Surface.SEMANTIC_CACHE, manifest.subject_ref, rid
                    )
                    for rid in present
                )

        return ErasureReport(
            target_tenant=target, surfaces=tuple(surfaces), findings=tuple(findings)
        )

    @staticmethod
    def _surface(surface: Surface, ids: Sequence[str], present: Sequence[str]) -> SurfaceErasure:
        return SurfaceErasure(surface=surface, markers_before=len(ids), residual_after=len(present))

    def _residual_finding(
        self, target: UUID, surface: Surface, subject_ref: str, record_id: str
    ) -> Finding:
        # The evidence span is the record id, not its content: the manifest never
        # carries subject PII, so neither does the attestation.
        return Finding(
            finding_id=f"subject-erasure-residual-{surface.value}-{record_id}",
            probe_id=self.id,
            severity=Severity.HIGH,
            confidence=1.0,
            status=FindingStatus.CONFIRMED,
            owner_tenant_id=target,
            observed_in_tenant_id=target,
            surface=surface,
            marker_id=record_id,
            evidence_span=f"subject {subject_ref}: record {record_id}",
            owasp_llm=self.owasp_llm,
            atlas=self.atlas_techniques,
            nist=self.nist_rmf,
            owasp_secondary=self.owasp_secondary,
            remediation_pointer=_REMEDIATION[surface],
        )
