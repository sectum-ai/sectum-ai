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

from sectum_ai.adapters.base import Capability, VectorHit, VectorStoreAdapter
from sectum_ai.adapters.vector._settle import settle
from sectum_ai.spec import CorpusDocument

Embedder = Callable[[str], Sequence[float]]
"""A function turning text into an embedding vector."""


class PineconeVectorStore(VectorStoreAdapter):
    """A vector store backed by a Pinecone index, one namespace per tenant.

    Construct it with an open Pinecone ``Index`` object (or use
    :meth:`connect`). The index is held opaquely so the adapter can be tested
    against an in-memory stand-in without the ``pinecone`` package.

    Scopes by tenant (one namespace per tenant). With ``user_scoped=True`` it
    records each document's owning user in metadata (a non-empty sentinel marks
    tenant-level documents) and filters ``query`` (a metadata filter) and
    ``fetch`` (post-lookup) to the caller's own documents plus tenant-shared ones
    (reporting ``USER_SCOPED``), so one user cannot retrieve a sibling user's
    document within the tenant (ADR-0006). ``user=None`` is the tenant-level
    scope and is unchanged.
    """

    _TENANT_LEVEL = "tenant-level"
    """The ``owner_user`` metadata sentinel for a tenant-level (unowned) document.

    Non-empty on purpose: this adapter's per-user behavior is verified offline
    against a mock, so the sentinel avoids any empty-string edge in a live
    Pinecone ``$in`` filter (the kind of backend quirk that bit Weaviate).
    """

    def __init__(
        self, index: Any, embed: Embedder, *, name: str = "pinecone", user_scoped: bool = False
    ) -> None:
        capabilities = {Capability.PER_TENANT_NAMESPACE}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        super().__init__(name, frozenset(capabilities))
        self._user_scoped = user_scoped
        # Without a user scope nothing user-specific reaches the backend: a call
        # made as a user is the tenant's call, so user-level steps are not run.
        self.carries_user = user_scoped
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
        user_scoped: bool = False,
    ) -> Self:
        """Open a Pinecone index by name (or host) and return the adapter.

        The ``pinecone`` package is imported here, on the live path only, so the
        adapter module and its mock-backed test do not require it.
        """
        from pinecone import Pinecone

        client = Pinecone(api_key=api_key)
        index = client.Index(host=host) if host else client.Index(index_name)
        return cls(index, embed, name=name, user_scoped=user_scoped)

    def _vector(self, text: str) -> list[float]:
        return [float(value) for value in self._embed(text)]

    @staticmethod
    def _metadata(item: Any) -> dict[str, Any]:
        # Pinecone's metadata is optional: a vector upserted without it has no
        # metadata attribute at all (the SDK model raises AttributeError), so a
        # foreign vector must not crash a read.
        return getattr(item, "metadata", None) or {}

    def _user_filter(self, user: UUID | None) -> dict[str, Any] | None:
        """A Pinecone metadata filter for the user's own + tenant-shared documents."""
        if self._user_scoped and user is not None:
            return {"owner_user": {"$in": [str(user), self._TENANT_LEVEL]}}
        return None

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        vectors = [
            {
                "id": document.doc_id,
                "values": self._vector(f"{document.title} {document.content}"),
                "metadata": {
                    "doc_id": document.doc_id,
                    "content": document.content,
                    "owner_user": (
                        str(document.owner_user_id)
                        if document.owner_user_id
                        else self._TENANT_LEVEL
                    ),
                },
            }
            for document in documents
        ]
        if vectors:
            self._index.upsert(vectors=vectors, namespace=tenant.hex)
            # Pinecone is eventually consistent: a probe that queried right after
            # the upsert saw nothing (no baseline, INCONCLUSIVE), and one that
            # re-scanned right after a delete saw the not-yet-purged vectors as a
            # RESIDUAL erasure failure. Wait, bounded, for the write to land.
            last = vectors[-1]["id"]
            settle(
                lambda: last in self._index.fetch(ids=[last], namespace=tenant.hex).vectors,
                f"Pinecone namespace {tenant.hex} did not reflect the upsert",
            )

    def query(
        self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
    ) -> list[VectorHit]:
        user_filter = self._user_filter(user)
        response = self._index.query(
            vector=self._vector(text),
            top_k=k,
            namespace=tenant.hex,
            include_metadata=True,
            **({"filter": user_filter} if user_filter is not None else {}),
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

    def fetch(self, tenant: UUID, doc_id: str, *, user: UUID | None = None) -> VectorHit | None:
        response = self._index.fetch(ids=[doc_id], namespace=tenant.hex)
        vector = response.vectors.get(doc_id)
        if vector is None:
            return None
        metadata = self._metadata(vector)
        # fetch is a direct id lookup with no server-side filter, so a user-scoped
        # store checks the owning user here (ADR-0006).
        if self._user_scoped and user is not None:
            owner_user = str(metadata.get("owner_user", self._TENANT_LEVEL))
            if owner_user not in (str(user), self._TENANT_LEVEL):
                return None
        return VectorHit(
            doc_id=str(metadata.get("doc_id", doc_id)),
            tenant_id=tenant,
            score=1.0,
            content=str(metadata.get("content", "")),
        )

    def delete(self, tenant: UUID) -> None:
        self._index.delete(delete_all=True, namespace=tenant.hex)
        settle(
            lambda: self._namespace_count(tenant) == 0,
            f"Pinecone namespace {tenant.hex} still holds vectors after the delete",
        )

    def _namespace_count(self, tenant: UUID) -> int:
        stats = self._index.describe_index_stats().namespaces
        summary = stats.get(tenant.hex) if hasattr(stats, "get") else None
        if summary is None:
            return 0
        return int(getattr(summary, "vector_count", None) or summary.get("vector_count", 0))

    def list_namespaces(self) -> list[str]:
        stats = self._index.describe_index_stats()
        return sorted(stats.namespaces)
