"""A Weaviate read must not create the tenant's collection.

`_collection` creates on first use, which is right for a write and wrong for a
read. A post-erasure re-scan recreated the (empty) collection it was checking,
so `list_namespaces` showed the purged tenant again and the Class 11
attestation described a namespace its own scan had just made -- spec section 7's
first hiding place is literally "orphaned collections". Worse, a cross-tenant
Class 1 fetch did the same for a tenant the operator never provisioned: a read
that WRITES to the customer's production store.

Chroma, Qdrant, Milvus and Azure AI Search all guard their reads; Weaviate was
the one that did not. The adapter imports `weaviate` in `__init__`, so these
build it without running the constructor and drive a stub client.
"""

from typing import Any
from uuid import UUID

from sectum_ai.adapters.vector.weaviate import WeaviateVectorStore

_TENANT = UUID(int=0xA)


class _StubCollections:
    def __init__(self) -> None:
        self.names: set[str] = set()
        self.created: list[str] = []

    def exists(self, name: str) -> bool:
        return name in self.names

    def create(self, name: str, **_: Any) -> Any:
        self.created.append(name)
        self.names.add(name)
        return _StubCollection()

    def get(self, name: str) -> Any:
        return _StubCollection()

    def list_all(self) -> list[str]:
        return sorted(self.names)


class _StubCollection:
    def __init__(self) -> None:
        self.query = self

    def near_vector(self, *_: Any, **__: Any) -> Any:
        raise AssertionError("a read on an absent collection must not reach the server")

    def fetch_object_by_id(self, *_: Any, **__: Any) -> Any:
        raise AssertionError("a read on an absent collection must not reach the server")


def _store() -> tuple[WeaviateVectorStore, _StubCollections]:
    collections = _StubCollections()
    store = object.__new__(WeaviateVectorStore)
    store._client = type("_C", (), {"collections": collections})()
    store._prefix = "Sectum"
    store._user_scoped = False
    store._embed = lambda text: [0.0, 1.0]
    return store, collections


def test_a_query_on_an_absent_tenant_creates_nothing() -> None:
    store, collections = _store()
    assert store.query(_TENANT, "anything") == []
    assert collections.created == []
    assert store.list_namespaces() == []


def test_a_fetch_on_an_absent_tenant_creates_nothing() -> None:
    store, collections = _store()
    assert store.fetch(_TENANT, "doc-1") is None
    assert collections.created == []
    assert store.list_namespaces() == []
