"""Tests for Class 1 - the direct tenant-boundary-fetch probe."""

from sectum.adapters import FakeVectorStore
from sectum.probes import TenantBoundaryProbe, confirmed_findings
from sectum.runner import Runner
from sectum.spec import Substrate
from sectum.substrate import build_substrate, default_scenario


def _seeded_store(substrate: Substrate, *, shared_index: bool) -> FakeVectorStore:
    store = FakeVectorStore(shared_index=shared_index)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        store.upsert(tenant.tenant_id, documents)
    return store


def test_shared_index_leaks_across_the_tenant_boundary() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=True)
    findings = confirmed_findings(Runner(substrate, vector=store).run(TenantBoundaryProbe()))
    assert findings
    assert all(finding.owner_tenant_id != finding.observed_in_tenant_id for finding in findings)


def test_isolated_index_has_no_tenant_boundary_leak() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=False)
    findings = Runner(substrate, vector=store).run(TenantBoundaryProbe())
    assert confirmed_findings(findings) == []


def test_probe_plans_only_cross_tenant_fetch_steps() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = TenantBoundaryProbe().plan(substrate)
    assert steps
    tenant_ids = {tenant.tenant_id for tenant in substrate.tenants}
    for step in steps:
        assert step.action == "vector.fetch"
        assert step.actor_tenant_id in tenant_ids
        assert "doc_id" in step.payload
