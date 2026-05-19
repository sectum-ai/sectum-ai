"""Tests for Class 3 - the adversarial RAG poisoning probe."""

from sectum.adapters import FakeVectorStore
from sectum.probes import RagPoisoningProbe, confirmed_findings
from sectum.runner import Runner
from sectum.spec import Substrate
from sectum.substrate import build_substrate, default_scenario


def _seeded_store(substrate: Substrate, *, shared_index: bool) -> FakeVectorStore:
    store = FakeVectorStore(shared_index=shared_index)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        store.upsert(tenant.tenant_id, documents)
    return store


def test_poison_document_pivots_across_a_shared_index() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=True)
    findings = confirmed_findings(Runner(substrate, vector=store).run(RagPoisoningProbe()))
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)


def test_poison_document_stays_within_an_isolated_index() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=False)
    findings = Runner(substrate, vector=store).run(RagPoisoningProbe())
    assert confirmed_findings(findings) == []


def test_probe_plans_upserts_then_queries() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = RagPoisoningProbe().plan(substrate)
    assert steps
    assert {step.action for step in steps} == {"vector.upsert", "vector.query"}
