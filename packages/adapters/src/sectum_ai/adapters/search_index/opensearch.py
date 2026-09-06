"""Live OpenSearch adapter: a full-text search index backed by an OpenSearch cluster.

Each tenant maps to its own OpenSearch index (``{prefix}-{tenant.hex}``) - a
keyword/full-text index derived from the RAG corpus, the tenth of the spec's "ten
hiding places", distinct from the embedding vector store. Class 11 erasure
verification seeds the tenant's content, then confirms a ``delete`` purges it from
the real index. With ``soft_delete=True`` a ``delete`` is acknowledged but leaves
the index in place - the residue Class 11 is built to catch.

Requires the ``opensearch`` optional dependency:
``pip install sectum-ai-adapters[opensearch]``.
"""

from uuid import UUID

from sectum_ai.adapters.base import Capability, SearchIndexAdapter
from sectum_ai.spec import AdapterError

# OpenSearch's default index.max_result_window; a tenant with more matching
# documents than this is refused rather than silently truncated.
_SEARCH_SIZE = 10000


class OpenSearchSearchIndex(SearchIndexAdapter):
    """A full-text search index backed by OpenSearch, one index per tenant.

    Scopes by tenant (one index per tenant), so a search reads only the calling
    tenant's index. ``soft_delete=True`` (reporting ``SOFT_DELETE``) makes a
    ``delete`` a no-op, leaving the tenant's index searchable - the Class 11
    erasure residue.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9200,
        *,
        user: str | None = None,
        password: str | None = None,
        use_ssl: bool = False,
        verify_certs: bool = True,
        name: str = "opensearch-search",
        prefix: str = "sectum-ai-search",
        soft_delete: bool = False,
    ) -> None:
        from opensearchpy import OpenSearch

        capabilities = {Capability.TEXT_SEARCH}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._client = OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=(user, password) if user and password else None,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
        )
        self._prefix = prefix
        self._soft_delete = soft_delete

    def _index_name(self, tenant: UUID) -> str:
        return f"{self._prefix}-{tenant.hex}"

    def _ensure_index(self, tenant: UUID) -> str:
        """Return the tenant's index name, creating it (a single ``content`` text field) first."""
        name = self._index_name(tenant)
        if not self._client.indices.exists(index=name):
            self._client.indices.create(
                index=name,
                body={"mappings": {"properties": {"content": {"type": "text"}}}},
            )
        return name

    def index(self, tenant: UUID, text: str) -> None:
        # refresh=True so the document is immediately searchable, matching the
        # synchronous in-memory fake: the erasure flow seeds then scans right away.
        self._client.index(index=self._ensure_index(tenant), body={"content": text}, refresh=True)

    def search(self, tenant: UUID, query: str) -> list[str]:
        index = self._index_name(tenant)
        if not self._client.indices.exists(index=index):
            return []
        response = self._client.search(
            index=index,
            body={
                "size": _SEARCH_SIZE,
                "track_total_hits": True,
                "query": {"match": {"content": query}},
            },
        )
        hits = response.get("hits", {})
        rows = hits.get("hits", [])
        total = hits.get("total", {})
        total_count = int(total.get("value", 0)) if isinstance(total, dict) else int(total or 0)
        contents = [str(hit.get("_source", {}).get("content", "")) for hit in rows]
        # A truncated page is not a scan: a document ranked past it read as absent.
        # But both callers ask "is this phrase still here", and a page that already
        # holds it answers that - refusing would lose a definite residual. So only
        # a MISS on a truncated page is refused, as on the eval-set and trace
        # backends.
        # Case-insensitive: two callers ask this, and the A3 subject check
        # casefolds where Class 11 does not. Suppress the refusal whenever EITHER
        # would count a hit - keyed on the stricter one, a full page carrying the
        # phrase in another case was refused instead of returned, and the subject
        # probe turns that into an exit-3 error over a genuine residual.
        needle = query.casefold()
        if total_count > len(rows) and not any(needle in text.casefold() for text in contents):
            raise AdapterError(
                f"OpenSearch matched {total_count} documents for the tenant but returned "
                f"{len(rows)}; a search-index scan that found nothing would be incomplete"
            )
        return contents

    def delete(self, tenant: UUID) -> None:
        # A soft-delete index acknowledges the request but keeps the documents
        # searchable - the residue Class 11 erasure verification is built to catch.
        if self._soft_delete:
            return
        index = self._index_name(tenant)
        if self._client.indices.exists(index=index):
            self._client.indices.delete(index=index)

    def close(self) -> None:
        """Close the OpenSearch client; call this when the adapter is done."""
        self._client.close()
