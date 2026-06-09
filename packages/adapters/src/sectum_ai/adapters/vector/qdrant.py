"""Live Qdrant adapter: a vector store backed by a Qdrant server.

Each tenant maps to its own Qdrant collection, so this adapter is per-tenant
isolated: a query or a fetch is scoped to the calling tenant's collection.
Embeddings are computed by the caller's embedder and passed to Qdrant
explicitly. Each document id is folded into a deterministic point id (a UUIDv5),
so an upsert is idempotent and a fetch is a direct point lookup; the original
``doc_id`` is preserved in the point payload.

Requires the ``qdrant`` optional dependency: ``pip install sectum-ai-adapters[qdrant]``.
"""

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID, uuid5

from sectum_ai.adapters.base import Capability, VectorHit, VectorStoreAdapter
from sectum_ai.spec import AdapterError, CorpusDocument

Embedder = Callable[[str], Sequence[float]]
"""A function turning text into an embedding vector."""

_POINT_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
"""A fixed namespace for deriving a deterministic point id from a ``doc_id``."""


class QdrantVectorStore(VectorStoreAdapter):
    """A vector store backed by a Qdrant server, one collection per tenant.

    Scopes by tenant (one collection per tenant). With ``user_scoped=True`` it
    records each document's owning user in the point payload and filters
    ``query`` (a payload filter) and ``fetch`` (post-lookup) to the caller's own
    documents plus tenant-shared ones (reporting ``USER_SCOPED``), so one user
    cannot retrieve a sibling user's document within the tenant (ADR-0006).
    ``user=None`` is the tenant-level scope and is unchanged. Tenant-level
    documents carry an empty ``owner_user`` sentinel so the filter can match them.
    """

    _TENANT_LEVEL = ""
    """The ``owner_user`` payload sentinel for a tenant-level (unowned) document."""

    def __init__(
        self,
        embed: Embedder,
        *,
        dim: int,
        host: str = "localhost",
        port: int = 6333,
        grpc_port: int = 6334,
        prefer_grpc: bool = False,
        api_key: str | None = None,
        https: bool | None = None,
        name: str = "qdrant",
        prefix: str = "sectum-ai",
        user_scoped: bool = False,
    ) -> None:
        from qdrant_client import QdrantClient

        capabilities = {Capability.PER_TENANT_NAMESPACE}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        super().__init__(name, frozenset(capabilities))
        self._client = QdrantClient(
            host=host,
            port=port,
            grpc_port=grpc_port,
            prefer_grpc=prefer_grpc,
            api_key=api_key,
            https=https,
        )
        self._embed = embed
        self._dim = dim
        self._prefix = prefix
        self._user_scoped = user_scoped

    def _collection_name(self, tenant: UUID) -> str:
        return f"{self._prefix}-{tenant.hex}"

    def _vector(self, text: str) -> list[float]:
        return [float(value) for value in self._embed(text)]

    @staticmethod
    def _point_id(doc_id: str) -> str:
        return str(uuid5(_POINT_NAMESPACE, doc_id))

    def _ensure_collection(self, tenant: UUID) -> str:
        """Return the tenant's collection name, creating the collection on first use."""
        from qdrant_client import models

        name = self._collection_name(tenant)
        if not self._client.collection_exists(name):
            self._client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(size=self._dim, distance=models.Distance.COSINE),
            )
        return name

    def _user_filter(self, user: UUID | None) -> Any:
        """A Qdrant filter for the user's own + tenant-shared documents."""
        from qdrant_client import models

        if self._user_scoped and user is not None:
            return models.Filter(
                should=[
                    models.FieldCondition(
                        key="owner_user", match=models.MatchValue(value=str(user))
                    ),
                    models.FieldCondition(
                        key="owner_user", match=models.MatchValue(value=self._TENANT_LEVEL)
                    ),
                ]
            )
        return None

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        from qdrant_client import models

        items = list(documents)
        if not items:
            return
        collection = self._ensure_collection(tenant)
        points = [
            models.PointStruct(
                id=self._point_id(document.doc_id),
                vector=self._vector(f"{document.title} {document.content}"),
                payload={
                    "doc_id": document.doc_id,
                    "content": document.content,
                    "owner_user": (
                        str(document.owner_user_id)
                        if document.owner_user_id
                        else self._TENANT_LEVEL
                    ),
                },
            )
            for document in items
        ]
        self._client.upsert(collection_name=collection, points=points, wait=True)

    def query(
        self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
    ) -> list[VectorHit]:
        collection = self._collection_name(tenant)
        if not self._client.collection_exists(collection):
            return []
        response = self._client.query_points(
            collection_name=collection,
            query=self._vector(text),
            limit=k,
            with_payload=True,
            query_filter=self._user_filter(user),
        )
        hits: list[VectorHit] = []
        for point in response.points:
            payload = point.payload or {}
            hits.append(
                VectorHit(
                    doc_id=str(payload.get("doc_id", point.id)),
                    tenant_id=tenant,
                    score=float(point.score),
                    content=str(payload.get("content", "")),
                )
            )
        return hits

    def fetch(self, tenant: UUID, doc_id: str, *, user: UUID | None = None) -> VectorHit | None:
        collection = self._collection_name(tenant)
        if not self._client.collection_exists(collection):
            return None
        records = self._client.retrieve(
            collection_name=collection, ids=[self._point_id(doc_id)], with_payload=True
        )
        if not records:
            return None
        payload = records[0].payload or {}
        # retrieve is a direct id lookup with no server-side filter, so a
        # user-scoped store checks the owning user here (ADR-0006).
        if self._user_scoped and user is not None:
            owner_user = str(payload.get("owner_user", self._TENANT_LEVEL))
            if owner_user not in (str(user), self._TENANT_LEVEL):
                return None
        return VectorHit(
            doc_id=str(payload.get("doc_id", doc_id)),
            tenant_id=tenant,
            score=1.0,
            content=str(payload.get("content", "")),
        )

    def delete(self, tenant: UUID) -> None:
        collection = self._collection_name(tenant)
        if self._client.collection_exists(collection):
            self._client.delete_collection(collection_name=collection)

    def list_namespaces(self) -> list[str]:
        try:
            collections = self._client.get_collections().collections
        except Exception as error:
            raise AdapterError(f"failed to list Qdrant collections: {error}") from error
        return sorted(collection.name for collection in collections)

    def close(self) -> None:
        """Close the Qdrant client; call this when the adapter is done."""
        self._client.close()
