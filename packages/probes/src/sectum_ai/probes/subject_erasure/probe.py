"""A3 Phase 0/2 - data-subject erasure verification (by id, and by content).

Class 11's :class:`~sectum_ai.probes.erasure.probe.ErasureProbe` verifies erasure
with planted synthetic canaries on a seeded substrate. This verifies a **real**
data subject's erasure after the customer's own deletion has already run - a
post-deletion *check*, not a plant/erase flow (the DSR connector's structural +
fingerprint verification model; see ``internal/specs/a3-dsr-connector.md``).

Two verification methods, both folded into one per-surface verdict:

- **By id (Phase 0):** given the subject's record ids per surface, confirm each is
  gone *by id*. Deterministic. The vector store (:meth:`VectorStoreAdapter.fetch`)
  and the semantic cache (:meth:`CacheAdapter.get`) expose a by-id primitive today;
  every other surface reads ``NOT_COVERED``.
- **By content fingerprint (Phase 2):** given the subject's known content, probe
  the vector store with a semantic :meth:`VectorStoreAdapter.query` and check
  whether that content still surfaces - catching *derived* residual (an embedding
  copy) that a by-id check cannot see. A positive hit is deterministic evidence of
  residual; a clean result is best-effort (a non-hit is evidence, not proof of
  absence). The content is used only to query and is **never** persisted: a
  fingerprint finding records a hash of the phrase, so the attestation holds no PII.

A surface is ``ERASED`` only when every supplied id is gone **and** no supplied
content still surfaces; ``RESIDUAL`` if either remains; ``NOT_COVERED`` when the
surface was not (or could not be) checked - never a vacuous ``ERASED``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sectum_ai.adapters import CacheAdapter, VectorStoreAdapter
from sectum_ai.probes.erasure import ErasureReport, SurfaceErasure
from sectum_ai.spec import Finding, FindingStatus, Severity, Surface, sha256_hex

# The erasure surfaces with a by-id existence primitive in the adapter SDK today.
# A subject's ids on any other surface cannot be checked by id yet, so they read
# NOT_COVERED until that adapter family gains a by-id accessor.
SUBJECT_VERIFIABLE_SURFACES: tuple[Surface, ...] = (Surface.VECTOR_DB, Surface.SEMANTIC_CACHE)

# Surfaces that support content-fingerprint (semantic-query) residual probing today.
SUBJECT_FINGERPRINT_SURFACES: tuple[Surface, ...] = (Surface.VECTOR_DB,)

# How many nearest neighbours a fingerprint probe inspects for the subject's content.
_FINGERPRINT_QUERY_K = 10

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
_FINGERPRINT_REMEDIATION = (
    "the subject's content still surfaces in a semantic query of the vector store; "
    "purge the derived embeddings/records that still carry it"
)


@dataclass(frozen=True)
class SubjectManifest:
    """A data subject's record ids and (optional) content fingerprints, per surface.

    ``subject_ref`` is an opaque, customer-chosen reference for the DSR. ``records``
    maps an erasure surface to the subject's record **ids** on it (a vector
    ``doc_id``, a cache key, ...) - ids only, no PII. ``fingerprints`` maps a surface
    to the subject's known **content** phrases to probe for residual derived data;
    this is the one place subject content is supplied, and it is used only to query -
    never persisted (a fingerprint finding records a hash, not the phrase).
    """

    subject_ref: str
    records: Mapping[Surface, tuple[str, ...]]
    fingerprints: Mapping[Surface, tuple[str, ...]] = field(default_factory=dict)


class SubjectErasureProbe:
    """Verify a real data subject's records are gone by id and by content (A3)."""

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
        """Check the subject's ids and content are gone; return an erasure report.

        For a surface with a configured adapter and supplied ids and/or content,
        ``markers_before`` counts the distinct ids + content phrases checked and
        ``residual_after`` counts those still present, so the verdict is ``ERASED``
        only when nothing remains, ``RESIDUAL`` if any does, and ``NOT_COVERED``
        when the surface was not (or could not be) checked.
        """
        surfaces: list[SurfaceErasure] = []
        findings: list[Finding] = []

        vector = self._vector
        if vector is not None:
            # Dedupe per surface so the count is distinct and a repeat cannot emit
            # two findings with the same finding_id.
            ids = tuple(dict.fromkeys(manifest.records.get(Surface.VECTOR_DB, ())))
            phrases = tuple(dict.fromkeys(manifest.fingerprints.get(Surface.VECTOR_DB, ())))
            if ids or phrases:
                present = [rid for rid in ids if vector.fetch(target, rid) is not None]
                surfacing = [p for p in phrases if self._content_surfaces(vector, target, p)]
                # By-id and content residual both count against the vector surface:
                # it is ERASED only when no id remains AND no content still surfaces.
                surfaces.append(
                    SurfaceErasure(
                        surface=Surface.VECTOR_DB,
                        markers_before=len(ids) + len(phrases),
                        residual_after=len(present) + len(surfacing),
                    )
                )
                findings.extend(
                    self._residual_finding(target, Surface.VECTOR_DB, manifest.subject_ref, rid)
                    for rid in present
                )
                findings.extend(
                    self._fingerprint_finding(target, Surface.VECTOR_DB, manifest.subject_ref, p)
                    for p in surfacing
                )

        cache = self._cache
        if cache is not None:
            ids = tuple(dict.fromkeys(manifest.records.get(Surface.SEMANTIC_CACHE, ())))
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
    def _content_surfaces(vector: VectorStoreAdapter, target: UUID, phrase: str) -> bool:
        # A semantic query for the subject's content: if the phrase still appears in
        # any returned document, that content is residual in the vector store - a
        # derived copy the by-id check would miss.
        needle = phrase.casefold()
        hits = vector.query(target, phrase, k=_FINGERPRINT_QUERY_K)
        return any(needle in hit.content.casefold() for hit in hits)

    @staticmethod
    def _surface(surface: Surface, ids: Sequence[str], present: Sequence[str]) -> SurfaceErasure:
        return SurfaceErasure(surface=surface, markers_before=len(ids), residual_after=len(present))

    def _residual_finding(
        self, target: UUID, surface: Surface, subject_ref: str, record_id: str
    ) -> Finding:
        # The evidence span is the record id, not its content: the manifest's records
        # carry ids only, so neither does the attestation.
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

    def _fingerprint_finding(
        self, target: UUID, surface: Surface, subject_ref: str, phrase: str
    ) -> Finding:
        # Data-minimized: the finding stores only a hash of the probed phrase, never
        # the subject's raw content, so the attestation carries no PII even though the
        # probe queried with real content.
        digest = sha256_hex(phrase.encode("utf-8"))[:16]
        return Finding(
            finding_id=f"subject-erasure-fingerprint-{surface.value}-{digest}",
            probe_id=self.id,
            severity=Severity.HIGH,
            confidence=1.0,
            status=FindingStatus.CONFIRMED,
            owner_tenant_id=target,
            observed_in_tenant_id=target,
            surface=surface,
            marker_id=digest,
            evidence_span=(
                f"subject {subject_ref}: content fingerprint {digest} still surfaces "
                "(semantic probe)"
            ),
            owasp_llm=self.owasp_llm,
            atlas=self.atlas_techniques,
            nist=self.nist_rmf,
            owasp_secondary=self.owasp_secondary,
            remediation_pointer=_FINGERPRINT_REMEDIATION,
        )
