"""Live Weaviate adapter: a vector store backed by a Weaviate server.

Each tenant maps to its own Weaviate collection, so this adapter is per-tenant
isolated. Embeddings are computed by the caller's embedder and passed to
Weaviate explicitly (the collection is created with self-provided vectors).
Each document id is folded into a deterministic object id, so an upsert is
idempotent and a fetch is a direct object lookup.

Requires the ``weaviate`` optional dependency: ``pip install sectum-ai-adapters[weaviate]``.
"""

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

import weaviate
from weaviate.classes.config import Configure, DataType, Property
from weaviate.classes.query import MetadataQuery
from weaviate.util import generate_uuid5

from sectum.adapters.base import Capability, VectorHit, VectorStoreAdapter
from sectum.spec import AdapterError, CorpusDocument

Embedder = Callable[[str], Sequence[float]]
"""A function turning text into an embedding vector."""


class WeaviateVectorStore(VectorStoreAdapter):
    """A vector store backed by a Weaviate server.

    Scopes by tenant (one collection per tenant). ``user`` is accepted on
    ``query``/``fetch`` for interface conformance (ADR-0008) but not yet enforced
    - per-user isolation is a per-backend follow-on - so this adapter does not
    report ``USER_SCOPED``.
    """

    def __init__(
        self,
        host: str,
        port: int,
        grpc_port: int,
        embed: Embedder,
        *,
        name: str = "weaviate",
        prefix: str = "Sectum",
    ) -> None:
        if not (prefix.isalnum() and prefix[:1].isupper()):
            raise AdapterError(
                f"prefix must be alphanumeric and start with an uppercase letter: {prefix!r}"
            )
        super().__init__(name, frozenset({Capability.PER_TENANT_NAMESPACE}))
        self._client = weaviate.connect_to_local(host=host, port=port, grpc_port=grpc_port)
        self._embed = embed
        self._prefix = prefix

    def close(self) -> None:
        """Close the Weaviate connection; call this when the adapter is done."""
        self._client.close()

    def _collection_name(self, tenant: UUID) -> str:
        return f"{self._prefix}{tenant.hex}"

    def _vector(self, text: str) -> list[float]:
        return [float(value) for value in self._embed(text)]

    def _collection(self, tenant: UUID) -> Any:
        """Return the tenant's collection, creating it on first use."""
        name = self._collection_name(tenant)
        if not self._client.collections.exists(name):
            self._client.collections.create(
                name,
                vector_config=Configure.Vectors.self_provided(),
                properties=[
                    Property(name="doc_id", data_type=DataType.TEXT),
                    Property(name="content", data_type=DataType.TEXT),
                ],
            )
        return self._client.collections.get(name)

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        items = list(documents)
        if not items:
            return
        collection = self._collection(tenant)
        for document in items:
            object_id = generate_uuid5(document.doc_id)
            properties = {"doc_id": document.doc_id, "content": document.content}
            vector = self._vector(f"{document.title} {document.content}")
            if collection.data.exists(object_id):
                collection.data.replace(uuid=object_id, properties=properties, vector=vector)
            else:
                collection.data.insert(properties=properties, uuid=object_id, vector=vector)

    def query(
        self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
    ) -> list[VectorHit]:
        collection = self._collection(tenant)
        result = collection.query.near_vector(
            self._vector(text), limit=k, return_metadata=MetadataQuery(distance=True)
        )
        return [
            VectorHit(
                doc_id=str(obj.properties["doc_id"]),
                tenant_id=tenant,
                score=1.0 - float(obj.metadata.distance or 0.0),
                content=str(obj.properties["content"]),
            )
            for obj in result.objects
        ]

    def fetch(self, tenant: UUID, doc_id: str, *, user: UUID | None = None) -> VectorHit | None:
        collection = self._collection(tenant)
        obj = collection.query.fetch_object_by_id(generate_uuid5(doc_id))
        if obj is None:
            return None
        return VectorHit(
            doc_id=str(obj.properties["doc_id"]),
            tenant_id=tenant,
            score=1.0,
            content=str(obj.properties["content"]),
        )

    def delete(self, tenant: UUID) -> None:
        name = self._collection_name(tenant)
        if self._client.collections.exists(name):
            self._client.collections.delete(name)

    def list_namespaces(self) -> list[str]:
        return sorted(str(name) for name in self._client.collections.list_all())
