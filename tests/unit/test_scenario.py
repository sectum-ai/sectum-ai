"""The default four-tenant scenario generates with shared organic entities."""

from uuid import UUID

import pytest

from sectum_ai.spec import ConfigError
from sectum_ai.substrate import build_substrate, default_scenario

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


def test_corpus_smaller_than_the_marker_count_is_rejected() -> None:
    """A corpus too small to give every marker its own pivot document is rejected."""
    with pytest.raises(ConfigError, match="markers-per-tenant"):
        build_substrate(default_scenario(seed=1, corpus_size=3))


def test_a_corpus_one_short_of_the_marker_count_is_rejected() -> None:
    """The guard is inclusive at the boundary: corpus_size == markers - 1 is rejected.

    The guard must fire whenever a marker would not get its own pivot document, and one
    short of the marker count is the first size that collides two markers onto one document
    (dropping a canary). The far-below size above does not exercise this edge - a guard
    weakened to ``size < markers - 1`` still rejects corpus_size=3 but would silently admit
    this one. The marker count is measured rather than hardcoded so the boundary tracks it.
    """
    healthy = build_substrate(default_scenario(seed=1, corpus_size=24))
    tenant_id = healthy.tenants[0].tenant_id
    markers_per_tenant = sum(1 for m in healthy.manifest.markers if m.owner_tenant_id == tenant_id)
    with pytest.raises(ConfigError, match="markers-per-tenant"):
        build_substrate(default_scenario(seed=1, corpus_size=markers_per_tenant - 1))


def test_a_corpus_exactly_the_marker_count_is_accepted() -> None:
    """The guard is inclusive at the accept boundary: corpus_size == markers succeeds.

    corpus_size must be at least the markers-per-tenant count, so exactly the count is the
    minimal valid corpus - every marker still gets its own pivot document. The reject sibling
    above pins one short; this pins the exact-equality accept point, which a guard tightened to
    ``size <= markers`` would wrongly refuse with a self-contradictory error. The count is
    measured, not hardcoded.
    """
    healthy = build_substrate(default_scenario(seed=1, corpus_size=24))
    tenant_id = healthy.tenants[0].tenant_id
    markers_per_tenant = sum(1 for m in healthy.manifest.markers if m.owner_tenant_id == tenant_id)
    minimal = build_substrate(default_scenario(seed=1, corpus_size=markers_per_tenant))
    assert all(marker.planted_locations for marker in minimal.manifest.markers)
