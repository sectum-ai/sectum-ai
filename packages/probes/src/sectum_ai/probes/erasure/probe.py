"""Class 11 - GDPR Article 17 erasure verification (the engineering spec, section 7).

The wedge SKU. It confirms a target tenant's hard canaries are present on each
configured surface, runs the erasure flow, then re-scans every surface; any
marker still observable post-erasure is an itemized erasure failure.

Unlike the catalog's attack probes, Class 11 is a pre/erase/post workflow rather
than a plan/detect probe, so it exposes its own ``run`` entry point and returns
an ``ErasureReport`` instead of a flat finding list.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from uuid import UUID

from sectum_ai.adapters import (
    BackupAdapter,
    CacheAdapter,
    EvalSetAdapter,
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    SearchIndexAdapter,
    VectorStoreAdapter,
)
from sectum_ai.spec import (
    CoverageVerdict,
    ErasureUnsupported,
    Finding,
    FindingStatus,
    Marker,
    MarkerType,
    Severity,
    Substrate,
    Surface,
)

# The canonical, ordered set of surfaces a Class 11 erasure run can verify - the
# spec's "10 hiding places" (the engineering spec, section 7, Class 11) that have
# a scanning adapter today. A coverage block reports a verdict for *every* one of
# these, so a surface that was out of scope or unscanned is explicitly
# NOT_COVERED rather than silently absent (the anti-over-claim guarantee). The
# vector store leads because it is always present; the rest follow the run plan's
# order so the coverage matrix reads in a stable, documented sequence.
ERASURE_SURFACES: tuple[Surface, ...] = (
    Surface.VECTOR_DB,
    Surface.TRACING,
    Surface.AGENT_MEMORY,
    Surface.SEMANTIC_CACHE,
    Surface.MODEL_ADAPTER,
    Surface.SEARCH_INDEX,
    Surface.EVAL_SET,
    Surface.BACKUP,
)

# One surface's pre/post scan (target + markers -> the markers still present)
# and its erasure callable, threaded through the uniform _erase_surface helper.
_Scan = Callable[[UUID, tuple[Marker, ...]], list[Marker]]
_Delete = Callable[[UUID], None]


@dataclass(frozen=True)
class SurfaceErasure:
    """The erasure outcome for one surface: markers seen before vs residual after.

    ``erasure_supported`` is ``False`` when the surface's backend exposes no
    programmatic per-tenant erasure API (it raised ``ErasureUnsupported`` from
    ``delete``). That is materially different from a backend that was asked to
    erase and didn't (soft-delete / residual): the data is presumed retained,
    but the gap is a documented backend limitation, not a failure of the
    customer's erasure flow - spec §7, Class 11, hiding place #8
    ("attestable-with-caveat"). It defaults to ``True`` so every surface whose
    backend does support erasure is unaffected.
    """

    surface: Surface
    markers_before: int
    residual_after: int
    erasure_supported: bool = True

    @property
    def erased(self) -> bool:
        """True when a baseline was established and no marker survived erasure.

        A surface with no markers before erasure yields no baseline, so its
        erasure cannot be attested - ``erased`` is ``False`` rather than
        vacuously ``True``. A caveat surface (no programmatic erasure API) is
        never ``erased``: its data is presumed retained.
        """
        if not self.erasure_supported:
            return False
        return self.markers_before > 0 and self.residual_after == 0

    @property
    def attestable_with_caveat(self) -> bool:
        """True when a baseline existed but the backend has no per-tenant erasure API.

        The DPO-facing distinction: the tenant's data was present and the
        backend cannot purge it per-tenant (Helicone, Datadog APM, ...), so it
        is presumed retained until it ages out of the backend's retention
        window. Itemized as a caveat, not conflated with a flow failure.
        """
        return not self.erasure_supported and self.markers_before > 0

    @property
    def verdict(self) -> str:
        """Human-readable: ERASED, RESIDUAL DATA, ATTESTABLE WITH CAVEAT, or NO BASELINE."""
        if self.markers_before == 0:
            return "NO BASELINE"
        if not self.erasure_supported:
            return "ATTESTABLE WITH CAVEAT"
        if self.residual_after == 0:
            return "ERASED"
        return "RESIDUAL DATA"

    @property
    def coverage_verdict(self) -> CoverageVerdict:
        """The machine-readable coverage verdict for this scanned surface.

        Maps the human-readable :attr:`verdict` onto the canonical
        :class:`~sectum_ai.spec.enums.CoverageVerdict` enum recorded in the
        evidence pack's coverage block. A surface with no pre-erasure baseline
        is ``NOT_COVERED`` (its erasure cannot be attested - it is not evidence
        of erasure), aligning the no-baseline case with the unscanned/out-of-scope
        case in the coverage matrix. The anti-over-claim invariant holds here too:
        this property returns ``ERASED`` only when :attr:`erased` is true.
        """
        if self.markers_before == 0:
            return CoverageVerdict.NOT_COVERED
        if not self.erasure_supported:
            return CoverageVerdict.ATTESTABLE_WITH_CAVEAT
        if self.residual_after == 0:
            return CoverageVerdict.ERASED
        return CoverageVerdict.RESIDUAL


@dataclass(frozen=True)
class ErasureReport:
    """The result of an erasure-verification run for one target tenant."""

    target_tenant: UUID
    surfaces: tuple[SurfaceErasure, ...]
    findings: tuple[Finding, ...]

    @property
    def erased(self) -> bool:
        """True when every surface established a baseline and is now clear.

        A caveat surface (no programmatic erasure API) is not ``erased``, so a
        run that includes one is never reported as a clean pass.
        """
        return bool(self.surfaces) and all(surface.erased for surface in self.surfaces)

    @property
    def genuine_residual(self) -> bool:
        """True when a surface that *supports* erasure still has residual data.

        This is a real erasure failure (the backend was asked to erase and the
        marker survived), distinct from a caveat surface that never offered a
        per-tenant erasure API.
        """
        return any(s.erasure_supported and s.residual_after > 0 for s in self.surfaces)

    @property
    def caveats(self) -> tuple[SurfaceErasure, ...]:
        """Surfaces whose backend exposes no per-tenant erasure API (spec §7 #8)."""
        return tuple(s for s in self.surfaces if s.attestable_with_caveat)

    def coverage(self) -> dict[Surface, CoverageVerdict]:
        """The per-surface coverage verdict for *every* erasure surface.

        Returns a verdict for each surface in :data:`ERASURE_SURFACES`, not just
        the scanned ones: a surface that was out of scope or otherwise not
        scanned is ``NOT_COVERED``. This is the honest, anti-over-claim coverage
        record the evidence pack carries - the attestation can never imply more
        coverage than the run actually verified (the engineering spec, section 7,
        Class 11).
        """
        scanned = {surface.surface: surface.coverage_verdict for surface in self.surfaces}
        return {
            surface: scanned.get(surface, CoverageVerdict.NOT_COVERED)
            for surface in ERASURE_SURFACES
        }

    @property
    def not_covered(self) -> tuple[Surface, ...]:
        """Erasure surfaces with no ``ERASED``/``RESIDUAL``/caveat verdict.

        These are the surfaces a DPO must be told the attestation did *not*
        verify (out of scope, no adapter configured, or no pre-erasure
        baseline). Listing them is the other half of an honest verdict: a run is
        "fully erased" only when every scanned surface is ERASED *and* the
        attestation states what was NOT_COVERED.
        """
        return tuple(
            surface
            for surface, verdict in self.coverage().items()
            if verdict is CoverageVerdict.NOT_COVERED
        )


class ErasureProbe:
    """Class 11: verify a tenant's data has left every configured surface."""

    id = "gdpr-erasure-verification"
    name = "GDPR Article 17 erasure verification"
    owasp_llm = "LLM08:2025"
    owasp_secondary: tuple[str, ...] = ("LLM02:2025",)
    # Erasure verification is a control check, not an attack technique, so atlas
    # is intentionally empty (the engineering spec, section 9).
    atlas_techniques: tuple[str, ...] = ()
    nist_rmf: tuple[str, ...] = ("MEASURE 2.7",)

    def __init__(
        self,
        substrate: Substrate,
        *,
        vector: VectorStoreAdapter,
        observability: ObservabilityAdapter | None = None,
        memory: MemoryAdapter | None = None,
        cache: CacheAdapter | None = None,
        model: ModelAdapter | None = None,
        search_index: SearchIndexAdapter | None = None,
        eval_set: EvalSetAdapter | None = None,
        backup: BackupAdapter | None = None,
    ) -> None:
        self._substrate = substrate
        self._vector = vector
        self._observability = observability
        self._memory = memory
        self._cache = cache
        self._model = model
        self._search_index = search_index
        self._eval_set = eval_set
        self._backup = backup
        self._documents = {document.doc_id: document for document in substrate.documents}

    def run(self, target: UUID, *, scope: Iterable[Surface] | None = None) -> ErasureReport:
        """Confirm the target's markers, run the erasure, and re-scan each surface.

        Args:
            target: The tenant whose data the run verifies has been erased.
            scope: When given, restrict the run to this subset of erasure
                surfaces - this backs a cheaper single-surface "snapshot"
                engagement (for example just the vector DB). A surface outside
                the scope is *not scanned* and is reported ``NOT_COVERED`` in the
                report's coverage block, never ``ERASED``. ``None`` (the default)
                scans every configured surface, the unchanged full-run behavior.
                Surfaces in ``scope`` that have no configured adapter are simply
                not scanned (they too read ``NOT_COVERED``); the vector store is
                always present.

        Returns:
            An :class:`ErasureReport` whose ``surfaces`` are exactly the scanned
            surfaces and whose ``coverage()`` reports a verdict for *every*
            erasure surface, so the attestation never implies more coverage than
            it verified.
        """
        in_scope = frozenset(scope) if scope is not None else None
        markers = tuple(
            marker
            for marker in self._substrate.manifest.markers
            if marker.owner_tenant_id == target and marker.marker_type is MarkerType.HARD_CANARY
        )
        surfaces: list[SurfaceErasure] = []
        findings: list[Finding] = []

        # Each configured surface runs the same pre/erase/post flow, so it is
        # driven through one caveat-tolerant helper. The vector store is always
        # present; the rest are optional. A backend that exposes no per-tenant
        # erasure API (raising ``ErasureUnsupported``) is itemized as a caveat
        # on *any* surface, not just observability - the contract is uniform.
        plan: list[tuple[Surface, _Scan, _Delete]] = [
            (Surface.VECTOR_DB, self._scan_vector, self._vector.delete),
        ]
        if self._observability is not None:
            plan.append((Surface.TRACING, self._scan_observability, self._observability.delete))
        if self._memory is not None:
            plan.append((Surface.AGENT_MEMORY, self._scan_memory, self._memory.delete))
        if self._cache is not None:
            plan.append((Surface.SEMANTIC_CACHE, self._scan_cache, self._cache.delete))
        if self._model is not None:
            plan.append((Surface.MODEL_ADAPTER, self._scan_model, self._model.delete))
        if self._search_index is not None:
            plan.append((Surface.SEARCH_INDEX, self._scan_search, self._search_index.delete))
        if self._eval_set is not None:
            plan.append((Surface.EVAL_SET, self._scan_eval, self._eval_set.delete))
        if self._backup is not None:
            plan.append((Surface.BACKUP, self._scan_backup, self._backup.delete))

        for surface, scan, delete in plan:
            # A scope skips a surface entirely - it is left out of ``surfaces`` so
            # the coverage block marks it NOT_COVERED rather than scanning it.
            if in_scope is not None and surface not in in_scope:
                continue
            surface_result, surface_findings = self._erase_surface(
                target, markers, surface, scan, delete
            )
            surfaces.append(surface_result)
            findings.extend(surface_findings)

        return ErasureReport(
            target_tenant=target, surfaces=tuple(surfaces), findings=tuple(findings)
        )

    def _erase_surface(
        self,
        target: UUID,
        markers: tuple[Marker, ...],
        surface: Surface,
        scan: _Scan,
        delete: _Delete,
    ) -> tuple[SurfaceErasure, list[Finding]]:
        """Run the pre/erase/post flow for one surface; return its result + findings.

        Catches ``ErasureUnsupported`` so a backend with no per-tenant erasure
        API is recorded as *attestable-with-caveat* (data presumed retained,
        never a false PASS) rather than crashing the run or being misreported
        as a flow failure (spec §7, Class 11, hiding place #8).
        """
        before = scan(target, markers)
        supported = True
        try:
            delete(target)
        except ErasureUnsupported:
            supported = False
        residual = scan(target, markers)
        surface_result = SurfaceErasure(
            surface=surface,
            markers_before=len(before),
            residual_after=len(residual),
            erasure_supported=supported,
        )
        if supported:
            surface_findings = [
                self._residual_finding(target, marker, surface) for marker in residual
            ]
        else:
            # Nothing was deleted, so every marker that was present remains;
            # itemize them all as caveats from the pre-erasure baseline.
            surface_findings = [self._caveat_finding(target, marker, surface) for marker in before]
        return surface_result, surface_findings

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

    def _scan_cache(self, target: UUID, markers: tuple[Marker, ...]) -> list[Marker]:
        """Return the target's hard-canary markers still present in the cache."""
        if self._cache is None:
            return []
        values = self._cache.values(target)
        return [marker for marker in markers if any(marker.plaintext in value for value in values)]

    def _scan_model(self, target: UUID, markers: tuple[Marker, ...]) -> list[Marker]:
        """Return the target's hard-canary markers the model still reproduces.

        Querying the model with the canary surfaces it only while the tenant's
        fine-tune/adapter has memorized it; once the adapter is erased the model
        recalls nothing for that prompt.
        """
        if self._model is None:
            return []
        model = self._model
        return [
            marker
            for marker in markers
            if marker.plaintext in model.infer(target, marker.plaintext)
        ]

    def _scan_search(self, target: UUID, markers: tuple[Marker, ...]) -> list[Marker]:
        """Return the target's hard-canary markers still present in the search index."""
        if self._search_index is None:
            return []
        search_index = self._search_index
        return [
            marker
            for marker in markers
            if any(marker.plaintext in hit for hit in search_index.search(target, marker.plaintext))
        ]

    def _scan_eval(self, target: UUID, markers: tuple[Marker, ...]) -> list[Marker]:
        """Return the target's hard-canary markers still present in the eval set."""
        if self._eval_set is None:
            return []
        eval_set = self._eval_set
        return [
            marker
            for marker in markers
            if any(marker.plaintext in hit for hit in eval_set.search(target, marker.plaintext))
        ]

    def _scan_backup(self, target: UUID, markers: tuple[Marker, ...]) -> list[Marker]:
        """Return the target's hard-canary markers still present in the backups."""
        if self._backup is None:
            return []
        backup = self._backup
        return [
            marker
            for marker in markers
            if any(marker.plaintext in hit for hit in backup.search(target, marker.plaintext))
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
            Surface.SEMANTIC_CACHE: (
                "data survived an Article 17 erasure; evict the tenant's entries from the "
                "semantic/application cache"
            ),
            Surface.MODEL_ADAPTER: (
                "data survived an Article 17 erasure; retire or retrain the tenant's "
                "fine-tune/adapter so it no longer reproduces the data"
            ),
            Surface.SEARCH_INDEX: (
                "data survived an Article 17 erasure; purge the tenant's documents from the "
                "derived full-text search index"
            ),
            Surface.EVAL_SET: (
                "data survived an Article 17 erasure; purge the tenant's fixtures from the "
                "evaluation / golden test set"
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
            atlas=self.atlas_techniques,
            nist=self.nist_rmf,
            owasp_secondary=self.owasp_secondary,
            remediation_pointer=remediation,
        )

    def _caveat_finding(self, target: UUID, marker: Marker, surface: Surface) -> Finding:
        """A finding for a surface whose backend exposes no programmatic erasure API.

        This is *attestable-with-caveat* (spec §7 Class 11 #8), not an erasure
        *failure*: the customer's erasure flow is not broken - the backend
        simply offers no per-tenant delete, so the data is presumed retained
        and must be purged via the backend's own retention policy or console.
        The distinction matters to a DPO, so it is carried in the remediation
        pointer rather than conflated with a residual-after-erasure finding.

        Status is ``UNVERIFIED``, not ``CONFIRMED``: a caveat is a backend
        coverage limitation on the *same* tenant (``owner == observed``), not a
        confirmed cross-tenant leak. Holding it in the unverified bucket (the
        false-positive control) keeps it out of the confirmed-findings count and
        the ``sectum-ai diff`` / ``baseline`` regression gates (``newly_confirmed``),
        so onboarding a no-per-tenant-erasure-API backend never reads as a
        regression - the "caveats never regress" contract applied to the finding
        paths, not just the ``erasure_caveats`` metric dict.
        """
        return Finding(
            finding_id=f"erasure-caveat-{surface.value}-{marker.marker_id}",
            probe_id=self.id,
            severity=Severity.MEDIUM,
            confidence=1.0,
            status=FindingStatus.UNVERIFIED,
            owner_tenant_id=target,
            observed_in_tenant_id=target,
            surface=surface,
            marker_id=marker.marker_id,
            evidence_span=marker.plaintext,
            owasp_llm=self.owasp_llm,
            atlas=self.atlas_techniques,
            nist=self.nist_rmf,
            owasp_secondary=self.owasp_secondary,
            remediation_pointer=(
                "ATTESTABLE WITH CAVEAT: this backend exposes no programmatic "
                "per-tenant erasure API, so Article 17 erasure cannot be verified "
                "through it; purge the tenant's data via the backend's retention "
                "policy or console and re-run. This is a backend limitation, not "
                "a failure of the erasure flow."
            ),
        )
