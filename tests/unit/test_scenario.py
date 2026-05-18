"""The default four-tenant scenario generates with shared organic entities."""

from uuid import UUID

from sectum.substrate import build_substrate, default_scenario

_EXPECTED_TENANTS = (
    "Acme Robotics",
    "Globex Logistics",
    "Initech Financial",
    "Hooli Health",
)


def test_default_scenario_has_the_four_named_tenants() -> None:
    scenario = default_scenario(seed=1)
    assert tuple(tenant.display_name for tenant in scenario.tenants) == _EXPECTED_TENANTS


def test_built_substrate_has_four_tenants_each_with_a_corpus() -> None:
    substrate = build_substrate(default_scenario(seed=1, corpus_size=24))
    assert len(substrate.tenants) == 4
    assert len(substrate.documents) == 4 * 24
    for tenant in substrate.tenants:
        docs = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        assert len(docs) == 24


def test_shared_entities_appear_in_every_tenant_corpus() -> None:
    substrate = build_substrate(default_scenario(seed=1))
    shared_values = [entity.value for entity in substrate.scenario.shared_entities]
    corpus_by_tenant: dict[UUID, list[str]] = {}
    for doc in substrate.documents:
        corpus_by_tenant.setdefault(doc.tenant_id, []).append(f"{doc.title}\n{doc.content}")
    for value in shared_values:
        tenants_with_value = sum(
            1 for blobs in corpus_by_tenant.values() if any(value in blob for blob in blobs)
        )
        assert tenants_with_value == 4, f"shared entity {value!r} missing from a tenant corpus"


def test_every_marker_rides_in_a_shared_entity_document() -> None:
    """The flagship Class 2 pivot depends on each marker being co-located with a
    shared organic entity in retrievable text; lock that property here."""
    substrate = build_substrate(default_scenario(seed=1))
    documents = {doc.doc_id: doc for doc in substrate.documents}
    shared_values = [entity.value for entity in substrate.scenario.shared_entities]
    for marker in substrate.manifest.markers:
        assert marker.planted_locations, f"{marker.marker_id} was never planted"
        for location in marker.planted_locations:
            document = documents[location.doc_id]
            assert marker.plaintext in document.content
            assert any(value in document.content for value in shared_values)
