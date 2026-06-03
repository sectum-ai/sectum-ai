"""Live pgvector adapter: a vector store backed by PostgreSQL with pgvector.

Documents are scoped by a ``tenant`` column and every query filters on it, so
this adapter is per-tenant isolated. A connection is opened per operation -
correctness over throughput for verification runs.

Requires the ``pgvector`` optional dependency: ``pip install sectum-ai-adapters[pgvector]``.
"""

from collections.abc import Callable, Sequence
from uuid import UUID

import psycopg

from sectum_ai.adapters.base import Capability, VectorHit, VectorStoreAdapter
from sectum_ai.spec import AdapterError, CorpusDocument

Embedder = Callable[[str], Sequence[float]]
"""A function turning text into an embedding vector."""


class PgVectorStore(VectorStoreAdapter):
    """A vector store backed by PostgreSQL with the pgvector extension.

    Scopes by tenant via a ``tenant`` column. With ``user_scoped=True`` it also
    records each document's ``owner_user`` and filters ``query``/``fetch`` to the
    caller's own rows plus tenant-shared ones (reporting ``USER_SCOPED``), so one
    user cannot retrieve a sibling user's document within the tenant (ADR-0006).
    ``user=None`` is the tenant-level scope and is unchanged.
    """

    def __init__(
        self,
        dsn: str,
        embed: Embedder,
        *,
        dim: int,
        name: str = "pgvector",
        table: str = "sectum_vectors",
        user_scoped: bool = False,
    ) -> None:
        if not table.isidentifier():
            raise AdapterError(f"invalid table name: {table!r}")
        capabilities = {Capability.PER_TENANT_NAMESPACE}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        super().__init__(name, frozenset(capabilities))
        self._dsn = dsn
        self._embed = embed
        self._dim = dim
        self._table = table
        self._user_scoped = user_scoped
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                "tenant uuid NOT NULL, doc_id text NOT NULL, content text NOT NULL, "
                f"embedding vector({self._dim}) NOT NULL, owner_user uuid, "
                "PRIMARY KEY (tenant, doc_id))"
            )
            # Idempotent migration for tables created before the user dimension.
            cur.execute(f"ALTER TABLE {self._table} ADD COLUMN IF NOT EXISTS owner_user uuid")
            conn.commit()

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            for document in documents:
                vector = self._literal(self._embed(f"{document.title} {document.content}"))
                owner_user = str(document.owner_user_id) if document.owner_user_id else None
                cur.execute(
                    f"INSERT INTO {self._table} (tenant, doc_id, content, embedding, owner_user) "
                    "VALUES (%s, %s, %s, %s::vector, %s) "
                    "ON CONFLICT (tenant, doc_id) DO UPDATE SET "
                    "content = EXCLUDED.content, embedding = EXCLUDED.embedding, "
                    "owner_user = EXCLUDED.owner_user",
                    (str(tenant), document.doc_id, document.content, vector, owner_user),
                )
            conn.commit()

    def _user_filter(self, user: UUID | None, params: list[object]) -> str:
        """Append the user-scope params and return the SQL clause (empty if not scoped).

        A user-scoped store exposes the caller's own rows plus tenant-shared ones
        (``owner_user IS NULL``); a tenant-only store ignores ``user``.
        """
        if self._user_scoped and user is not None:
            params.append(str(user))
            return "AND (owner_user IS NULL OR owner_user = %s) "
        return ""

    def query(
        self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
    ) -> list[VectorHit]:
        vector = self._literal(self._embed(text))
        params: list[object] = [vector, str(tenant)]
        user_clause = self._user_filter(user, params)
        params.extend([vector, k])
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT doc_id, content, 1 - (embedding <=> %s::vector) AS score "
                f"FROM {self._table} WHERE tenant = %s {user_clause}"
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                params,
            )
            rows = cur.fetchall()
        return [
            VectorHit(doc_id=doc_id, tenant_id=tenant, score=float(score), content=content)
            for doc_id, content, score in rows
        ]

    def fetch(self, tenant: UUID, doc_id: str, *, user: UUID | None = None) -> VectorHit | None:
        params: list[object] = [str(tenant), doc_id]
        user_clause = self._user_filter(user, params)
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT content FROM {self._table} "
                f"WHERE tenant = %s AND doc_id = %s {user_clause}",
                params,
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
