"""Tests for Class 10 - the IKEA-style implicit benign extraction probe."""

from sectum_ai.adapters import FakeVectorStore
from sectum_ai.probes import IkeaExtractionProbe, confirmed_findings
from sectum_ai.runner import Runner
from sectum_ai.spec import Substrate
from sectum_ai.substrate import build_substrate, default_scenario


def _seeded_store(substrate: Substrate, *, shared_index: bool) -> FakeVectorStore:
    store = FakeVectorStore(shared_index=shared_index)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        store.upsert(tenant.tenant_id, documents)
    return store


def test_multi_turn_benign_queries_extract_foreign_content() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=True)
    findings = confirmed_findings(Runner(substrate, vector=store).run(IkeaExtractionProbe()))
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)


def test_isolated_index_has_no_benign_extraction() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=False)
    findings = Runner(substrate, vector=store).run(IkeaExtractionProbe())
    assert confirmed_findings(findings) == []


def test_probe_plans_a_multi_turn_sequence() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = IkeaExtractionProbe().plan(substrate)
    assert steps
    assert all(step.action == "vector.query" for step in steps)
    expected = 3 * len(substrate.scenario.shared_entities) * len(substrate.tenants)
    assert len(steps) == expected
