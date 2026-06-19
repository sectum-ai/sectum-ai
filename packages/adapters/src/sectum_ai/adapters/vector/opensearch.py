"""Live OpenSearch adapter: a vector store backed by an OpenSearch cluster.

Each tenant maps to its own OpenSearch index (``{prefix}-{tenant.hex}``), so this
adapter is per-tenant isolated: a query or a fetch is scoped to the calling
tenant's index. Vectors are indexed as ``knn_vector`` fields (the Lucene engine,
cosine space) and searched with the k-NN query; embeddings are computed by the
caller's embedder and passed to OpenSearch explicitly. Each document id is folded
into a deterministic ``_id`` (a UUIDv5) so an index call is idempotent and a fetch
is a direct id lookup; the original ``doc_id`` is preserved in the document source.

Requires the ``opensearch`` optional dependency:
``pip install sectum-ai-adapters[opensearch]``.
"""

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID, uuid5

from sectum_ai.adapters.base import Capability, VectorHit, VectorStoreAdapter
from sectum_ai.spec import AdapterError, CorpusDocument

Embedder = Callable[[str], Sequence[float]]
"""A function turning text into an embedding vector."""

_POINT_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
"""A fixed namespace for deriving a deterministic document id from a ``doc_id``."""


class OpenSearchVectorStore(VectorStoreAdapter):
    """A vector store backed by OpenSearch, one index per tenant.

    Scopes by tenant (one index per tenant). With ``user_scoped=True`` it records
    each document's owning user in the source and filters ``query`` (a k-NN
    pre-filter) and ``fetch`` (post-lookup) to the caller's own documents plus
    tenant-shared ones (reporting ``USER_SCOPED``), so one user cannot retrieve a
    sibling user's document within the tenant (ADR-0006). ``user=None`` is the
    tenant-level scope and is unchanged. Tenant-level documents carry an empty
    ``owner_user`` sentinel so the filter can match them.
    """

    _TENANT_LEVEL = ""
    """The ``owner_user`` source sentinel for a tenant-level (unowned) document."""

    def __init__(
        self,
        embed: Embedder,
        *,
        dim: int,
        host: str = "localhost",
        port: int = 9200,
        user: str | None = None,
        password: str | None = None,
        use_ssl: bool = False,
        verify_certs: bool = False,
        name: str = "opensearch",
        prefix: str = "sectum-ai",
        user_scoped: bool = False,
    ) -> None:
        from opensearchpy import OpenSearch

        capabilities = {Capability.PER_TENANT_NAMESPACE}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        super().__init__(name, frozenset(capabilities))
        self._client = OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=(user, password) if user and password else None,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
        )
        self._embed = embed
        self._dim = dim
        self._prefix = prefix
        self._user_scoped = user_scoped

    def _index_name(self, tenant: UUID) -> str:
        return f"{self._prefix}-{tenant.hex}"

    def _vector(self, text: str) -> list[float]:
        return [float(value) for value in self._embed(text)]

    @staticmethod
    def _doc_id(doc_id: str) -> str:
        return str(uuid5(_POINT_NAMESPACE, doc_id))

    def _ensure_index(self, tenant: UUID) -> str:
        """Return the tenant's index name, creating the index on first use."""
        name = self._index_name(tenant)
        if not self._client.indices.exists(index=name):
            self._client.indices.create(
                index=name,
                body={
                    "settings": {"index": {"knn": True}},
                    "mappings": {
                        "properties": {
                            "vector": {
                                "type": "knn_vector",
                                "dimension": self._dim,
                                "method": {
                                    "name": "hnsw",
                                    "space_type": "cosinesimil",
                                    "engine": "lucene",
                                },
                            },
                            "doc_id": {"type": "keyword"},
                            "content": {"type": "text"},
                            "owner_user": {"type": "keyword"},
                        }
                    },
                },
            )
        return name

    def _user_clause(self, user: UUID | None) -> Any:
        """A term filter for the user's own + tenant-shared documents, or ``None``."""
        if self._user_scoped and user is not None:
            return {"terms": {"owner_user": [str(user), self._TENANT_LEVEL]}}
        return None

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        items = list(documents)
        if not items:
            return
        index = self._ensure_index(tenant)
        for document in items:
            self._client.index(
                index=index,
                id=self._doc_id(document.doc_id),
                body={
                    "vector": self._vector(f"{document.title} {document.content}"),
                    "doc_id": document.doc_id,
                    "content": document.content,
                    "owner_user": (
                        str(document.owner_user_id)
                        if document.owner_user_id
                        else self._TENANT_LEVEL
                    ),
                },
                refresh=True,
            )

    def query(
        self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
    ) -> list[VectorHit]:
        index = self._index_name(tenant)
        if not self._client.indices.exists(index=index):
            return []
        knn: dict[str, Any] = {"vector": self._vector(text), "k": k}
        clause = self._user_clause(user)
        if clause is not None:
            knn["filter"] = {"bool": {"filter": [clause]}}
        response = self._client.search(
            index=index, body={"size": k, "query": {"knn": {"vector": knn}}}
        )
        hits: list[VectorHit] = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            hits.append(
                VectorHit(
                    doc_id=str(source.get("doc_id", hit.get("_id", ""))),
                    tenant_id=tenant,
                    score=float(hit.get("_score", 0.0)),
                    content=str(source.get("content", "")),
                )
            )
        return hits

    def fetch(self, tenant: UUID, doc_id: str, *, user: UUID | None = None) -> VectorHit | None:
        from opensearchpy.exceptions import NotFoundError

        index = self._index_name(tenant)
        if not self._client.indices.exists(index=index):
            return None
        try:
            record = self._client.get(index=index, id=self._doc_id(doc_id))
        except NotFoundError:
            return None
        source = record.get("_source", {})
        # get is a direct id lookup with no server-side filter, so a user-scoped
        # store checks the owning user here (ADR-0006).
        if self._user_scoped and user is not None:
            owner_user = str(source.get("owner_user", self._TENANT_LEVEL))
            if owner_user not in (str(user), self._TENANT_LEVEL):
                return None
        return VectorHit(
            doc_id=str(source.get("doc_id", doc_id)),
            tenant_id=tenant,
            score=1.0,
            content=str(source.get("content", "")),
        )

    def delete(self, tenant: UUID) -> None:
        index = self._index_name(tenant)
        if self._client.indices.exists(index=index):
            self._client.indices.delete(index=index)

    def list_namespaces(self) -> list[str]:
        from opensearchpy.exceptions import NotFoundError

        try:
            indices = self._client.indices.get(index=f"{self._prefix}-*")
        except NotFoundError:
            return []
        except Exception as error:
            raise AdapterError(f"failed to list OpenSearch indices: {error}") from error
        return sorted(indices)

    def close(self) -> None:
        """Close the OpenSearch client; call this when the adapter is done."""
        self._client.close()
