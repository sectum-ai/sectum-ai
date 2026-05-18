"""Integration tests for the live pgvector adapter.

Requires a PostgreSQL + pgvector backend (see compose.yaml). The ``store``
fixture skips the tests when no backend is reachable, so the default test run
stays offline.
"""

import hashlib
import os
import re
from collections.abc import Iterator
from uuid import UUID

import psycopg
import pytest

from sectum.adapters.vector.pgvector import PgVectorStore
from sectum.spec import CorpusDocument

pytestmark = pytest.mark.integration

_DSN = os.environ.get("SECTUM_PGVECTOR_DSN", "postgresql://sectum:sectum@localhost:5433/sectum")
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
def store() -> Iterator[PgVectorStore]:
    try:
        psycopg.connect(_DSN).close()
    except psycopg.OperationalError as error:
        pytest.skip(f"pgvector backend not reachable: {error}")
    instance = PgVectorStore(_DSN, _embed, dim=_DIM, table="sectum_it_vectors")
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)
    yield instance
    instance.delete(_TENANT_A)
    instance.delete(_TENANT_B)


def test_pgvector_round_trips_and_isolates_tenants(store: PgVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    store.upsert(_TENANT_B, _documents(_TENANT_B, "b", "alpha"))
    hits = store.query(_TENANT_A, "alpha", k=10)
    assert {hit.doc_id for hit in hits} == {"a-0", "a-1", "a-2"}
    assert all(hit.tenant_id == _TENANT_A for hit in hits)


def test_pgvector_delete_and_list_namespaces(store: PgVectorStore) -> None:
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    assert str(_TENANT_A) in store.list_namespaces()
    store.delete(_TENANT_A)
    assert store.query(_TENANT_A, "alpha", k=10) == []
