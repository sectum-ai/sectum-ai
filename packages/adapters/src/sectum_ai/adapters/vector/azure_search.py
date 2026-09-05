"""Live Azure AI Search adapter: a vector store backed by an Azure AI Search service.

Each tenant maps to its own search index (``{prefix}-{tenant.hex}``), so this
adapter is per-tenant isolated: a query or a fetch is scoped to the calling
tenant's index. Vectors are stored in a ``Collection(Edm.Single)`` field (HNSW,
cosine) and searched with a vector query; embeddings are computed by the caller's
embedder and passed to Azure explicitly. Each document id is folded into a
deterministic key (a UUIDv5) so an upload is idempotent and a fetch is a direct
key lookup; the original ``doc_id`` is preserved as a field.

Azure AI Search is a managed cloud service with no local emulator, so this adapter
has no docker-compose backend: its integration test is skipped unless
``SECTUM_AZURE_SEARCH_ENDPOINT``/``SECTUM_AZURE_SEARCH_KEY`` point at a real
service (mirroring the Pinecone adapter).

Requires the ``azure-search`` optional dependency:
``pip install sectum-ai-adapters[azure-search]``.
"""

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID, uuid5

from sectum_ai.adapters.base import Capability, VectorHit, VectorStoreAdapter
from sectum_ai.adapters.vector._settle import settle
from sectum_ai.spec import AdapterError, CorpusDocument

Embedder = Callable[[str], Sequence[float]]
"""A function turning text into an embedding vector."""

_POINT_NAMESPACE = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
"""A fixed namespace for deriving a deterministic document key from a ``doc_id``."""


class AzureSearchVectorStore(VectorStoreAdapter):
    """A vector store backed by Azure AI Search, one index per tenant.

    Scopes by tenant (one index per tenant). With ``user_scoped=True`` it records
    each document's owning user and filters ``query`` (an OData filter) and
    ``fetch`` (post-lookup) to the caller's own documents plus tenant-shared ones
    (reporting ``USER_SCOPED``), so one user cannot retrieve a sibling user's
    document within the tenant (ADR-0006). ``user=None`` is the tenant-level scope
    and is unchanged. Tenant-level documents carry an empty ``owner_user``
    sentinel so the filter can match them.
    """

    _TENANT_LEVEL = ""
    """The ``owner_user`` field sentinel for a tenant-level (unowned) document."""

    _VECTOR_PROFILE = "sectum-ai-vector-profile"
    _VECTOR_ALGORITHM = "sectum-ai-hnsw"

    def __init__(
        self,
        embed: Embedder,
        *,
        dim: int,
        endpoint: str,
        api_key: str,
        name: str = "azure-search",
        prefix: str = "sectum-ai",
        user_scoped: bool = False,
    ) -> None:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.indexes import SearchIndexClient

        capabilities = {Capability.PER_TENANT_NAMESPACE}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        super().__init__(name, frozenset(capabilities))
        self._endpoint = endpoint
        self._credential = AzureKeyCredential(api_key)
        self._index_client = SearchIndexClient(endpoint, self._credential)
        self._embed = embed
        self._dim = dim
        self._prefix = prefix
        self._user_scoped = user_scoped

    def _index_name(self, tenant: UUID) -> str:
        return f"{self._prefix}-{tenant.hex}"

    def _vector(self, text: str) -> list[float]:
        return [float(value) for value in self._embed(text)]

    @staticmethod
    def _key(doc_id: str) -> str:
        return str(uuid5(_POINT_NAMESPACE, doc_id))

    def _client(self, index: str) -> Any:
        from azure.search.documents import SearchClient

        return SearchClient(self._endpoint, index, self._credential)

    def _index_exists(self, name: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._index_client.get_index(name)
        except ResourceNotFoundError:
            return False
        return True

    def _ensure_index(self, tenant: UUID) -> str:
        """Return the tenant's index name, creating the index on first use."""
        from azure.search.documents.indexes.models import (
            HnswAlgorithmConfiguration,
            SearchableField,
            SearchField,
            SearchFieldDataType,
            SearchIndex,
            SimpleField,
            VectorSearch,
            VectorSearchProfile,
        )

        name = self._index_name(tenant)
        if self._index_exists(name):
            return name
        fields = [
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="doc_id", type=SearchFieldDataType.String, filterable=True),
            SearchableField(name="content", type=SearchFieldDataType.String),
            SimpleField(name="owner_user", type=SearchFieldDataType.String, filterable=True),
            SearchField(
                name="vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self._dim,
                vector_search_profile_name=self._VECTOR_PROFILE,
            ),
        ]
        vector_search = VectorSearch(
            profiles=[
                VectorSearchProfile(
                    name=self._VECTOR_PROFILE,
                    algorithm_configuration_name=self._VECTOR_ALGORITHM,
                )
            ],
            algorithms=[HnswAlgorithmConfiguration(name=self._VECTOR_ALGORITHM)],
        )
        self._index_client.create_index(
            SearchIndex(name=name, fields=fields, vector_search=vector_search)
        )
        return name

    def _user_filter(self, user: UUID | None) -> str | None:
        """An OData filter for the user's own + tenant-shared documents, or ``None``."""
        if self._user_scoped and user is not None:
            return f"owner_user eq '{user}' or owner_user eq '{self._TENANT_LEVEL}'"
        return None

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        items = list(documents)
        if not items:
            return
        index = self._ensure_index(tenant)
        client = self._client(index)
        client.upload_documents(
            documents=[
                {
                    "id": self._key(document.doc_id),
                    "doc_id": document.doc_id,
                    "content": document.content,
                    "owner_user": (
                        str(document.owner_user_id)
                        if document.owner_user_id
                        else self._TENANT_LEVEL
                    ),
                    "vector": self._vector(f"{document.title} {document.content}"),
                }
                for document in items
            ]
        )
        # Azure indexes asynchronously; see _settle for what an early read cost.
        last_key = self._key(items[-1].doc_id)
        settle(
            lambda: self._document_present(client, last_key),
            f"Azure AI Search index {index} did not reflect the upload",
        )

    @staticmethod
    def _document_present(client: Any, key: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            client.get_document(key=key)
        except ResourceNotFoundError:
            return False
        return True

    def query(
        self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
    ) -> list[VectorHit]:
        from azure.search.documents.models import VectorizedQuery

        index = self._index_name(tenant)
        if not self._index_exists(index):
            return []
        results = self._client(index).search(
            search_text=None,
            vector_queries=[
                VectorizedQuery(vector=self._vector(text), k_nearest_neighbors=k, fields="vector")
            ],
            filter=self._user_filter(user),
            top=k,
        )
        hits: list[VectorHit] = []
        for record in results:
            hits.append(
                VectorHit(
                    doc_id=str(record.get("doc_id", record.get("id", ""))),
                    tenant_id=tenant,
                    score=float(record.get("@search.score", 0.0)),
                    content=str(record.get("content", "")),
                )
            )
        return hits

    def fetch(self, tenant: UUID, doc_id: str, *, user: UUID | None = None) -> VectorHit | None:
        from azure.core.exceptions import ResourceNotFoundError

        index = self._index_name(tenant)
        if not self._index_exists(index):
            return None
        try:
            record = self._client(index).get_document(key=self._key(doc_id))
        except ResourceNotFoundError:
            return None
        # get_document is a direct key lookup with no server-side filter, so a
        # user-scoped store checks the owning user here (ADR-0006).
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
        index = self._index_name(tenant)
        if self._index_exists(index):
            self._index_client.delete_index(index)
            settle(
                lambda: not self._index_exists(index),
                f"Azure AI Search index {index} still exists after the delete",
            )

    def list_namespaces(self) -> list[str]:
        try:
            return sorted(self._index_client.list_index_names())
        except Exception as error:
            raise AdapterError(f"failed to list Azure AI Search indexes: {error}") from error

    def close(self) -> None:
        """Close the Azure AI Search admin client; call this when the adapter is done."""
        self._index_client.close()
