"""Tests for Class 2 - the flagship organic entity-bleed RAG probe."""

from sectum.adapters import FakeVectorStore
from sectum.probes import RagEntityBleedProbe, confirmed_findings
from sectum.runner import Runner, retrieval_pivot_rate
from sectum.spec import Substrate
from sectum.substrate import build_substrate, default_scenario


def _seeded_store(substrate: Substrate, *, shared_index: bool) -> FakeVectorStore:
    store = FakeVectorStore(shared_index=shared_index)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        store.upsert(tenant.tenant_id, documents)
    return store


def test_benign_queries_pivot_across_tenants_on_a_shared_index() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=True)
    results = Runner(substrate, vector=store).run_per_step(RagEntityBleedProbe())
    assert retrieval_pivot_rate(results) > 0.0
    confirmed = [finding for _, findings in results for finding in confirmed_findings(findings)]
    assert confirmed
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in confirmed)


def test_isolated_index_has_no_entity_bleed() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=False)
    results = Runner(substrate, vector=store).run_per_step(RagEntityBleedProbe())
    assert retrieval_pivot_rate(results) == 0.0


def test_probe_plans_one_benign_query_per_shared_entity_and_tenant() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = RagEntityBleedProbe().plan(substrate)
    expected = len(substrate.scenario.shared_entities) * len(substrate.tenants)
    assert len(steps) == expected
    assert all(step.action == "vector.query" for step in steps)
