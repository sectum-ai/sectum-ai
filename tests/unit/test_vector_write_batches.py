"""Hosted stores' corpus writes stay within each store's per-request cap.

At 384 dimensions (all-MiniLM-L6-v2's) a default 500-document tenant corpus
computes to about 4 MB, twice Pinecone's 2 MB upsert cap, in one request; the
64-dimension hashing default fit. Qdrant and Azure split only past caps a corpus
reaches at larger dimensions, so their tests lower the cap to exercise the split.
"""

import hashlib
import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from sectum_ai.adapters.vector._batch import request_batches
from sectum_ai.spec import CorpusDocument

_TENANT = UUID(int=0xA)
_DIM = 384


def _embed(text: str) -> list[float]:
    """Full-precision floats, as a real model returns them."""
    seed = hashlib.sha256(text.encode()).digest()
    return [((seed[i % 32] + i) % 251) / 251.0 + 1e-9 for i in range(_DIM)]


def _corpus(size: int = 500) -> list[CorpusDocument]:
    return [
        CorpusDocument(
            doc_id=f"doc-{index}",
            tenant_id=_TENANT,
            doc_type="note",
            title=f"note {index}",
            content=f"a document about item {index} " * 8,
        )
        for index in range(size)
    ]


def test_batches_split_on_bytes_and_on_count_and_keep_order() -> None:
    records = list(range(10))
    assert [list(b) for b in request_batches(records, max_bytes=3, size=lambda _r: 1)] == [
        [0, 1, 2],
        [3, 4, 5],
        [6, 7, 8],
        [9],
    ]
    by_count = request_batches(records, max_bytes=100, size=lambda _r: 1, max_records=4)
    assert [list(b) for b in by_count] == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9]]
    # a record over the byte cap on its own still goes, alone
    sizes = {0: 1, 1: 50, 2: 1}
    lone = request_batches([0, 1, 2], max_bytes=10, size=sizes.__getitem__)
    assert [list(b) for b in lone] == [[0], [1], [2]]
    assert list(request_batches([], max_bytes=10, size=lambda _r: 1)) == []


def test_pinecone_upserts_a_real_model_corpus_in_requests_under_its_cap() -> None:
    from sectum_ai.adapters.vector.pinecone import PineconeVectorStore

    class _Index:
        def __init__(self) -> None:
            self.requests: list[list[dict[str, Any]]] = []
            self.ids: set[str] = set()

        def upsert(self, *, vectors: list[dict[str, Any]], namespace: str) -> None:
            self.requests.append(vectors)
            self.ids.update(vector["id"] for vector in vectors)

        def fetch(self, *, ids: list[str], namespace: str) -> SimpleNamespace:
            return SimpleNamespace(vectors={i: object() for i in ids if i in self.ids})

    index = _Index()
    PineconeVectorStore(index, _embed).upsert(_TENANT, _corpus())
    assert len(index.requests) > 1
    assert all(len(json.dumps(request)) < 2_000_000 for request in index.requests)
    assert all(len(request) <= 1000 for request in index.requests)
    assert [v["id"] for r in index.requests for v in r] == [f"doc-{i}" for i in range(500)]


def test_qdrant_splits_its_upsert_at_the_byte_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("qdrant_client")
    from qdrant_client import QdrantClient

    from sectum_ai.adapters.vector import qdrant

    monkeypatch.setattr(qdrant, "_MAX_UPSERT_BYTES", 1_000_000)
    client = QdrantClient(":memory:")
    requests: list[list[Any]] = []
    real_upsert = client.upsert

    def upsert(**kwargs: Any) -> Any:
        requests.append(kwargs["points"])
        return real_upsert(**kwargs)

    monkeypatch.setattr(client, "upsert", upsert)
    monkeypatch.setattr("qdrant_client.QdrantClient", lambda **_kwargs: client)
    store = qdrant.QdrantVectorStore(_embed, dim=_DIM)
    store.upsert(_TENANT, _corpus())
    assert len(requests) > 1
    assert all(sum(len(p.model_dump_json()) for p in r) <= 1_000_000 for r in requests)
    assert sum(len(r) for r in requests) == 500
    assert {hit.doc_id for hit in store.query(_TENANT, "item 7", k=500)} == {
        f"doc-{i}" for i in range(500)
    }


@pytest.mark.parametrize("max_bytes", [1_000_000, 10**12])
def test_azure_splits_its_upload_at_the_byte_and_document_caps(
    monkeypatch: pytest.MonkeyPatch, max_bytes: int
) -> None:
    from sectum_ai.adapters.vector import azure_search

    monkeypatch.setattr(azure_search, "_MAX_UPLOAD_BYTES", max_bytes)
    store = object.__new__(azure_search.AzureSearchVectorStore)
    store._embed, store._dim, store._user_scoped = _embed, _DIM, False
    requests: list[list[dict[str, Any]]] = []
    client = SimpleNamespace(upload_documents=lambda documents: requests.append(documents))
    monkeypatch.setattr(store, "_ensure_index", lambda _tenant: "index")
    monkeypatch.setattr(store, "_client", lambda _index: client)
    monkeypatch.setattr(store, "_document_present", lambda _client, _key: True)
    store.upsert(_TENANT, _corpus(1200))
    assert len(requests) > 1
    assert all(sum(len(json.dumps(d)) for d in request) <= max_bytes for request in requests)
    assert all(len(request) <= 1000 for request in requests)
    assert [d["doc_id"] for r in requests for d in r] == [f"doc-{i}" for i in range(1200)]
