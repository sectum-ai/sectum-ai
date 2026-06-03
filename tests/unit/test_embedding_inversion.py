"""Tests for Class 6 - the embedding inversion probe."""

from sectum_ai.adapters import FakeVectorStore
from sectum_ai.probes import EmbeddingInversionProbe, confirmed_findings
from sectum_ai.runner import Runner
from sectum_ai.spec import MarkerType, Substrate
from sectum_ai.substrate import build_substrate, default_scenario


def _seeded_store(substrate: Substrate, *, shared_index: bool) -> FakeVectorStore:
    store = FakeVectorStore(shared_index=shared_index)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        store.upsert(tenant.tenant_id, documents)
    return store


def test_shared_index_reconstructs_a_foreign_entity_canary() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=True)
    findings = confirmed_findings(Runner(substrate, vector=store).run(EmbeddingInversionProbe()))
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)


def test_isolated_index_yields_no_reconstruction() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=False)
    findings = Runner(substrate, vector=store).run(EmbeddingInversionProbe())
    assert confirmed_findings(findings) == []


def test_probe_plans_fragment_queries_for_foreign_entity_canaries() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = EmbeddingInversionProbe().plan(substrate)
    assert steps
    assert all(step.action == "vector.query" for step in steps)
    # Each query is a *partial fragment* of an entity canary - a strict prefix that
    # drops the canary's unique trailing segment, modelling reconstruction from
    # partial knowledge. A regression to querying the full plaintext (no inversion)
    # would make the query equal to a whole canary and fail this.
    entity_plaintexts = [
        marker.plaintext
        for marker in substrate.manifest.markers
        if marker.marker_type is MarkerType.ENTITY_CANARY
    ]
    for step in steps:
        query = step.payload["query"]
        assert any(full.startswith(f"{query}-") for full in entity_plaintexts), query
