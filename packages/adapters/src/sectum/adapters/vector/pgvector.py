"""Live pgvector adapter: a vector store backed by PostgreSQL with pgvector.

Documents are scoped by a ``tenant`` column and every query filters on it, so
this adapter is per-tenant isolated. A connection is opened per operation -
correctness over throughput for verification runs.

Requires the ``pgvector`` optional dependency: ``pip install sectum-ai-adapters[pgvector]``.
"""

from collections.abc import Callable, Sequence
from uuid import UUID

import psycopg

from sectum.adapters.base import Capability, VectorHit, VectorStoreAdapter
from sectum.spec import AdapterError, CorpusDocument

Embedder = Callable[[str], Sequence[float]]
"""A function turning text into an embedding vector."""


class PgVectorStore(VectorStoreAdapter):
    """A vector store backed by PostgreSQL with the pgvector extension."""

    def __init__(
        self,
        dsn: str,
        embed: Embedder,
        *,
        dim: int,
        name: str = "pgvector",
        table: str = "sectum_vectors",
    ) -> None:
        if not table.isidentifier():
            raise AdapterError(f"invalid table name: {table!r}")
        super().__init__(name, frozenset({Capability.PER_TENANT_NAMESPACE}))
        self._dsn = dsn
        self._embed = embed
        self._dim = dim
        self._table = table
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                "tenant uuid NOT NULL, doc_id text NOT NULL, content text NOT NULL, "
                f"embedding vector({self._dim}) NOT NULL, "
                "PRIMARY KEY (tenant, doc_id))"
            )
            conn.commit()

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            for document in documents:
                vector = self._literal(self._embed(f"{document.title} {document.content}"))
                cur.execute(
                    f"INSERT INTO {self._table} (tenant, doc_id, content, embedding) "
                    "VALUES (%s, %s, %s, %s::vector) "
                    "ON CONFLICT (tenant, doc_id) "
                    "DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding",
                    (str(tenant), document.doc_id, document.content, vector),
                )
            conn.commit()

    def query(self, tenant: UUID, text: str, k: int = 5) -> list[VectorHit]:
        vector = self._literal(self._embed(text))
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT doc_id, content, 1 - (embedding <=> %s::vector) AS score "
                f"FROM {self._table} WHERE tenant = %s "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (vector, str(tenant), vector, k),
            )
            rows = cur.fetchall()
        return [
            VectorHit(doc_id=doc_id, tenant_id=tenant, score=float(score), content=content)
            for doc_id, content, score in rows
        ]

    def fetch(self, tenant: UUID, doc_id: str) -> VectorHit | None:
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT content FROM {self._table} WHERE tenant = %s AND doc_id = %s",
                (str(tenant), doc_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return VectorHit(doc_id=doc_id, tenant_id=tenant, score=1.0, content=str(row[0]))

    def delete(self, tenant: UUID) -> None:
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self._table} WHERE tenant = %s", (str(tenant),))
            conn.commit()

    def list_namespaces(self) -> list[str]:
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT tenant FROM {self._table} ORDER BY tenant")
            return [str(row[0]) for row in cur.fetchall()]

    @staticmethod
    def _literal(values: Sequence[float]) -> str:
        return "[" + ",".join(repr(float(value)) for value in values) + "]"
