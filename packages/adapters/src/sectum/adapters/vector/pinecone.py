"""Live Pinecone adapter: a vector store backed by a Pinecone index.

Each tenant maps to its own Pinecone namespace within a single index, so this
adapter is per-tenant isolated: a query or a fetch is scoped to the calling
tenant's namespace. Embeddings are computed by the caller's embedder and passed
to Pinecone explicitly; the document id is the vector id, so an upsert is
idempotent and a fetch is a direct id lookup.

Pinecone is a hosted service with no local backend, so it is verified by a
mock-backed contract test plus an opt-in live test (the engineering spec,
sections 11 and 13). The ``pinecone`` package is imported only on the live
connection path, so the adapter and its mock-backed test need no extra
dependency. The live path requires the ``pinecone`` optional dependency:
``pip install sectum-ai-adapters[pinecone]``.
"""

from collections.abc import Callable, Sequence
from typing import Any, Self
from uuid import UUID

from sectum.adapters.base import Capability, VectorHit, VectorStoreAdapter
from sectum.spec import CorpusDocument

Embedder = Callable[[str], Sequence[float]]
"""A function turning text into an embedding vector."""


class PineconeVectorStore(VectorStoreAdapter):
    """A vector store backed by a Pinecone index, one namespace per tenant.

    Construct it with an open Pinecone ``Index`` object (or use
    :meth:`connect`). The index is held opaquely so the adapter can be tested
    against an in-memory stand-in without the ``pinecone`` package.
    """

    def __init__(self, index: Any, embed: Embedder, *, name: str = "pinecone") -> None:
        super().__init__(name, frozenset({Capability.PER_TENANT_NAMESPACE}))
        self._index = index
        self._embed = embed

    @classmethod
    def connect(
        cls,
        api_key: str,
        index_name: str,
        embed: Embedder,
        *,
        host: str | None = None,
        name: str = "pinecone",
    ) -> Self:
        """Open a Pinecone index by name (or host) and return the adapter.

        The ``pinecone`` package is imported here, on the live path only, so the
        adapter module and its mock-backed test do not require it.
        """
        from pinecone import Pinecone

        client = Pinecone(api_key=api_key)
        index = client.Index(host=host) if host else client.Index(index_name)
        return cls(index, embed, name=name)

    def _vector(self, text: str) -> list[float]:
        return [float(value) for value in self._embed(text)]

    @staticmethod
    def _metadata(item: Any) -> dict[str, Any]:
        # Pinecone's metadata is optional: a vector upserted without it has no
        # metadata attribute at all (the SDK model raises AttributeError), so a
        # foreign vector must not crash a read.
        return getattr(item, "metadata", None) or {}

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        vectors = [
            {
                "id": document.doc_id,
                "values": self._vector(f"{document.title} {document.content}"),
                "metadata": {"doc_id": document.doc_id, "content": document.content},
            }
            for document in documents
        ]
        if vectors:
            self._index.upsert(vectors=vectors, namespace=tenant.hex)

    def query(self, tenant: UUID, text: str, k: int = 5) -> list[VectorHit]:
        response = self._index.query(
            vector=self._vector(text),
            top_k=k,
            namespace=tenant.hex,
            include_metadata=True,
        )
        hits: list[VectorHit] = []
        for match in response.matches:
            metadata = self._metadata(match)
            hits.append(
                VectorHit(
                    doc_id=str(metadata.get("doc_id", match.id)),
                    tenant_id=tenant,
                    score=float(match.score),
                    content=str(metadata.get("content", "")),
                )
            )
        return hits

    def fetch(self, tenant: UUID, doc_id: str) -> VectorHit | None:
        response = self._index.fetch(ids=[doc_id], namespace=tenant.hex)
        vector = response.vectors.get(doc_id)
        if vector is None:
            return None
        metadata = self._metadata(vector)
        return VectorHit(
            doc_id=str(metadata.get("doc_id", doc_id)),
            tenant_id=tenant,
            score=1.0,
            content=str(metadata.get("content", "")),
        )

    def delete(self, tenant: UUID) -> None:
        self._index.delete(delete_all=True, namespace=tenant.hex)

    def list_namespaces(self) -> list[str]:
        stats = self._index.describe_index_stats()
        return sorted(stats.namespaces)
