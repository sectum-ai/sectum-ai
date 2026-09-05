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
  the high-risk *derived* surfaces for residual a by-id check cannot see. The
  vector store is probed with a semantic :meth:`VectorStoreAdapter.query`; the
  model is probed with :meth:`ModelAdapter.infer` - both for whole-phrase recall
  and, because a real autoregressive model *continues* a prompt rather than echoing
  it, for prefix-continuation extraction (prompt the leading half, catch the
  sensitive trailing half regurgitated) - and a reproduced completion is residual
  *memorization* (a fine-tune/adapter copy), checked only when the model is trainable
  (per-tenant adapter or shared weights), else the surface reads ``NOT_COVERED``; the
  agent-memory store is probed with :meth:`MemoryAdapter.recall` and the derived
  full-text search index with :meth:`SearchIndexAdapter.search`, each residual when
  the recalled/returned entry still carries the phrase. A positive hit is
  deterministic evidence of residual; a clean result is best-effort (a non-hit is
  evidence, not proof of absence). The content is used only to query and is **never**
  persisted: a fingerprint finding records a hash of the phrase, so the attestation
  holds no PII.

A surface is ``ERASED`` only when every supplied id is gone **and** no supplied
content still surfaces; ``RESIDUAL`` if either remains; ``NOT_COVERED`` when the
surface was not (or could not be) checked - never a vacuous ``ERASED``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sectum_ai.adapters import (
    CacheAdapter,
    Capability,
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    SearchIndexAdapter,
    VectorStoreAdapter,
)
from sectum_ai.probes._recall import content_recalled, continuation_split, has_base_control
from sectum_ai.probes.erasure import ErasureReport, SurfaceErasure
from sectum_ai.spec import Finding, FindingStatus, Severity, Surface, sha256_hex

# The erasure surfaces with a by-id existence primitive in the adapter SDK today.
# A subject's ids on any other surface cannot be checked by id yet, so they read
# NOT_COVERED until that adapter family gains a by-id accessor. Tracing is by-id
# verifiable only when the configured observability adapter implements
# ``fetch_trace`` (else the probe reports it NOT_COVERED, never a false ERASED).
SUBJECT_VERIFIABLE_SURFACES: tuple[Surface, ...] = (
    Surface.VECTOR_DB,
    Surface.SEMANTIC_CACHE,
    Surface.TRACING,
)

# Surfaces that support content-fingerprint residual probing today: the vector store
# (semantic query), the model (residual memorization via inference, when trainable),
# the agent-memory store (recall), and the derived full-text search index (search).
# All are derived surfaces a by-id check cannot see into.
SUBJECT_FINGERPRINT_SURFACES: tuple[Surface, ...] = (
    Surface.VECTOR_DB,
    Surface.MODEL_ADAPTER,
    Surface.AGENT_MEMORY,
    Surface.SEARCH_INDEX,
)

# How many nearest neighbours a fingerprint probe inspects for the subject's content.
_FINGERPRINT_QUERY_K = 50

_REMEDIATION = {
    Surface.VECTOR_DB: (
        "a record named in the subject's erasure request is still fetchable by id; "
        "purge the orphaned vector(s)"
    ),
    Surface.SEMANTIC_CACHE: (
        "a record named in the subject's erasure request is still present in the cache; "
        "evict the entry"
    ),
    Surface.TRACING: (
        "a trace named in the subject's erasure request is still fetchable by id; "
        "purge the tenant's traces from the observability backend"
    ),
}
_FINGERPRINT_REMEDIATION = {
    Surface.VECTOR_DB: (
        "the subject's content still surfaces in a semantic query of the vector store; "
        "purge the derived embeddings/records that still carry it"
    ),
    Surface.MODEL_ADAPTER: (
        "the subject's content is still reproduced by the model; retire or retrain the "
        "tenant's fine-tune/adapter so it no longer memorizes it"
    ),
    Surface.AGENT_MEMORY: (
        "the subject's content still surfaces in a recall from the agent-memory store; "
        "purge the tenant's memory entries that still carry it"
    ),
    Surface.SEARCH_INDEX: (
        "the subject's content still surfaces in the derived full-text search index; "
        "purge the tenant's documents from the index"
    ),
}
# The label each fingerprint surface uses in a finding's evidence span - the probe
# method that surfaced the residual.
_FINGERPRINT_PROBE_LABEL = {
    Surface.VECTOR_DB: "semantic probe",
    Surface.MODEL_ADAPTER: "model inference probe",
    Surface.AGENT_MEMORY: "memory recall probe",
    Surface.SEARCH_INDEX: "search-index probe",
}


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
        observability: ObservabilityAdapter | None = None,
        model: ModelAdapter | None = None,
        memory: MemoryAdapter | None = None,
        search_index: SearchIndexAdapter | None = None,
    ) -> None:
        self._vector = vector
        self._cache = cache
        self._observability = observability
        self._model = model
        self._memory = memory
        self._search_index = search_index

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
        unverifiable: dict[Surface, int] = {}

        vector = self._vector
        if vector is not None:
            # Dedupe per surface so the count is distinct and a repeat cannot emit
            # two findings with the same finding_id.
            ids = tuple(dict.fromkeys(manifest.records.get(Surface.VECTOR_DB, ())))
            phrases = tuple(dict.fromkeys(manifest.fingerprints.get(Surface.VECTOR_DB, ())))
            if ids or phrases:
                present = [rid for rid in ids if vector.fetch(target, rid) is not None]
                verdicts = {p: self._content_surfaces(vector, target, p) for p in phrases}
                surfacing = [p for p, v in verdicts.items() if v]
                inconclusive = sum(1 for v in verdicts.values() if v is None)
                if inconclusive:
                    unverifiable[Surface.VECTOR_DB] = inconclusive
                # By-id and content residual both count against the vector surface:
                # it is ERASED only when no id remains AND no content still surfaces -
                # and never while a phrase could not be checked.
                if present or surfacing or not inconclusive:
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

        observability = self._observability
        if observability is not None:
            ids = tuple(dict.fromkeys(manifest.records.get(Surface.TRACING, ())))
            if ids:
                try:
                    present = [
                        tid for tid in ids if observability.fetch_trace(target, tid) is not None
                    ]
                except NotImplementedError:
                    # The adapter has no by-id trace fetch: leave the surface unscanned
                    # so the coverage block reads NOT_COVERED, never a false ERASED.
                    pass
                else:
                    surfaces.append(self._surface(Surface.TRACING, ids, present))
                    findings.extend(
                        self._residual_finding(target, Surface.TRACING, manifest.subject_ref, tid)
                        for tid in present
                    )

        model = self._model
        if model is not None:
            # The model surface is fingerprint-only: there is no "fetch a memorized
            # fact by id" primitive, so a subject's model residual is caught by
            # probing inference with the subject's content. Only a trainable model
            # (per-tenant adapter or shared weights) can memorize it; a serving-only
            # endpoint trained nothing, so the surface is left unscanned and reads
            # NOT_COVERED - never a vacuous ERASED, the same gate as the Class 11
            # canary model scan.
            supplied = tuple(dict.fromkeys(manifest.fingerprints.get(Surface.MODEL_ADAPTER, ())))
            phrases = (
                tuple(p for p in supplied if continuation_split(p) is not None)
                if has_base_control(model)
                # Without a base-knowledge control every phrase is unverifiable:
                # see `_recall.has_base_control`.
                else ()
            )
            if len(phrases) < len(supplied):
                # A fingerprint the continuation check cannot verify (a bare
                # two-word name; a prefix with no control form). It is counted, the
                # verifiable phrases are still scanned, and the surface can read
                # RESIDUAL (something recalled) or NOT_COVERED - never ERASED "for
                # the subject" on the phrases that survived.
                unverifiable[Surface.MODEL_ADAPTER] = len(supplied) - len(phrases)
            if phrases and self._model_can_memorize(model):
                recalled = [p for p in phrases if self._content_recalled(model, target, p)]
                if recalled or Surface.MODEL_ADAPTER not in unverifiable:
                    surfaces.append(
                        SurfaceErasure(
                            surface=Surface.MODEL_ADAPTER,
                            markers_before=len(phrases),
                            residual_after=len(recalled),
                        )
                    )
                findings.extend(
                    self._fingerprint_finding(
                        target, Surface.MODEL_ADAPTER, manifest.subject_ref, p
                    )
                    for p in recalled
                )

        memory = self._memory
        if memory is not None:
            # Fingerprint-only, like the vector store: the agent-memory store has no
            # stable by-id primitive, so a subject's residual is caught by recalling
            # the subject's content and checking the returned entries still carry it.
            phrases = tuple(dict.fromkeys(manifest.fingerprints.get(Surface.AGENT_MEMORY, ())))
            if phrases:
                surfacing = [p for p in phrases if self._content_in_memory(memory, target, p)]
                surfaces.append(
                    SurfaceErasure(
                        surface=Surface.AGENT_MEMORY,
                        markers_before=len(phrases),
                        residual_after=len(surfacing),
                    )
                )
                findings.extend(
                    self._fingerprint_finding(target, Surface.AGENT_MEMORY, manifest.subject_ref, p)
                    for p in surfacing
                )

        search_index = self._search_index
        if search_index is not None:
            # Fingerprint-only: the derived full-text index is searched for the
            # subject's content, and a hit whose text still carries the phrase is
            # residual in the tenth hiding place a by-id check cannot see into.
            phrases = tuple(dict.fromkeys(manifest.fingerprints.get(Surface.SEARCH_INDEX, ())))
            if phrases:
                surfacing = [p for p in phrases if self._content_in_search(search_index, target, p)]
                surfaces.append(
                    SurfaceErasure(
                        surface=Surface.SEARCH_INDEX,
                        markers_before=len(phrases),
                        residual_after=len(surfacing),
                    )
                )
                findings.extend(
                    self._fingerprint_finding(target, Surface.SEARCH_INDEX, manifest.subject_ref, p)
                    for p in surfacing
                )

        return ErasureReport(
            target_tenant=target,
            surfaces=tuple(surfaces),
            findings=tuple(findings),
            unverifiable=unverifiable,
        )

    @staticmethod
    def _content_surfaces(vector: VectorStoreAdapter, target: UUID, phrase: str) -> bool | None:
        # A semantic query for the subject's content: if the phrase still appears in
        # any returned document, that content is residual in the vector store - a
        # derived copy the by-id check would miss. ``None`` when the page came back
        # full without it: a stored document ranked past k is indistinguishable
        # from an erased one, and read as erased.
        needle = phrase.casefold()
        hits = vector.query(target, phrase, k=_FINGERPRINT_QUERY_K)
        if any(needle in hit.content.casefold() for hit in hits):
            return True
        return None if len(hits) >= _FINGERPRINT_QUERY_K else False

    @staticmethod
    def _content_in_memory(memory: MemoryAdapter, target: UUID, phrase: str) -> bool:
        # A keyword recall of the subject's content: if the phrase still appears in any
        # recalled memory entry, that content is residual in the agent-memory store.
        needle = phrase.casefold()
        return any(needle in entry.casefold() for entry in memory.recall(target, phrase))

    @staticmethod
    def _content_in_search(search: SearchIndexAdapter, target: UUID, phrase: str) -> bool:
        # A full-text search for the subject's content: if the phrase still appears in
        # any returned hit, that content is residual in the derived search index.
        needle = phrase.casefold()
        return any(needle in hit.casefold() for hit in search.search(target, phrase))

    @staticmethod
    def _content_recalled(model: ModelAdapter, target: UUID, phrase: str) -> bool:
        return content_recalled(model, target, phrase)

    @staticmethod
    def _continuation_split(phrase: str) -> tuple[str, str] | None:
        return continuation_split(phrase)

    @staticmethod
    def _model_can_memorize(model: ModelAdapter) -> bool:
        # A model can hold a subject's residual only if it trains per-tenant
        # adapters/fine-tunes or shares (bleeding) weights; a serving-only endpoint
        # memorizes nothing, so its surface is NOT_COVERED, never a false ERASED.
        return any(
            model.supports(cap)
            for cap in (Capability.PER_TENANT_ADAPTER, Capability.SHARED_WEIGHTS)
        )

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
                f"({_FINGERPRINT_PROBE_LABEL[surface]})"
            ),
            owasp_llm=self.owasp_llm,
            atlas=self.atlas_techniques,
            nist=self.nist_rmf,
            owasp_secondary=self.owasp_secondary,
            remediation_pointer=_FINGERPRINT_REMEDIATION[surface],
        )
