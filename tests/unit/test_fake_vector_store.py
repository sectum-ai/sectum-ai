"""The built-in fake vector store models a store, not an append log."""

from uuid import UUID

from sectum_ai.adapters import FakeVectorStore
from sectum_ai.spec import CorpusDocument

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


def _doc(tenant: UUID, doc_id: str, content: str) -> CorpusDocument:
    return CorpusDocument(
        doc_id=doc_id, tenant_id=tenant, doc_type="note", title=content, content=content
    )


def test_an_upsert_replaces_the_document_with_the_same_id() -> None:
    # Appending duplicated hits on a re-upsert and left fetch returning the stale
    # copy, inflating Class 3 re-upsert counts.
    store = FakeVectorStore()
    store.upsert(_TENANT_A, [_doc(_TENANT_A, "d-1", "canary alpha old")])
    store.upsert(_TENANT_A, [_doc(_TENANT_A, "d-1", "canary alpha new")])
    hits = store.query(_TENANT_A, "canary alpha", k=5)
    assert [hit.doc_id for hit in hits] == ["d-1"]
    fetched = store.fetch(_TENANT_A, "d-1")
    assert fetched is not None and fetched.content == "canary alpha new"


def test_a_weak_embedding_model_never_drops_the_tenants_own_hit() -> None:
    # The top-k cut ran before the recall filter, so a foreign hit that the
    # filter then removed could push the tenant's own document past k.
    store = FakeVectorStore(shared_index=True, recall=0.0)
    store.upsert(_TENANT_B, [_doc(_TENANT_B, f"b-{i}", "canary alpha") for i in range(5)])
    store.upsert(_TENANT_A, [_doc(_TENANT_A, "z-own", "canary alpha")])
    hits = store.query(_TENANT_A, "canary alpha", k=5)
    assert [hit.tenant_id for hit in hits] == [_TENANT_A]
    assert hits[0].doc_id == "z-own"
