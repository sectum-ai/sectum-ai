"""Live Chroma adapter: a vector store backed by a ChromaDB server.

Each tenant maps to its own Chroma collection, so this adapter is per-tenant
isolated. Embeddings are computed by the caller's embedder and passed to Chroma
explicitly, so the lightweight ``chromadb-client`` package is sufficient.

Requires the ``chroma`` optional dependency: ``pip install sectum-ai-adapters[chroma]``.
"""

from collections.abc import Callable, Sequence
from uuid import UUID

import chromadb

from sectum_ai.adapters.base import Capability, VectorHit, VectorStoreAdapter
from sectum_ai.spec import CorpusDocument

Embedder = Callable[[str], Sequence[float]]
"""A function turning text into an embedding vector."""


class ChromaVectorStore(VectorStoreAdapter):
    """A vector store backed by a ChromaDB server.

    Scopes by tenant (one collection per tenant). With ``user_scoped=True`` it
    records each document's owning user in metadata and filters ``query``/
    ``fetch`` to the caller's own documents plus tenant-shared ones (reporting
    ``USER_SCOPED``), so one user cannot retrieve a sibling user's document
    within the tenant (ADR-0006). ``user=None`` is the tenant-level scope and is
    unchanged. Tenant-level documents carry an empty ``owner_user`` sentinel so
    the metadata filter can match them.
    """

    _TENANT_LEVEL = ""
    """The ``owner_user`` metadata sentinel for a tenant-level (unowned) document."""

    def __init__(
        self,
        host: str,
        port: int,
        embed: Embedder,
        *,
        name: str = "chroma",
        prefix: str = "sectum-ai",
        user_scoped: bool = False,
    ) -> None:
        capabilities = {Capability.PER_TENANT_NAMESPACE}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        super().__init__(name, frozenset(capabilities))
        self._client = chromadb.HttpClient(host=host, port=port)
        self._embed = embed
        self._prefix = prefix
        self._user_scoped = user_scoped

    def _collection_name(self, tenant: UUID) -> str:
        return f"{self._prefix}-{tenant.hex}"

    def _vector(self, text: str) -> list[float]:
        return [float(value) for value in self._embed(text)]

    def _user_where(self, user: UUID | None) -> dict[str, object] | None:
        """A Chroma ``where`` filter for the user's own + tenant-shared documents."""
        if self._user_scoped and user is not None:
            return {"owner_user": {"$in": [str(user), self._TENANT_LEVEL]}}
        return None

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        items = list(documents)
        if not items:
            return
        collection = self._client.get_or_create_collection(
            self._collection_name(tenant), embedding_function=None
        )
        collection.upsert(
            ids=[document.doc_id for document in items],
            embeddings=[self._vector(f"{document.title} {document.content}") for document in items],
            documents=[document.content for document in items],
            metadatas=[
                {
                    "owner_user": str(document.owner_user_id)
                    if document.owner_user_id
                    else self._TENANT_LEVEL
                }
                for document in items
            ],
        )

    def query(
        self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
    ) -> list[VectorHit]:
        collection = self._client.get_or_create_collection(
            self._collection_name(tenant), embedding_function=None
        )
        where = self._user_where(user)
        result = collection.query(
            query_embeddings=[self._vector(text)],
            n_results=k,
            **({"where": where} if where is not None else {}),
        )
        ids = result["ids"][0]
        documents = result["documents"][0] if result["documents"] else [""] * len(ids)
        distances = result["distances"][0] if result["distances"] else [0.0] * len(ids)
        return [
            VectorHit(
                doc_id=doc_id,
                tenant_id=tenant,
                score=1.0 - float(distance),
                content=content,
            )
            for doc_id, content, distance in zip(ids, documents, distances, strict=True)
        ]

    def fetch(self, tenant: UUID, doc_id: str, *, user: UUID | None = None) -> VectorHit | None:
        collection = self._client.get_or_create_collection(
            self._collection_name(tenant), embedding_function=None
        )
        where = self._user_where(user)
        result = collection.get(ids=[doc_id], **({"where": where} if where is not None else {}))
        ids = result["ids"]
        if not ids:
            return None
        documents = result["documents"] or [""]
        return VectorHit(doc_id=ids[0], tenant_id=tenant, score=1.0, content=documents[0])

    def delete(self, tenant: UUID) -> None:
        name = self._collection_name(tenant)
        if name in {collection.name for collection in self._client.list_collections()}:
            self._client.delete_collection(name)

    def list_namespaces(self) -> list[str]:
        return sorted(collection.name for collection in self._client.list_collections())
