"""Opt-in live integration test for the Azure AI Search vector adapter.

Azure AI Search is a hosted service with no local emulator, so this test is
skipped unless ``SECTUM_AZURE_SEARCH_ENDPOINT`` and ``SECTUM_AZURE_SEARCH_KEY``
are set (the engineering spec, section 13: opt-in live), mirroring the Pinecone
live test. Enable it with ``pip install sectum-ai-adapters[azure-search]`` and the
env vars; the resolver wiring is covered offline by ``tests/unit/test_config.py``.
"""

import hashlib
import os
import re
import time
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum_ai.adapters.base import Capability
from sectum_ai.adapters.vector.azure_search import AzureSearchVectorStore
from sectum_ai.spec import CorpusDocument

_ENDPOINT = os.environ.get("SECTUM_AZURE_SEARCH_ENDPOINT")
_KEY = os.environ.get("SECTUM_AZURE_SEARCH_KEY")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (_ENDPOINT and _KEY),
        reason="set SECTUM_AZURE_SEARCH_ENDPOINT and SECTUM_AZURE_SEARCH_KEY to run",
    ),
]

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


def _settle() -> None:
    """Azure AI Search indexes documents near-real-time; give it a moment."""
    time.sleep(3)


@pytest.fixture
def store() -> Iterator[AzureSearchVectorStore]:
    assert _ENDPOINT and _KEY  # narrowed by the module skipif
    instance = AzureSearchVectorStore(
        _embed, dim=_DIM, endpoint=_ENDPOINT, api_key=_KEY, prefix="sectum-it"
    )
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)
    yield instance
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)
    instance.close()


def test_azure_search_round_trips_and_isolates_tenants(store: AzureSearchVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    store.upsert(_TENANT_B, _documents(_TENANT_B, "b", "alpha"))
    _settle()
    hits = store.query(_TENANT_A, "alpha", k=10)
    assert {hit.doc_id for hit in hits} == {"a-0", "a-1", "a-2"}
    assert all(hit.tenant_id == _TENANT_A for hit in hits)


def test_azure_search_fetch_by_id_is_tenant_scoped(store: AzureSearchVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    _settle()
    hit = store.fetch(_TENANT_A, "a-1")
    assert hit is not None
    assert hit.doc_id == "a-1"
    assert store.fetch(_TENANT_A, "missing") is None
    # a per-tenant-index store denies another tenant's document id
    assert store.fetch(_TENANT_B, "a-1") is None


def test_azure_search_delete_and_list_namespaces(store: AzureSearchVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    _settle()
    assert any("sectum-it" in name for name in store.list_namespaces())
    store.delete(_TENANT_A)
    _settle()
    assert store.query(_TENANT_A, "alpha", k=10) == []


def test_azure_search_user_scoped_isolates_users() -> None:
    assert _ENDPOINT and _KEY  # narrowed by the module skipif
    scoped = AzureSearchVectorStore(
        _embed, dim=_DIM, endpoint=_ENDPOINT, api_key=_KEY, prefix="sectum-it-us", user_scoped=True
    )
    scoped.delete(_TENANT_A)
    try:
        scoped.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_A, "ua", "alpha"))
        scoped.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_B, "ub", "alpha"))
        _settle()
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
