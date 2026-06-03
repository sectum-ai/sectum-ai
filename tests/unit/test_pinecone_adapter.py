"""Mock-backed contract tests for the live Pinecone adapter.

Pinecone is a hosted service with no local backend, so the adapter's logic is
verified here against an in-memory stand-in for a Pinecone index (the
engineering spec, section 13: "Pinecone via mock + opt-in live"). The live path
is exercised separately by ``tests/integration/test_pinecone.py``.
"""

import hashlib
import re
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sectum_ai.adapters.base import Capability, VectorStoreAdapter
from sectum_ai.adapters.vector.pinecone import PineconeVectorStore
from sectum_ai.spec import CorpusDocument

_DIM = 64
_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)
_USER_A = UUID(int=0xA1)
_USER_B = UUID(int=0xB2)


def _embed(text: str) -> list[float]:
    """A deterministic hashing-trick embedding (offline, no model)."""
    vector = [0.0] * _DIM
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % _DIM
        vector[index] += 1.0
    return vector


def _documents(tenant: UUID, prefix: str, word: str) -> list[CorpusDocument]:
    return [
        CorpusDocument(
            doc_id=f"{prefix}-{index}",
            tenant_id=tenant,
            doc_type="note",
            title=f"{word} note {index}",
            content=f"a document about {word} item {index}",
        )
        for index in range(3)
    ]


class _FakeIndex:
    """A minimal in-memory stand-in for a namespaced Pinecone index."""

    def __init__(self) -> None:
        self._namespaces: dict[str, dict[str, dict[str, Any]]] = {}

    def upsert(self, *, vectors: list[dict[str, Any]], namespace: str) -> None:
        store = self._namespaces.setdefault(namespace, {})
        for vector in vectors:
            store[vector["id"]] = {
                "values": list(vector["values"]),
                "metadata": dict(vector["metadata"]),
            }

    def query(
        self,
        *,
        vector: list[float],
        top_k: int,
        namespace: str,
        include_metadata: bool = True,
        filter: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        store = self._namespaces.get(namespace, {})
        records = list(store.items())
        if filter is not None:
            # A minimal metadata $in filter, enough to model owner_user scoping.
            allowed = filter["owner_user"]["$in"]
            records = [
                (doc_id, record)
                for doc_id, record in records
                if record["metadata"].get("owner_user") in allowed
            ]
        scored = sorted(
            ((self._dot(vector, record["values"]), doc_id, record) for doc_id, record in records),
            key=lambda item: item[0],
            reverse=True,
        )
        matches = [
            SimpleNamespace(id=doc_id, score=score, metadata=record["metadata"])
            for score, doc_id, record in scored[:top_k]
        ]
        return SimpleNamespace(matches=matches)

    def fetch(self, *, ids: list[str], namespace: str) -> SimpleNamespace:
        store = self._namespaces.get(namespace, {})
        vectors = {
            doc_id: SimpleNamespace(
                id=doc_id, values=store[doc_id]["values"], metadata=store[doc_id]["metadata"]
            )
            for doc_id in ids
            if doc_id in store
        }
        return SimpleNamespace(vectors=vectors)

    def delete(self, *, delete_all: bool, namespace: str) -> None:
        self._namespaces.pop(namespace, None)

    def describe_index_stats(self) -> SimpleNamespace:
        return SimpleNamespace(
            namespaces={
                namespace: SimpleNamespace(vector_count=len(records))
                for namespace, records in self._namespaces.items()
            }
        )

    @staticmethod
    def _dot(left: list[float], right: list[float]) -> float:
        return sum(x * y for x, y in zip(left, right, strict=False))


def _user_documents(tenant: UUID, user: UUID, prefix: str, word: str) -> list[CorpusDocument]:
    return [
        CorpusDocument(
            doc_id=f"{prefix}-{index}",
            tenant_id=tenant,
            doc_type="note",
            title=f"{word} note {index}",
            content=f"a document about {word} item {index}",
            owner_user_id=user,
        )
        for index in range(2)
    ]


def _store() -> PineconeVectorStore:
    return PineconeVectorStore(_FakeIndex(), _embed)


def test_pinecone_adapter_conforms_to_the_family_and_reports_isolation() -> None:
    store = _store()
    assert isinstance(store, VectorStoreAdapter)
    assert store.supports(Capability.PER_TENANT_NAMESPACE)
    assert not store.supports(Capability.SHARED_INDEX)


def test_pinecone_round_trips_and_isolates_tenants_by_namespace() -> None:
    store = _store()
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    store.upsert(_TENANT_B, _documents(_TENANT_B, "b", "alpha"))
    hits = store.query(_TENANT_A, "alpha", k=10)
    assert {hit.doc_id for hit in hits} == {"a-0", "a-1", "a-2"}
    assert all(hit.tenant_id == _TENANT_A for hit in hits)


def test_pinecone_fetch_by_id_is_namespace_scoped() -> None:
    store = _store()
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    hit = store.fetch(_TENANT_A, "a-1")
    assert hit is not None
    assert hit.doc_id == "a-1"
    assert store.fetch(_TENANT_A, "missing") is None
    # another tenant's namespace does not resolve tenant A's document id
    assert store.fetch(_TENANT_B, "a-1") is None


def test_pinecone_delete_and_list_namespaces() -> None:
    store = _store()
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    store.upsert(_TENANT_B, _documents(_TENANT_B, "b", "alpha"))
    assert store.list_namespaces() == sorted([_TENANT_A.hex, _TENANT_B.hex])
    store.delete(_TENANT_A)
    assert store.query(_TENANT_A, "alpha", k=10) == []
    assert store.list_namespaces() == [_TENANT_B.hex]


def test_pinecone_query_tolerates_a_vector_without_metadata() -> None:
    """A Pinecone vector upserted without metadata has no metadata attribute
    (the SDK raises AttributeError); the adapter must read it without crashing,
    falling back to the vector id and empty content."""

    class _Index:
        def query(
            self,
            *,
            vector: list[float],
            top_k: int,
            namespace: str,
            include_metadata: bool = True,
        ) -> SimpleNamespace:
            return SimpleNamespace(matches=[SimpleNamespace(id="orphan-1", score=0.9)])

    hits = PineconeVectorStore(_Index(), _embed).query(_TENANT_A, "anything", k=5)
    assert len(hits) == 1
    assert hits[0].doc_id == "orphan-1"
    assert hits[0].content == ""


def test_pinecone_user_scoped_isolates_users() -> None:
    store = PineconeVectorStore(_FakeIndex(), _embed, user_scoped=True)
    assert store.supports(Capability.USER_SCOPED)
    store.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_A, "ua", "alpha"))
    store.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_B, "ub", "alpha"))
    # _documents have no owner, so they land under the tenant-level sentinel
    store.upsert(_TENANT_A, _documents(_TENANT_A, "shared", "alpha"))
    doc_ids = {hit.doc_id for hit in store.query(_TENANT_A, "alpha", k=10, user=_USER_A)}
    # user A sees its own documents and the tenant-shared ones, never user B's
    assert any(d.startswith("ua-") for d in doc_ids)
    assert any(d.startswith("shared-") for d in doc_ids)
    assert not any(d.startswith("ub-") for d in doc_ids)
    # fetch: own and tenant-shared resolve; a sibling user's document is denied
    assert store.fetch(_TENANT_A, "ua-0", user=_USER_A) is not None
    assert store.fetch(_TENANT_A, "shared-0", user=_USER_A) is not None
    assert store.fetch(_TENANT_A, "ub-0", user=_USER_A) is None


def test_pinecone_tenant_only_store_leaks_across_users() -> None:
    # a store that scopes by namespace alone ignores the user, so a sibling user
    # reads another user's document - the cross-user leak (ADR-0006)
    store = PineconeVectorStore(_FakeIndex(), _embed)
    assert not store.supports(Capability.USER_SCOPED)
    store.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_B, "ub", "alpha"))
    assert store.fetch(_TENANT_A, "ub-0", user=_USER_A) is not None
