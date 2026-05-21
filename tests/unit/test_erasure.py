"""Tests for Class 11 - the GDPR Article 17 erasure-verification wedge."""

from sectum.adapters import (
    FakeCache,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeVectorStore,
)
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
