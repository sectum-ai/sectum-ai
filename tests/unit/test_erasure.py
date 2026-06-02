"""Tests for Class 11 - the GDPR Article 17 erasure-verification wedge."""

from sectum.adapters import (
    FakeBackup,
    FakeCache,
    FakeEvalSet,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeSearchIndex,
    FakeVectorStore,
)
from sectum.adapters.base import ObservabilityAdapter
from sectum.probes import ErasureProbe
from sectum.spec import MarkerType, Substrate, Surface
from sectum.substrate import build_substrate, default_scenario


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
                "sectum-erasure",
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
                f"sectum-erasure-{marker.marker_id}",
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

    from sectum.adapters.base import ObservabilityAdapter, TraceHit
    from sectum.spec import ErasureUnsupported

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

    from sectum.adapters.base import TraceHit
    from sectum.spec import ErasureUnsupported

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
    # control (confirmed-count, sectum diff/baseline gates) never treats a
    # no-per-tenant-erasure-API backend as a confirmed finding (spec §7 #8).
    from sectum.spec import FindingStatus

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
    # `sectum diff` (no newly-confirmed finding, no confirmed-count bump).
    from sectum.baseline import diff_findings
    from sectum.probes import confirmed_findings

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
