"""Tests for Class 11 - the GDPR Article 17 erasure-verification wedge."""

from sectum.adapters import FakeObservability, FakeVectorStore
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


def test_erasure_is_verified_when_the_store_hard_deletes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    target = substrate.tenants[0].tenant_id
    store = _seeded_store(substrate, soft_delete=False)
    report = ErasureProbe(substrate, vector=store).run(target)
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
