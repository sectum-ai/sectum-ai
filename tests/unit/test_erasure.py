"""Tests for Class 11 - the GDPR Article 17 erasure-verification wedge."""

from uuid import UUID

from sectum_ai.adapters import (
    FakeBackup,
    FakeCache,
    FakeEvalSet,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeSearchIndex,
    FakeVectorStore,
)
from sectum_ai.adapters.base import ObservabilityAdapter, VectorHit
from sectum_ai.probes import ERASURE_SURFACES, ErasureProbe
from sectum_ai.spec import CoverageVerdict, MarkerType, Substrate, Surface
from sectum_ai.substrate import build_substrate, default_scenario


def _seeded_store(substrate: Substrate, *, soft_delete: bool) -> FakeVectorStore:
    store = FakeVectorStore(soft_delete=soft_delete)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        store.upsert(tenant.tenant_id, documents)
    return store


def _seeded_observability(substrate: Substrate, *, soft_delete: bool) -> FakeObservability:
    obs = FakeObservability(soft_delete=soft_delete)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            obs.record(
                marker.owner_tenant_id,
                "sectum-ai-erasure",
                f"trace recording marker {marker.plaintext}",
            )
    return obs


def _seeded_memory(substrate: Substrate, *, soft_delete: bool) -> FakeMemory:
    memory = FakeMemory(soft_delete=soft_delete)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            memory.remember(marker.owner_tenant_id, f"memory note recording {marker.plaintext}")
    return memory


def _seeded_cache(substrate: Substrate, *, soft_delete: bool) -> FakeCache:
    cache = FakeCache(soft_delete=soft_delete)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            cache.set(
                marker.owner_tenant_id,
                f"sectum-ai-erasure-{marker.marker_id}",
                f"cached answer mentioning {marker.plaintext}",
            )
    return cache


def _seeded_model(substrate: Substrate, *, soft_delete: bool) -> FakeModel:
    model = FakeModel(soft_delete=soft_delete)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            model.train_adapter(marker.owner_tenant_id, [f"fine-tune sample {marker.plaintext}"])
    return model


def _seeded_search(substrate: Substrate, *, soft_delete: bool) -> FakeSearchIndex:
    search = FakeSearchIndex(soft_delete=soft_delete)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            search.index(
                marker.owner_tenant_id, f"search index entry mentioning {marker.plaintext}"
            )
    return search


def _seeded_eval(substrate: Substrate, *, soft_delete: bool) -> FakeEvalSet:
    eval_set = FakeEvalSet(soft_delete=soft_delete)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            eval_set.add(marker.owner_tenant_id, f"eval set fixture mentioning {marker.plaintext}")
    return eval_set


def test_erasure_is_verified_when_the_store_hard_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    report = ErasureProbe(substrate, vector=store).run(target)
    # default (no observability adapter) reports only the vector-store surface
    assert tuple(surface.surface for surface in report.surfaces) == (Surface.VECTOR_DB,)
    assert report.surfaces[0].markers_before > 0
    assert report.erased
    assert report.findings == ()


def test_erasure_fails_when_the_store_soft_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=True)
    report = ErasureProbe(substrate, vector=store).run(target)
    assert report.surfaces[0].markers_before > 0
    assert not report.erased
    assert report.findings
    assert all(finding.owner_tenant_id == target for finding in report.findings)


def test_erasure_leaves_other_tenants_untouched() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    other = substrate.tenants[1].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    ErasureProbe(substrate, vector=store).run(target)
    assert store.query(other, "record", k=10)


def test_erasure_is_inconclusive_without_a_baseline() -> None:
    """An empty store yields no pre-erasure baseline, so erasure cannot be attested."""
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = FakeVectorStore()  # never populated: nothing to establish a baseline
    report = ErasureProbe(substrate, vector=store).run(target)
    assert report.surfaces[0].markers_before == 0
    assert report.surfaces[0].verdict == "NO BASELINE"
    assert not report.erased
    assert report.findings == ()


def test_erasure_clears_observability_when_the_backend_hard_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    obs = _seeded_observability(substrate, soft_delete=False)
    report = ErasureProbe(substrate, vector=store, observability=obs).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert Surface.TRACING in surfaces
    assert surfaces[Surface.TRACING].markers_before > 0
    assert surfaces[Surface.TRACING].residual_after == 0
    assert report.erased


def test_erasure_fails_when_observability_soft_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    obs = _seeded_observability(substrate, soft_delete=True)
    report = ErasureProbe(substrate, vector=store, observability=obs).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert surfaces[Surface.TRACING].residual_after > 0
    assert not report.erased
    assert any(finding.surface is Surface.TRACING for finding in report.findings)


def test_erasure_reports_a_caveat_when_observability_has_no_erasure_api() -> None:
    # A backend whose delete() raises ErasureUnsupported (Helicone / Datadog)
    # must NOT crash the run and must NOT be reported as erased: the data is
    # presumed retained, so the surface shows residual + a caveat finding
    # distinct from an erasure *failure* (spec §7 Class 11 hiding place #8).
    from uuid import UUID

    from sectum_ai.adapters.base import ObservabilityAdapter, TraceHit
    from sectum_ai.spec import ErasureUnsupported

    class _NoErasureObservability(ObservabilityAdapter):
        def __init__(self, seeded: FakeObservability) -> None:
            super().__init__("no-erasure-obs")
            self._seeded = seeded

        def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
            return self._seeded.search_traces(tenant, marker)

        def list_projects(self) -> list[str]:
            return self._seeded.list_projects()

        def delete(self, tenant: UUID) -> None:
            raise ErasureUnsupported("backend exposes no per-tenant erasure API")

    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    obs = _NoErasureObservability(_seeded_observability(substrate, soft_delete=False))
    report = ErasureProbe(substrate, vector=store, observability=obs).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    tracing = surfaces[Surface.TRACING]
    # the surface is recorded (no crash) and shows residual = before (retained)
    assert tracing.markers_before > 0
    assert tracing.residual_after == tracing.markers_before
    assert not report.erased
    # the caveat is distinct end to end: not erasure_supported, a dedicated
    # verdict, and surfaced on the report as a caveat rather than a genuine
    # residual failure (the soft-delete case below) - spec §7 #8.
    assert not tracing.erasure_supported
    assert tracing.attestable_with_caveat
    assert tracing.verdict == "ATTESTABLE WITH CAVEAT"
    assert not report.genuine_residual
    assert tracing in report.caveats
    # a caveat finding is emitted, distinct from a residual-after-erasure finding
    caveat_findings = [
        finding
        for finding in report.findings
        if finding.surface is Surface.TRACING
        and "ATTESTABLE WITH CAVEAT" in finding.remediation_pointer
    ]
    assert caveat_findings
    assert all(finding.finding_id.startswith("erasure-caveat-") for finding in caveat_findings)


def _seeded_backup(
    substrate: Substrate, *, soft_delete: bool = False, no_erasure: bool = False
) -> FakeBackup:
    backup = FakeBackup(soft_delete=soft_delete, no_erasure=no_erasure)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            backup.add(marker.owner_tenant_id, f"backup snapshot mentioning {marker.plaintext}")
    return backup


def test_erasure_clears_backup_when_it_hard_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    report = ErasureProbe(substrate, vector=store, backup=_seeded_backup(substrate)).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert Surface.BACKUP in surfaces
    assert surfaces[Surface.BACKUP].markers_before > 0
    assert surfaces[Surface.BACKUP].residual_after == 0
    assert report.erased


def test_erasure_fails_when_backup_soft_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    report = ErasureProbe(
        substrate, vector=store, backup=_seeded_backup(substrate, soft_delete=True)
    ).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert surfaces[Surface.BACKUP].residual_after > 0
    assert not report.erased
    assert any(finding.surface is Surface.BACKUP for finding in report.findings)


def test_erasure_reports_a_caveat_when_backup_has_no_erasure_api() -> None:
    # An immutable backup with no per-tenant purge (hiding place #7) is the
    # canonical caveat: data presumed retained, never a clean PASS, and distinct
    # from a genuine residual failure.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    report = ErasureProbe(
        substrate, vector=store, backup=_seeded_backup(substrate, no_erasure=True)
    ).run(target)
    backup = {surface.surface: surface for surface in report.surfaces}[Surface.BACKUP]
    assert backup.markers_before > 0
    assert backup.residual_after == backup.markers_before
    assert not backup.erasure_supported
    assert backup.attestable_with_caveat
    assert not report.genuine_residual
    assert backup in report.caveats


def test_erasure_caveat_is_distinct_from_a_soft_delete_failure() -> None:
    # A soft-delete observability backend (delete is a no-op but the API
    # exists) is a genuine residual FAILURE, not a caveat: erasure_supported
    # stays True and the verdict is RESIDUAL DATA. This is the line the caveat
    # path must not blur.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    obs = _seeded_observability(substrate, soft_delete=True)
    report = ErasureProbe(substrate, vector=store, observability=obs).run(target)
    tracing = {s.surface: s for s in report.surfaces}[Surface.TRACING]
    assert tracing.erasure_supported
    assert not tracing.attestable_with_caveat
    assert tracing.verdict == "RESIDUAL DATA"
    assert report.genuine_residual
    assert report.caveats == ()


def test_erasure_clears_memory_when_the_store_hard_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    memory = _seeded_memory(substrate, soft_delete=False)
    report = ErasureProbe(substrate, vector=store, memory=memory).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert Surface.AGENT_MEMORY in surfaces
    assert surfaces[Surface.AGENT_MEMORY].markers_before > 0
    assert surfaces[Surface.AGENT_MEMORY].residual_after == 0
    assert report.erased


def test_erasure_fails_when_memory_soft_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    memory = _seeded_memory(substrate, soft_delete=True)
    report = ErasureProbe(substrate, vector=store, memory=memory).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert surfaces[Surface.AGENT_MEMORY].residual_after > 0
    assert not report.erased
    assert any(finding.surface is Surface.AGENT_MEMORY for finding in report.findings)


def test_erasure_clears_cache_when_the_store_hard_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    cache = _seeded_cache(substrate, soft_delete=False)
    report = ErasureProbe(substrate, vector=store, cache=cache).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert Surface.SEMANTIC_CACHE in surfaces
    assert surfaces[Surface.SEMANTIC_CACHE].markers_before > 0
    assert surfaces[Surface.SEMANTIC_CACHE].residual_after == 0
    assert report.erased


def test_erasure_fails_when_cache_soft_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    cache = _seeded_cache(substrate, soft_delete=True)
    report = ErasureProbe(substrate, vector=store, cache=cache).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert surfaces[Surface.SEMANTIC_CACHE].residual_after > 0
    assert not report.erased
    assert any(finding.surface is Surface.SEMANTIC_CACHE for finding in report.findings)


def test_erasure_clears_the_model_adapter_when_it_hard_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    model = _seeded_model(substrate, soft_delete=False)
    report = ErasureProbe(substrate, vector=store, model=model).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert Surface.MODEL_ADAPTER in surfaces
    assert surfaces[Surface.MODEL_ADAPTER].markers_before > 0
    assert surfaces[Surface.MODEL_ADAPTER].residual_after == 0
    assert report.erased


def test_erasure_clears_the_model_adapter_under_weight_bleed() -> None:
    # With adapter_bleed, infer(target) recalls every tenant's adapter, so foreign
    # canaries (all sharing the SECTUM-CANARY- prefix) are returned. The scan's
    # substring check on the target's OWN plaintext keeps the verdict correct:
    # after deleting the target's adapter, its canary is no longer a substring of
    # any recall, so the surface reads ERASED rather than a false residual.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    model = FakeModel(adapter_bleed=True)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            model.train_adapter(marker.owner_tenant_id, [f"fine-tune sample {marker.plaintext}"])
    report = ErasureProbe(substrate, vector=store, model=model).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert surfaces[Surface.MODEL_ADAPTER].markers_before > 0
    assert surfaces[Surface.MODEL_ADAPTER].residual_after == 0
    assert report.erased


def test_erasure_fails_when_the_model_adapter_soft_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    model = _seeded_model(substrate, soft_delete=True)
    report = ErasureProbe(substrate, vector=store, model=model).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert surfaces[Surface.MODEL_ADAPTER].residual_after > 0
    assert not report.erased
    assert any(finding.surface is Surface.MODEL_ADAPTER for finding in report.findings)


def test_erasure_model_surface_is_not_covered_for_a_serving_only_model() -> None:
    # A serving-only model (vLLM/TGI) supports neither PER_TENANT_ADAPTER nor
    # SHARED_WEIGHTS, so it trained nothing that could hold a canary: the erasure
    # scan must skip inference entirely and read NOT_COVERED, never a vacuous ERASED.
    # The backend's complete raises if reached, proving no per-marker I/O happens
    # (so a flaky serving backend cannot abort an erasure run).
    from sectum_ai.adapters.model.vllm import VLLMModel

    class _ServingBackend:
        def complete(self, prompt: str) -> str:
            raise AssertionError("infer must not be called for a serving-only model")

        def first_token_latency_ms(self, prompt: str) -> float:
            return 0.0

    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    report = ErasureProbe(substrate, vector=store, model=VLLMModel(_ServingBackend())).run(target)
    # Not a scanned surface at all: in the plan it scanned to a zero baseline, and a
    # zero-baseline surface also makes `erased` false - so configuring a serving
    # model turned an otherwise ERASED run INCONCLUSIVE (exit 3).
    assert Surface.MODEL_ADAPTER not in {surface.surface for surface in report.surfaces}
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.NOT_COVERED
    assert report.erased


def test_erasure_clears_the_search_index_when_it_hard_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    search = _seeded_search(substrate, soft_delete=False)
    report = ErasureProbe(substrate, vector=store, search_index=search).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert Surface.SEARCH_INDEX in surfaces
    assert surfaces[Surface.SEARCH_INDEX].markers_before > 0
    assert surfaces[Surface.SEARCH_INDEX].residual_after == 0
    assert report.erased


def test_erasure_fails_when_the_search_index_soft_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    search = _seeded_search(substrate, soft_delete=True)
    report = ErasureProbe(substrate, vector=store, search_index=search).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert surfaces[Surface.SEARCH_INDEX].residual_after > 0
    assert not report.erased
    assert any(finding.surface is Surface.SEARCH_INDEX for finding in report.findings)


def test_erasure_clears_the_eval_set_when_it_hard_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    eval_set = _seeded_eval(substrate, soft_delete=False)
    report = ErasureProbe(substrate, vector=store, eval_set=eval_set).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert Surface.EVAL_SET in surfaces
    assert surfaces[Surface.EVAL_SET].markers_before > 0
    assert surfaces[Surface.EVAL_SET].residual_after == 0
    assert report.erased


def test_erasure_fails_when_the_eval_set_soft_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    eval_set = _seeded_eval(substrate, soft_delete=True)
    report = ErasureProbe(substrate, vector=store, eval_set=eval_set).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert surfaces[Surface.EVAL_SET].residual_after > 0
    assert not report.erased
    assert any(finding.surface is Surface.EVAL_SET for finding in report.findings)


def _no_erasure_observability(substrate: Substrate) -> ObservabilityAdapter:
    """A FakeObservability whose delete() raises ErasureUnsupported (caveat path)."""
    from uuid import UUID

    from sectum_ai.adapters.base import TraceHit
    from sectum_ai.spec import ErasureUnsupported

    class _NoErasureObservability(ObservabilityAdapter):
        def __init__(self, seeded: FakeObservability) -> None:
            super().__init__("no-erasure-obs")
            self._seeded = seeded

        def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
            return self._seeded.search_traces(tenant, marker)

        def list_projects(self) -> list[str]:
            return self._seeded.list_projects()

        def delete(self, tenant: UUID) -> None:
            raise ErasureUnsupported("backend exposes no per-tenant erasure API")

    return _NoErasureObservability(_seeded_observability(substrate, soft_delete=False))


def test_attestable_with_caveat_finding_is_unverified_not_confirmed() -> None:
    # An attestable-with-caveat finding is a same-tenant backend limitation, not
    # a confirmed cross-tenant leak. It must be UNVERIFIED so the false-positive
    # control (confirmed-count, sectum-ai diff/baseline gates) never treats a
    # no-per-tenant-erasure-API backend as a confirmed finding (spec §7 #8).
    from sectum_ai.spec import FindingStatus

    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    report = ErasureProbe(
        substrate, vector=store, observability=_no_erasure_observability(substrate)
    ).run(target)
    caveat_findings = [
        finding for finding in report.findings if finding.finding_id.startswith("erasure-caveat-")
    ]
    assert caveat_findings
    # Every caveat finding is UNVERIFIED, on the same tenant (not a cross-tenant leak).
    assert all(finding.status is FindingStatus.UNVERIFIED for finding in caveat_findings)
    assert all(
        finding.owner_tenant_id == finding.observed_in_tenant_id for finding in caveat_findings
    )


def test_onboarding_a_caveat_backend_is_not_a_diff_regression() -> None:
    # The "caveats never regress" contract end to end: a later erasure
    # attestation that differs from a clean baseline only by an added
    # no-per-tenant-erasure-API surface must NOT read as a regression in
    # `sectum-ai diff` (no newly-confirmed finding, no confirmed-count bump).
    from sectum_ai.baseline import diff_findings
    from sectum_ai.probes import confirmed_findings

    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id

    # Baseline: every surface erases cleanly (vector store hard-deletes, no obs).
    clean = ErasureProbe(substrate, vector=_seeded_store(substrate, soft_delete=False)).run(target)
    # Later: identical except a tracing backend with no per-tenant erasure API.
    with_caveat = ErasureProbe(
        substrate,
        vector=_seeded_store(substrate, soft_delete=False),
        observability=_no_erasure_observability(substrate),
    ).run(target)

    # The added surface contributes only caveat findings...
    assert any(f.finding_id.startswith("erasure-caveat-") for f in with_caveat.findings)
    # ...which are unverified, so they do not bump the confirmed count...
    assert len(confirmed_findings(with_caveat.findings)) == len(confirmed_findings(clean.findings))
    # ...and do not appear as newly-confirmed in a finding-level diff.
    diff = diff_findings(clean.findings, with_caveat.findings)
    assert diff.newly_confirmed == ()


# --- Snapshot scope + tri-state coverage (anti-over-claim) -------------------


def test_coverage_reports_a_verdict_for_every_erasure_surface() -> None:
    # The coverage block is total: a verdict for every surface in the canonical
    # set, even on a default (vector-store-only) run, so the attestation states
    # an explicit verdict for the surfaces it did not scan rather than omitting
    # them. The eight surfaces are exactly ERASURE_SURFACES.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    report = ErasureProbe(substrate, vector=_seeded_store(substrate, soft_delete=False)).run(target)
    coverage = report.coverage()
    assert set(coverage) == set(ERASURE_SURFACES)
    # The one scanned surface is ERASED; every other surface is NOT_COVERED.
    assert coverage[Surface.VECTOR_DB] is CoverageVerdict.ERASED
    for surface in ERASURE_SURFACES:
        if surface is not Surface.VECTOR_DB:
            assert coverage[surface] is CoverageVerdict.NOT_COVERED


def test_a_scoped_run_only_scans_the_scoped_surfaces() -> None:
    # Feature A1 part 1: --scope verifies a subset. A run scoped to the vector
    # store scans ONLY that surface (its report.surfaces is exactly that one),
    # and every other erasure surface is reported NOT_COVERED in coverage - even
    # though adapters for them are configured and seeded.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    report = ErasureProbe(
        substrate,
        vector=_seeded_store(substrate, soft_delete=False),
        observability=_seeded_observability(substrate, soft_delete=False),
        memory=_seeded_memory(substrate, soft_delete=False),
        cache=_seeded_cache(substrate, soft_delete=False),
    ).run(target, scope=[Surface.VECTOR_DB])
    # Only the scoped surface was actually scanned.
    assert tuple(s.surface for s in report.surfaces) == (Surface.VECTOR_DB,)
    coverage = report.coverage()
    assert coverage[Surface.VECTOR_DB] is CoverageVerdict.ERASED
    # The configured-but-out-of-scope surfaces are NOT_COVERED, not scanned.
    for surface in (Surface.TRACING, Surface.AGENT_MEMORY, Surface.SEMANTIC_CACHE):
        assert coverage[surface] is CoverageVerdict.NOT_COVERED
    assert set(report.not_covered) == set(ERASURE_SURFACES) - {Surface.VECTOR_DB}


def test_a_scoped_run_can_select_multiple_surfaces() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    report = ErasureProbe(
        substrate,
        vector=_seeded_store(substrate, soft_delete=False),
        observability=_seeded_observability(substrate, soft_delete=False),
    ).run(target, scope=[Surface.VECTOR_DB, Surface.TRACING])
    assert {s.surface for s in report.surfaces} == {Surface.VECTOR_DB, Surface.TRACING}
    coverage = report.coverage()
    assert coverage[Surface.VECTOR_DB] is CoverageVerdict.ERASED
    assert coverage[Surface.TRACING] is CoverageVerdict.ERASED
    assert coverage[Surface.AGENT_MEMORY] is CoverageVerdict.NOT_COVERED


def test_a_surface_in_scope_with_no_adapter_is_not_covered() -> None:
    # Scoping to a surface that has no configured adapter does not scan it (only
    # the vector store is wired here), so it reads NOT_COVERED - never ERASED.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    report = ErasureProbe(substrate, vector=_seeded_store(substrate, soft_delete=False)).run(
        target, scope=[Surface.VECTOR_DB, Surface.TRACING]
    )
    assert tuple(s.surface for s in report.surfaces) == (Surface.VECTOR_DB,)
    assert report.coverage()[Surface.TRACING] is CoverageVerdict.NOT_COVERED


def test_an_unscanned_surface_can_never_be_erased() -> None:
    # The anti-over-claim invariant (Feature A1 part 2): for EVERY scope a run
    # could be given, a surface that was not scanned never carries the ERASED
    # verdict in the coverage block. Sweep every single-surface scope and assert
    # that every out-of-scope surface is NOT_COVERED (the only verdict an
    # unscanned surface may hold), proving the pack cannot imply coverage it
    # does not have. All surfaces are configured + seeded with hard-deleting
    # backends, so absent the scope guard they WOULD read ERASED - that is what
    # makes this a real guarantee rather than a vacuous one.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id

    def _full_probe() -> ErasureProbe:
        return ErasureProbe(
            substrate,
            vector=_seeded_store(substrate, soft_delete=False),
            observability=_seeded_observability(substrate, soft_delete=False),
            memory=_seeded_memory(substrate, soft_delete=False),
            cache=_seeded_cache(substrate, soft_delete=False),
            model=_seeded_model(substrate, soft_delete=False),
            search_index=_seeded_search(substrate, soft_delete=False),
            eval_set=_seeded_eval(substrate, soft_delete=False),
            backup=_seeded_backup(substrate),
        )

    # Sanity: with no scope, every surface IS scanned and reads ERASED - so the
    # ERASED verdict is reachable here and the invariant below is non-trivial.
    full = _full_probe().run(target)
    assert all(v is CoverageVerdict.ERASED for v in full.coverage().values())

    for scoped_surface in ERASURE_SURFACES:
        report = _full_probe().run(target, scope=[scoped_surface])
        coverage = report.coverage()
        for surface, verdict in coverage.items():
            if surface is not scoped_surface:
                # The crux: an unscanned surface is NOT_COVERED and, in
                # particular, is NEVER ERASED.
                assert verdict is not CoverageVerdict.ERASED
                assert verdict is CoverageVerdict.NOT_COVERED


def test_a_no_baseline_surface_is_not_covered_in_the_coverage_block() -> None:
    # A scanned surface with no pre-erasure baseline cannot attest erasure, so it
    # maps to NOT_COVERED in the coverage block (aligning the no-baseline case
    # with the out-of-scope case) - never ERASED.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    empty_store = FakeVectorStore()  # never populated -> no baseline
    report = ErasureProbe(substrate, vector=empty_store).run(target)
    assert report.surfaces[0].markers_before == 0
    assert report.surfaces[0].coverage_verdict is CoverageVerdict.NOT_COVERED
    assert report.coverage()[Surface.VECTOR_DB] is CoverageVerdict.NOT_COVERED


def test_coverage_verdict_maps_residual_and_caveat() -> None:
    # The coverage block distinguishes a genuine residual (RESIDUAL) from a
    # no-per-tenant-erasure-API caveat (ATTESTABLE_WITH_CAVEAT) - the two are not
    # conflated, mirroring the human verdict strings.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    residual = ErasureProbe(substrate, vector=_seeded_store(substrate, soft_delete=True)).run(
        target
    )
    assert residual.coverage()[Surface.VECTOR_DB] is CoverageVerdict.RESIDUAL

    caveat = ErasureProbe(
        substrate,
        vector=_seeded_store(substrate, soft_delete=False),
        observability=_no_erasure_observability(substrate),
    ).run(target)
    assert caveat.coverage()[Surface.TRACING] is CoverageVerdict.ATTESTABLE_WITH_CAVEAT


def test_a_continuing_model_that_kept_the_canary_is_residual() -> None:
    # The canary scan was whole-phrase echo only; a real autoregressive LoRA that
    # memorized the canary continues a prefix of it and never echoes it, so a
    # retained LoRA read as absent (NOT_COVERED), never RESIDUAL.
    from collections.abc import Sequence
    from uuid import UUID

    from sectum_ai.adapters import FakeModel

    class _ContinuingLora(FakeModel):
        def __init__(self) -> None:
            super().__init__()
            self._memory: dict[UUID, list[str]] = {}

        def train_adapter(
            self, tenant: UUID, texts: Sequence[str], *, user: UUID | None = None
        ) -> None:
            self._memory.setdefault(tenant, []).extend(texts)

        def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
            for text in self._memory.get(tenant, []):
                for token in text.split():
                    if len(prompt) >= 3 and token.startswith(prompt) and token != prompt:
                        return token[len(prompt) :]
            return "nothing comes to mind"

        def delete(self, tenant: UUID) -> None:
            return None  # a soft delete: the LoRA keeps serving

    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    model = _ContinuingLora()
    for marker in substrate.manifest.markers:
        if marker.owner_tenant_id == target and marker.marker_type is MarkerType.HARD_CANARY:
            model.train_adapter(target, [marker.plaintext])
    store = _seeded_store(substrate, soft_delete=False)
    report = ErasureProbe(substrate, vector=store, model=model).run(target)
    assert report.coverage()[Surface.MODEL_ADAPTER] is CoverageVerdict.RESIDUAL


def test_a_marker_ranked_past_the_page_is_not_attested_erased() -> None:
    # The Class 11 vector scan read a full similarity page as absence, and did it
    # at k=10 while its A3 sibling had already moved to k=50 with an inconclusive
    # verdict. A canary the store still returns - just below the page - therefore
    # attested ERASED under GDPR Article 17 and CCPA 1798.105.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=True)  # nothing is really deleted

    class _PagedStore(FakeVectorStore):
        """Answers every query with a FULL page that never holds the canary."""

        def __init__(self, inner: FakeVectorStore) -> None:
            self._inner = inner
            self._truncate = False

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

        def delete(self, tenant: UUID) -> None:
            self._inner.delete(tenant)
            self._truncate = True

        def query(
            self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
        ) -> list[VectorHit]:
            hits = self._inner.query(tenant, text, k, user=user)
            if not self._truncate:
                return hits
            # Still stored, but every canary now ranks past the page.
            return [
                VectorHit(doc_id=f"filler-{index}", tenant_id=tenant, score=1.0, content="filler")
                for index in range(k)
            ]

    paged = _PagedStore(store)
    report = ErasureProbe(substrate, vector=paged).run(target)
    surface = report.surfaces[0]
    assert surface.markers_before > 0
    assert surface.residual_after == 0  # nothing was FOUND
    assert surface.unverifiable_after > 0  # but absence was never established
    assert surface.verdict == "NOT VERIFIED"
    assert surface.coverage_verdict is CoverageVerdict.NOT_COVERED
    assert not surface.erased
    assert not report.erased


def test_an_inconclusive_scan_on_one_surface_does_not_abort_the_run() -> None:
    # The vector scan degrades to "absence not established" on its own; every
    # other surface's adapter RAISES when it cannot trust its listing, and nothing
    # caught it - so one inconclusive trace, memory, eval-set or search scan
    # aborted the whole erasure run instead of marking that one surface uncovered.
    from sectum_ai.spec import AdapterError

    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id

    class _UntrustworthyObservability(FakeObservability):
        def search_traces(self, tenant: UUID, marker: str) -> list[object]:  # type: ignore[override]
            raise AdapterError("the listing was capped, so a miss is not absence")

    report = ErasureProbe(
        substrate,
        vector=_seeded_store(substrate, soft_delete=False),
        observability=_UntrustworthyObservability(),
    ).run(target)
    tracing = next(s for s in report.surfaces if s.surface is Surface.TRACING)
    assert tracing.unverifiable_after > 0
    assert tracing.coverage_verdict is CoverageVerdict.NOT_COVERED
    assert not tracing.erased
    # The other surface was still scanned, and the run as a whole is not ERASED.
    vector = next(s for s in report.surfaces if s.surface is Surface.VECTOR_DB)
    assert vector.erased
    assert not report.erased


class _CaseSensitivePurgeSearchIndex(FakeSearchIndex):
    """A search index whose purge matches the canary's literal spelling only.

    The ordinary partial purge: the backend's delete walks the documents that
    match the canary as written, and a derived copy that re-cased it survives.
    That is the hiding place Class 11 exists to find, and the scan has to see it.
    """

    def __init__(self, canaries: tuple[str, ...]) -> None:
        super().__init__(soft_delete=False)
        self._canaries = canaries

    def delete(self, tenant: UUID) -> None:
        self._documents[tenant] = [
            text
            for text in self._documents.get(tenant, [])
            if not any(canary in text for canary in self._canaries)
        ]


def test_erasure_counts_a_marker_the_index_re_cased_as_residual() -> None:
    # A raw case-sensitive `in` here signed ERASURE VERIFIED over a canary the
    # tenant's own search index still returns: the pre-scan saw the canonical
    # copy, the purge removed only that one, and the surviving re-cased copy
    # was invisible to the post-scan. The A3 sibling on the same bytes called
    # it RESIDUAL - two predicates, one question.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    canaries = tuple(
        marker.plaintext
        for marker in substrate.manifest.markers
        if marker.marker_type is MarkerType.HARD_CANARY
    )
    search = _CaseSensitivePurgeSearchIndex(canaries)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            search.index(
                marker.owner_tenant_id, f"search index entry mentioning {marker.plaintext}"
            )
            search.index(
                marker.owner_tenant_id,
                f"derived copy mentioning {marker.plaintext.lower()}",
            )
    report = ErasureProbe(
        substrate, vector=_seeded_store(substrate, soft_delete=False), search_index=search
    ).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert surfaces[Surface.SEARCH_INDEX].markers_before > 0
    assert surfaces[Surface.SEARCH_INDEX].residual_after > 0
    assert report.coverage()[Surface.SEARCH_INDEX] is CoverageVerdict.RESIDUAL
    assert not report.erased
    assert any(finding.surface is Surface.SEARCH_INDEX for finding in report.findings)


class _CaseSensitivePurgeObservability(FakeObservability):
    """A trace backend whose purge matches the canary's literal spelling only."""

    def __init__(self, canaries: tuple[str, ...]) -> None:
        super().__init__(soft_delete=False)
        self._canaries = canaries

    def delete(self, tenant: UUID) -> None:
        self._traces[tenant] = [
            row
            for row in self._traces.get(tenant, [])
            if not any(canary in row[2] for canary in self._canaries)
        ]


def test_erasure_counts_a_marker_the_trace_backend_re_cased_as_residual() -> None:
    # The tracing family was the one the shared-predicate commit skipped, and
    # `_scan_observability` applies no predicate of its own - it takes the
    # truthiness of the adapter's already-filtered list, so the adapter's raw `in`
    # WAS the residue test. Same bytes and same partial purge as the search-index
    # case above, opposite verdicts: the wedge SKU signed ERASURE VERIFIED for a
    # surface the backend still returns the canary from.
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    canaries = tuple(
        marker.plaintext
        for marker in substrate.manifest.markers
        if marker.marker_type is MarkerType.HARD_CANARY
    )
    obs = _CaseSensitivePurgeObservability(canaries)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            obs.record(
                marker.owner_tenant_id, "sectum-ai-erasure", f"trace recording {marker.plaintext}"
            )
            obs.record(
                marker.owner_tenant_id,
                "sectum-ai-erasure",
                f"normalized trace copy {marker.plaintext.lower()}",
            )
    report = ErasureProbe(
        substrate, vector=_seeded_store(substrate, soft_delete=False), observability=obs
    ).run(target)
    surfaces = {surface.surface: surface for surface in report.surfaces}
    assert surfaces[Surface.TRACING].markers_before > 0
    assert surfaces[Surface.TRACING].residual_after > 0
    assert report.coverage()[Surface.TRACING] is CoverageVerdict.RESIDUAL
    assert not report.erased
