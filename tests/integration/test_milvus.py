"""Integration tests for the live Milvus adapter.

Requires a Milvus server (see compose.yaml's ``milvus`` profile:
``docker compose --profile milvus up -d``) and the ``milvus`` extra. The ``store``
fixture retries the connection briefly and skips the tests when the client/server
is unavailable, so the default test run stays offline.
"""

import hashlib
import os
import re
import time
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum_ai.adapters.base import Capability
from sectum_ai.adapters.vector.milvus import MilvusVectorStore
from sectum_ai.spec import CorpusDocument

pytestmark = pytest.mark.integration

_URI = os.environ.get("SECTUM_MILVUS_URI", "http://localhost:19530")
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


def _server_ready() -> bool:
    try:
        from pymilvus import MilvusClient
    except ImportError:
        return False
    for _ in range(20):
        try:
            client = MilvusClient(uri=_URI)
            client.list_collections()
            client.close()
        except Exception:
            time.sleep(0.5)
        else:
            return True
    return False


@pytest.fixture
def store() -> Iterator[MilvusVectorStore]:
    if not _server_ready():
        pytest.skip("Milvus backend not reachable")
    instance = MilvusVectorStore(_embed, dim=_DIM, uri=_URI, prefix="sectum_it")
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)
    yield instance
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)
    instance.close()


def test_milvus_round_trips_and_isolates_tenants(store: MilvusVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    store.upsert(_TENANT_B, _documents(_TENANT_B, "b", "alpha"))
    hits = store.query(_TENANT_A, "alpha", k=10)
    assert {hit.doc_id for hit in hits} == {"a-0", "a-1", "a-2"}
    assert all(hit.tenant_id == _TENANT_A for hit in hits)


def test_milvus_delete_and_list_namespaces(store: MilvusVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    assert any("sectum_it" in name for name in store.list_namespaces())
    store.delete(_TENANT_A)
    assert store.query(_TENANT_A, "alpha", k=10) == []


def test_milvus_fetch_by_id_is_tenant_scoped(store: MilvusVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    hit = store.fetch(_TENANT_A, "a-1")
    assert hit is not None
    assert hit.doc_id == "a-1"
    assert store.fetch(_TENANT_A, "missing") is None
    # a per-tenant-collection store denies another tenant's document id
    assert store.fetch(_TENANT_B, "a-1") is None


def test_milvus_user_scoped_isolates_users() -> None:
    if not _server_ready():
        pytest.skip("Milvus backend not reachable")
    scoped = MilvusVectorStore(_embed, dim=_DIM, uri=_URI, prefix="sectum_it_us", user_scoped=True)
    scoped.delete(_TENANT_A)
    try:
        scoped.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_A, "ua", "alpha"))
        scoped.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_B, "ub", "alpha"))
        hits = scoped.query(_TENANT_A, "alpha", k=10, user=_USER_A)
        assert hits
        assert all(hit.doc_id.startswith("ua-") for hit in hits)
        # a direct fetch of user B's document from user A's session is denied
        assert scoped.fetch(_TENANT_A, "ub-0", user=_USER_A) is None
        assert scoped.fetch(_TENANT_A, "ua-0", user=_USER_A) is not None
        assert scoped.supports(Capability.USER_SCOPED)
    finally:
        scoped.delete(_TENANT_A)
        scoped.close()
