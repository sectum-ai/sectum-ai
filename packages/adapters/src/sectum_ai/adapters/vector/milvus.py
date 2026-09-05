"""Live Milvus adapter: a vector store backed by a Milvus server.

Each tenant maps to its own Milvus collection, so this adapter is per-tenant
isolated: a query or a fetch is scoped to the calling tenant's collection.
Embeddings are computed by the caller's embedder and passed to Milvus explicitly.
Each document id is folded into a deterministic primary key (a UUIDv5 string) so
an upsert is idempotent and a fetch is a direct id lookup; the original ``doc_id``
is preserved as a scalar field. The collection carries explicit scalar fields
(``doc_id``/``content``/``owner_user``) so boolean filtering and ``output_fields``
are reliable.

Milvus identifiers allow only letters, digits, and underscores, so the tenant's
collection name maps the id's prefix/hex onto that charset (``-`` becomes ``_``).

Requires the ``milvus`` optional dependency:
``pip install sectum-ai-adapters[milvus]``.
"""

from collections.abc import Callable, Sequence
from uuid import UUID, uuid5

from sectum_ai.adapters.base import Capability, VectorHit, VectorStoreAdapter
from sectum_ai.spec import AdapterError, CorpusDocument

Embedder = Callable[[str], Sequence[float]]
"""A function turning text into an embedding vector."""

_POINT_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
"""A fixed namespace for deriving a deterministic primary key from a ``doc_id``."""


class MilvusVectorStore(VectorStoreAdapter):
    """A vector store backed by a Milvus server, one collection per tenant.

    Scopes by tenant (one collection per tenant). With ``user_scoped=True`` it
    records each document's owning user and filters ``query`` (a boolean
    expression) and ``fetch`` (post-lookup) to the caller's own documents plus
    tenant-shared ones (reporting ``USER_SCOPED``), so one user cannot retrieve a
    sibling user's document within the tenant (ADR-0006). ``user=None`` is the
    tenant-level scope and is unchanged. Tenant-level documents carry an empty
    ``owner_user`` sentinel so the filter can match them.
    """

    _TENANT_LEVEL = ""
    """The ``owner_user`` field sentinel for a tenant-level (unowned) document."""

    def __init__(
        self,
        embed: Embedder,
        *,
        dim: int,
        uri: str = "http://localhost:19530",
        token: str | None = None,
        name: str = "milvus",
        prefix: str = "sectum_ai",
        user_scoped: bool = False,
    ) -> None:
        from pymilvus import MilvusClient

        capabilities = {Capability.PER_TENANT_NAMESPACE}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        super().__init__(name, frozenset(capabilities))
        self._client = MilvusClient(uri=uri, token=token or "")
        self._embed = embed
        self._dim = dim
        self._prefix = prefix
        self._user_scoped = user_scoped
        # Without a user scope nothing user-specific reaches the backend: a call
        # made as a user is the tenant's call, so user-level steps are not run.
        self.carries_user = user_scoped

    def _collection_name(self, tenant: UUID) -> str:
        # Milvus identifiers allow only [A-Za-z0-9_]; map the prefix + hex onto it.
        return f"{self._prefix}_{tenant.hex}".replace("-", "_")

    def _vector(self, text: str) -> list[float]:
        return [float(value) for value in self._embed(text)]

    @staticmethod
    def _primary_key(doc_id: str) -> str:
        return str(uuid5(_POINT_NAMESPACE, doc_id))

    def _ensure_collection(self, tenant: UUID) -> str:
        """Return the tenant's collection name, creating it on first use."""
        from pymilvus import DataType

        name = self._collection_name(tenant)
        if self._client.has_collection(name):
            return name
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self._dim)
        schema.add_field("doc_id", DataType.VARCHAR, max_length=512)
        schema.add_field("content", DataType.VARCHAR, max_length=65535)
        schema.add_field("owner_user", DataType.VARCHAR, max_length=64)
        index_params = self._client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        # Strong consistency: a verification tool must observe every write
        # immediately (a stale read could miss a leak or falsely report residue
        # erased), so it never trades correctness for the default bounded staleness.
        self._client.create_collection(
            collection_name=name,
            schema=schema,
            index_params=index_params,
            consistency_level="Strong",
        )
        return name

    def _user_filter(self, user: UUID | None) -> str:
        """A Milvus boolean expression for the user's own + tenant-shared docs."""
        if self._user_scoped and user is not None:
            return f'owner_user in ["{user}", "{self._TENANT_LEVEL}"]'
        return ""

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        items = list(documents)
        if not items:
            return
        collection = self._ensure_collection(tenant)
        rows = [
            {
                "id": self._primary_key(document.doc_id),
                "vector": self._vector(f"{document.title} {document.content}"),
                "doc_id": document.doc_id,
                "content": document.content,
                "owner_user": (
                    str(document.owner_user_id) if document.owner_user_id else self._TENANT_LEVEL
                ),
            }
            for document in items
        ]
        self._client.upsert(collection_name=collection, data=rows)

    def query(
        self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
    ) -> list[VectorHit]:
        collection = self._collection_name(tenant)
        if not self._client.has_collection(collection):
            return []
        results = self._client.search(
            collection_name=collection,
            data=[self._vector(text)],
            limit=k,
            filter=self._user_filter(user),
            output_fields=["doc_id", "content"],
        )
        hits: list[VectorHit] = []
        for match in results[0] if results else []:
            entity = match.get("entity", {})
            hits.append(
                VectorHit(
                    doc_id=str(entity.get("doc_id", match.get("id", ""))),
                    tenant_id=tenant,
                    score=float(match.get("distance", 0.0)),
                    content=str(entity.get("content", "")),
                )
            )
        return hits

    def fetch(self, tenant: UUID, doc_id: str, *, user: UUID | None = None) -> VectorHit | None:
        collection = self._collection_name(tenant)
        if not self._client.has_collection(collection):
            return None
        records = self._client.get(
            collection_name=collection,
            ids=[self._primary_key(doc_id)],
            output_fields=["doc_id", "content", "owner_user"],
        )
        if not records:
            return None
        record = records[0]
        # get is a direct id lookup with no expression filter, so a user-scoped
        # store checks the owning user here (ADR-0006).
        if self._user_scoped and user is not None:
            owner_user = str(record.get("owner_user", self._TENANT_LEVEL))
            if owner_user not in (str(user), self._TENANT_LEVEL):
                return None
        return VectorHit(
            doc_id=str(record.get("doc_id", doc_id)),
            tenant_id=tenant,
            score=1.0,
            content=str(record.get("content", "")),
        )

    def delete(self, tenant: UUID) -> None:
        collection = self._collection_name(tenant)
        if self._client.has_collection(collection):
            self._client.drop_collection(collection_name=collection)

    def list_namespaces(self) -> list[str]:
        try:
            collections = self._client.list_collections()
        except Exception as error:
            raise AdapterError(f"failed to list Milvus collections: {error}") from error
        return sorted(str(name) for name in collections)

    def close(self) -> None:
        """Close the Milvus client; call this when the adapter is done."""
        self._client.close()
