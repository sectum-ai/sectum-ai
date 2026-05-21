"""Opt-in live integration test for the Pinecone vector adapter.

Pinecone is a hosted service, so this test is skipped unless ``PINECONE_API_KEY``
and ``PINECONE_INDEX`` are set (the engineering spec, section 13: opt-in live).
The target index must exist with dimension 64 to match the offline embedder
below. Enable it with ``pip install sectum-ai-adapters[pinecone]`` and the env
vars; the adapter logic itself is covered offline by
``tests/unit/test_pinecone_adapter.py``.
"""

import hashlib
import os
import re
import time
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum.adapters.vector.pinecone import PineconeVectorStore
from sectum.spec import CorpusDocument

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("PINECONE_API_KEY") and os.environ.get("PINECONE_INDEX")),
        reason="set PINECONE_API_KEY and PINECONE_INDEX to run the live Pinecone test",
    ),
]

_DIM = 64
_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


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


@pytest.fixture
def store() -> Iterator[PineconeVectorStore]:
    instance = PineconeVectorStore.connect(
        os.environ["PINECONE_API_KEY"],
        os.environ["PINECONE_INDEX"],
        _embed,
        host=os.environ.get("PINECONE_HOST"),
    )
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)
    yield instance
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)


def _query_until(
    store: PineconeVectorStore, tenant: UUID, text: str, expected: set[str]
) -> set[str]:
    """Query, polling for Pinecone's eventual-consistency indexing lag."""
    found: set[str] = set()
    for _ in range(15):
        found = {hit.doc_id for hit in store.query(tenant, text, k=10)}
        if expected <= found:
            return found
        time.sleep(1.0)
    return found


def test_pinecone_round_trips_and_isolates_tenants(store: PineconeVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    store.upsert(_TENANT_B, _documents(_TENANT_B, "b", "alpha"))
    found = _query_until(store, _TENANT_A, "alpha", {"a-0", "a-1", "a-2"})
    # tenant A's namespace returns only tenant A's documents
    assert found == {"a-0", "a-1", "a-2"}
