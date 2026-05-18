"""Integration tests for the live Chroma adapter.

Requires a ChromaDB server (see compose.yaml). The ``store`` fixture retries the
connection briefly and skips the tests when no server is reachable, so the
default test run stays offline.
"""

import hashlib
import os
import re
import time
from collections.abc import Iterator
from uuid import UUID

import chromadb
import pytest

from sectum.adapters.vector.chroma import ChromaVectorStore
from sectum.spec import CorpusDocument

pytestmark = pytest.mark.integration

_HOST = os.environ.get("SECTUM_CHROMA_HOST", "localhost")
_PORT = int(os.environ.get("SECTUM_CHROMA_PORT", "8001"))
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


def _server_ready() -> bool:
    for _ in range(10):
        try:
            chromadb.HttpClient(host=_HOST, port=_PORT)
        except Exception:
            time.sleep(0.5)
        else:
            return True
    return False


@pytest.fixture
def store() -> Iterator[ChromaVectorStore]:
    if not _server_ready():
        pytest.skip("Chroma backend not reachable")
    instance = ChromaVectorStore(_HOST, _PORT, _embed, prefix="sectum-it")
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)
    yield instance
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)


def test_chroma_round_trips_and_isolates_tenants(store: ChromaVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    store.upsert(_TENANT_B, _documents(_TENANT_B, "b", "alpha"))
    hits = store.query(_TENANT_A, "alpha", k=10)
    assert {hit.doc_id for hit in hits} == {"a-0", "a-1", "a-2"}
    assert all(hit.tenant_id == _TENANT_A for hit in hits)


def test_chroma_delete_and_list_namespaces(store: ChromaVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    assert any("sectum-it" in name for name in store.list_namespaces())
    store.delete(_TENANT_A)
    assert store.query(_TENANT_A, "alpha", k=10) == []
