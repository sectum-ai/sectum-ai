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
from weaviate.classes.config import Configure, DataType, Property, Tokenization
from weaviate.classes.query import Filter, MetadataQuery
from weaviate.util import generate_uuid5

from sectum_ai.adapters.base import Capability, VectorHit, VectorStoreAdapter
from sectum_ai.spec import AdapterError, CorpusDocument

Embedder = Callable[[str], Sequence[float]]
"""A function turning text into an embedding vector."""


class WeaviateVectorStore(VectorStoreAdapter):
    """A vector store backed by a Weaviate server.

    Scopes by tenant (one collection per tenant). With ``user_scoped=True`` it
    records each document's owning user in an ``owner_user`` property and filters
    ``query``/``fetch`` to the caller's own documents plus tenant-shared ones
    (reporting ``USER_SCOPED``), so one user cannot retrieve a sibling user's
    document within the tenant (ADR-0006). ``user=None`` is the tenant-level scope
    and is unchanged. Tenant-level documents carry an empty ``owner_user``
    sentinel so the filter can match them.
    """

    _TENANT_LEVEL = "tenant-level"
    """The ``owner_user`` sentinel for a tenant-level (unowned) document.

    Non-empty on purpose: the ``owner_user`` property uses FIELD tokenization, and
    Weaviate rejects an ``equal("")`` filter ("only stopwords provided").
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
        user_scoped: bool = False,
    ) -> None:
        if not (prefix.isalnum() and prefix[:1].isupper()):
            raise AdapterError(
                f"prefix must be alphanumeric and start with an uppercase letter: {prefix!r}"
            )
        capabilities = {Capability.PER_TENANT_NAMESPACE}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        super().__init__(name, frozenset(capabilities))
        self._client = weaviate.connect_to_local(host=host, port=port, grpc_port=grpc_port)
        self._embed = embed
        self._prefix = prefix
        self._user_scoped = user_scoped
        # Without a user scope nothing user-specific reaches the backend: a call
        # made as a user is the tenant's call, so user-level steps are not run.
        self.carries_user = user_scoped

    def _user_filter(self, user: UUID | None) -> Filter | None:
        """A Weaviate filter for the user's own + tenant-shared documents."""
        if self._user_scoped and user is not None:
            return Filter.by_property("owner_user").equal(str(user)) | Filter.by_property(
                "owner_user"
            ).equal(self._TENANT_LEVEL)
        return None

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
                    # FIELD tokenization: match the whole owner_user value exactly
                    # (UUIDs and the sentinel), not WORD-split tokens.
                    Property(
                        name="owner_user",
                        data_type=DataType.TEXT,
                        tokenization=Tokenization.FIELD,
                    ),
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
            owner_user = (
                str(document.owner_user_id) if document.owner_user_id else self._TENANT_LEVEL
            )
            properties = {
                "doc_id": document.doc_id,
                "content": document.content,
                "owner_user": owner_user,
            }
            vector = self._vector(f"{document.title} {document.content}")
            if collection.data.exists(object_id):
                collection.data.replace(uuid=object_id, properties=properties, vector=vector)
            else:
                collection.data.insert(properties=properties, uuid=object_id, vector=vector)

    def query(
        self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
    ) -> list[VectorHit]:
        collection = self._collection(tenant)
        user_filter = self._user_filter(user)
        result = collection.query.near_vector(
            self._vector(text),
            limit=k,
            return_metadata=MetadataQuery(distance=True),
            **({"filters": user_filter} if user_filter is not None else {}),
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
        # fetch_object_by_id is a direct UUID lookup with no server-side filter,
        # so a user-scoped store checks the owning user here (ADR-0006).
        if self._user_scoped and user is not None:
            owner_user = str(obj.properties.get("owner_user", self._TENANT_LEVEL))
            if owner_user not in (str(user), self._TENANT_LEVEL):
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
