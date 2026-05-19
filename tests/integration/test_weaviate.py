"""Integration tests for the live Weaviate adapter.

Requires a Weaviate server (see compose.yaml). The ``store`` fixture skips the
tests when no server is reachable, so the default test run stays offline.
"""

import hashlib
import os
import re
from collections.abc import Iterator
from uuid import UUID

import pytest
from weaviate.exceptions import WeaviateBaseError

from sectum.adapters.vector.weaviate import WeaviateVectorStore
from sectum.spec import CorpusDocument

pytestmark = pytest.mark.integration

_HOST = os.environ.get("SECTUM_WEAVIATE_HOST", "localhost")
_PORT = int(os.environ.get("SECTUM_WEAVIATE_PORT", "8082"))
_GRPC_PORT = int(os.environ.get("SECTUM_WEAVIATE_GRPC_PORT", "50052"))
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
def store() -> Iterator[WeaviateVectorStore]:
    try:
        instance = WeaviateVectorStore(_HOST, _PORT, _GRPC_PORT, _embed, prefix="SectumIt")
    except WeaviateBaseError as error:
        pytest.skip(f"Weaviate backend not reachable: {error}")
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)
    yield instance
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)
    instance.close()


def test_weaviate_round_trips_and_isolates_tenants(store: WeaviateVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    store.upsert(_TENANT_B, _documents(_TENANT_B, "b", "alpha"))
    hits = store.query(_TENANT_A, "alpha", k=10)
    assert {hit.doc_id for hit in hits} == {"a-0", "a-1", "a-2"}
    assert all(hit.tenant_id == _TENANT_A for hit in hits)


def test_weaviate_delete_and_list_namespaces(store: WeaviateVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    assert any("SectumIt" in name for name in store.list_namespaces())
    store.delete(_TENANT_A)
    assert store.query(_TENANT_A, "alpha", k=10) == []


def test_weaviate_fetch_by_id_is_tenant_scoped(store: WeaviateVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    hit = store.fetch(_TENANT_A, "a-1")
    assert hit is not None
    assert hit.doc_id == "a-1"
    assert store.fetch(_TENANT_A, "missing") is None
    # an isolated store denies another tenant's document id
    assert store.fetch(_TENANT_B, "a-1") is None
