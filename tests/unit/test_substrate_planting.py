"""embedding_ref population and multi-field marker planting (the spec, section 6.3)."""

import hashlib

from sectum.adapters.fakes import FakeVectorStore
from sectum.spec import MarkerType, Substrate
from sectum.substrate import build_substrate, default_scenario


def _substrate(
    seed: int = 99, embedding_models: tuple[str, ...] = ("fake-deterministic",)
) -> Substrate:
    return build_substrate(default_scenario(seed=seed, embedding_models=embedding_models))


def test_only_entity_markers_carry_an_embedding_ref() -> None:
    # ENTITY canaries are the only type matched semantically, so they are the only
    # type with a stored embedding to reference (HARD/SECRET are matched exactly).
    substrate = _substrate()
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.ENTITY_CANARY:
            assert marker.embedding_ref is not None
        else:
            assert marker.embedding_ref is None


def test_embedding_ref_names_the_model_and_addresses_the_content() -> None:
    substrate = _substrate()
    for marker in substrate.manifest.markers:
        if marker.marker_type is not MarkerType.ENTITY_CANARY:
            continue
        assert marker.embedding_ref is not None
        model, _, digest = marker.embedding_ref.partition("/")
        assert model == "fake-deterministic"
        assert digest == hashlib.sha256(marker.plaintext.encode("utf-8")).hexdigest()[:16]


def test_embedding_ref_is_model_scoped() -> None:
    # The same entity addresses a distinct vector under a different model, so the
    # manifest records which model the semantic-detection vectors were computed
    # under - a provable test condition in the evidence chain (spec section 8).
    strong = _substrate(embedding_models=("st:all-mpnet-base-v2",))
    weak = _substrate(embedding_models=("hash-256",))
    strong_refs = {m.marker_id: m.embedding_ref for m in strong.manifest.markers if m.embedding_ref}
    weak_refs = {m.marker_id: m.embedding_ref for m in weak.manifest.markers if m.embedding_ref}
    assert strong_refs and strong_refs.keys() == weak_refs.keys()
    for marker_id, ref in strong_refs.items():
        assert ref.startswith("st:all-mpnet-base-v2/")
        assert ref != weak_refs[marker_id]


def test_every_marker_is_planted_in_body_title_and_metadata() -> None:
    substrate = _substrate()
    documents = {doc.doc_id: doc for doc in substrate.documents}
    for marker in substrate.manifest.markers:
        fields = {location.field for location in marker.planted_locations}
        assert fields == {"body", "title", "metadata"}
        for location in marker.planted_locations:
            document = documents[location.doc_id]
            present = {
                "body": marker.plaintext in document.content,
                "title": marker.plaintext in document.title,
                "metadata": marker.plaintext in " ".join(document.metadata.values()),
            }
            assert present[location.field], f"{marker.marker_id} absent from {location.field}"


def test_metadata_is_searched_by_the_vector_store() -> None:
    # A tenant's display name appears only in document metadata - never in a title
    # or body - so a query that retrieves its documents proves the store searches
    # metadata, the field multi-field planting depends on (spec section 6.3).
    substrate = _substrate()
    store = FakeVectorStore(shared_index=True)
    for tenant in substrate.tenants:
        store.upsert(
            tenant.tenant_id,
            [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id],
        )
    acme = substrate.tenants[0]
    assert all(acme.display_name not in doc.title for doc in substrate.documents)
    assert all(acme.display_name not in doc.content for doc in substrate.documents)
    # Query from another tenant over the shared index; only Acme's metadata matches.
    hits = store.query(substrate.tenants[1].tenant_id, acme.display_name, k=10)
    assert hits, "a metadata-only term returned no hits"
    assert all(hit.tenant_id == acme.tenant_id for hit in hits)
