"""The Sectum AI adapter SDK (the engineering spec, section 11).

An adapter connects the substrate and probes to a real system. Every adapter
declares its family and a set of named capabilities, so a probe can state which
adapter capabilities it requires (a probe's ``requires_adapters``).

This module defines the family interfaces. Concrete adapters - the in-memory
``fake`` implementations and the live adapters (pgvector, Chroma, Langfuse, and
so on) - subclass the family base classes.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sectum_ai.spec import CorpusDocument, get_logger

_log = get_logger(__name__)


class AdapterFamily(StrEnum):
    """The families of system an adapter can connect to."""

    VECTOR_STORE = "vector_store"
    RAG_PIPELINE = "rag_pipeline"
    OBSERVABILITY = "observability"
    AGENT = "agent"
    MCP = "mcp"
    CACHE = "cache"
    MODEL = "model"
    MEMORY = "memory"
    SEARCH_INDEX = "search_index"
    EVAL_SET = "eval_set"
    BACKUP = "backup"


class Capability(StrEnum):
    """A named adapter capability; a probe's ``requires_adapters`` lists these."""

    SHARED_INDEX = "shared_index"
    PER_TENANT_NAMESPACE = "per_tenant_namespace"
    USER_SCOPED = "user_scoped"
    SOFT_DELETE = "soft_delete"
    TENANT_SCOPED_KEYS = "tenant_scoped_keys"
    TRACE_SEARCH = "trace_search"
    TEXT_SEARCH = "text_search"
    TOOL_INVOCATION = "tool_invocation"
    PER_TENANT_ADAPTER = "per_tenant_adapter"
    SHARED_WEIGHTS = "shared_weights"
    TENANT_SCOPED_TOOLS = "tenant_scoped_tools"
    PER_TENANT_MEMORY = "per_tenant_memory"
    SHARED_MEMORY = "shared_memory"
    SHARED_PREFIX_CACHE = "shared_prefix_cache"


class _AdapterValue(BaseModel):
    """Frozen base for adapter input/output value types."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class VectorHit(_AdapterValue):
    """A single result from a vector-store query."""

    doc_id: str
    tenant_id: UUID
    score: float
    content: str


class RagAnswer(_AdapterValue):
    """A RAG pipeline's answer plus the context it retrieved."""

    answer: str
    retrieved: tuple[VectorHit, ...] = ()


class TraceHit(_AdapterValue):
    """A single observability trace matching a marker search."""

    trace_id: str
    project: str
    snippet: str


class AgentResult(_AdapterValue):
    """The result of an agent run."""

    output: str
    tool_calls: tuple[str, ...] = ()


class McpResult(_AdapterValue):
    """The result of invoking an MCP tool."""

    tool: str
    output: str


class Adapter(ABC):
    """Base for every Sectum AI adapter.

    Concrete adapters inherit ``family`` from their family base class and pass a
    name and capability set to ``__init__``.
    """

    family: AdapterFamily

    def __init__(self, name: str, capabilities: frozenset[Capability] | None = None) -> None:
        self.name = name
        self.capabilities: frozenset[Capability] = (
            capabilities if capabilities is not None else frozenset()
        )

    def supports(self, capability: Capability) -> bool:
        """Return whether this adapter reports ``capability``."""
        return capability in self.capabilities


class VectorStoreAdapter(Adapter):
    """Adapter for a vector database (the engineering spec, section 11)."""

    family = AdapterFamily.VECTOR_STORE

    @abstractmethod
    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        """Insert or update a tenant's documents."""

    @abstractmethod
    def query(
        self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
    ) -> list[VectorHit]:
        """Return the top-``k`` matches for ``text`` in the principal's scope.

        ``user`` narrows the scope to one user within ``tenant`` (ADR-0006). A
        user-scoped store (reporting ``USER_SCOPED``) returns only that user's
        documents plus tenant-shared ones; a store that scopes by tenant alone
        ignores ``user`` and may surface another user's document - a leak.
        ``user=None`` is the tenant-level scope and is unchanged.
        """

    @abstractmethod
    def fetch(self, tenant: UUID, doc_id: str, *, user: UUID | None = None) -> VectorHit | None:
        """Fetch one document by id from the principal's reachable scope, or ``None``.

        A direct object lookup - the Class 1 BOLA primitive - distinct from the
        similarity ``query``: a tenant-isolated store returns ``None`` for
        another tenant's ``doc_id``; a shared index returns the document. With
        ``user`` set, a user-scoped store likewise returns ``None`` for another
        user's ``doc_id`` within the tenant (ADR-0006); ``user=None`` is the
        tenant-level lookup and is unchanged.
        """

    @abstractmethod
    def delete(self, tenant: UUID) -> None:
        """Delete all of a tenant's documents."""

    @abstractmethod
    def list_namespaces(self) -> list[str]:
        """List every namespace visible in the store."""


class RAGPipelineAdapter(Adapter):
    """Adapter for a retrieval-augmented-generation pipeline."""

    family = AdapterFamily.RAG_PIPELINE

    @abstractmethod
    def ask(self, tenant: UUID, query: str) -> RagAnswer:
        """Answer ``query`` from ``tenant``'s session."""


class ObservabilityAdapter(Adapter):
    """Adapter for an observability or tracing backend."""

    family = AdapterFamily.OBSERVABILITY

    @abstractmethod
    def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
        """Search a tenant's traces for ``marker``."""

    @abstractmethod
    def list_projects(self) -> list[str]:
        """List every observability project."""

    @abstractmethod
    def delete(self, tenant: UUID) -> None:
        """Delete every trace observable for ``tenant``.

        Class 11 (erasure verification) uses this to model the upstream stack
        purging the tenant's traces, then re-scans to confirm no residue
        remains.
        """

    def fetch_trace(self, tenant: UUID, trace_id: str) -> TraceHit | None:
        """Fetch one trace by id from the tenant's scope, or ``None``.

        The by-id existence primitive for the A3 data-subject erasure check
        (:class:`~sectum_ai.probes.subject_erasure.SubjectErasureProbe`): a
        tenant-scoped backend returns ``None`` for another tenant's - or an
        erased - trace id. Optional: an adapter that cannot look a trace up by id
        leaves this ``NotImplementedError`` raised, and the subject-erasure check
        reports the tracing surface ``NOT_COVERED`` rather than guessing.
        """
        raise NotImplementedError  # pragma: no cover - optional default; subclasses override


class AgentAdapter(Adapter):
    """Adapter for an agent framework."""

    family = AdapterFamily.AGENT

    @abstractmethod
    def run(self, tenant: UUID, task: str) -> AgentResult:
        """Run ``task`` as ``tenant`` and return the result."""


class MCPAdapter(Adapter):
    """Adapter for a Model Context Protocol server."""

    family = AdapterFamily.MCP

    @abstractmethod
    def list_tools(self) -> list[str]:
        """List the tools the MCP server exposes."""

    @abstractmethod
    def invoke(
        self, tenant: UUID, tool: str, arguments: dict[str, str], *, user: UUID | None = None
    ) -> McpResult:
        """Invoke ``tool`` within the principal's scope.

        With ``user`` set, a user-scoped server (reporting ``USER_SCOPED``)
        resolves only that user's resources within the tenant (ADR-0006); a
        tenant-scoped server ignores ``user`` and may resolve a sibling user's
        resource - a leak. ``user=None`` is the tenant-level call and is unchanged.
        """


class CacheAdapter(Adapter):
    """Adapter for a semantic or application cache."""

    family = AdapterFamily.CACHE

    @abstractmethod
    def get(self, tenant: UUID, key: str, *, user: UUID | None = None) -> str | None:
        """Return the cached value for ``key`` in the principal's scope.

        With ``user`` set, a user-scoped cache (reporting ``USER_SCOPED``) folds
        the user into the key so one user never reads another user's entry within
        the tenant (ADR-0006); a cache that scopes by tenant alone ignores
        ``user`` and serves a sibling user's value - a leak. ``user=None`` is the
        tenant-level scope and is unchanged.
        """

    @abstractmethod
    def set(self, tenant: UUID, key: str, value: str, *, user: UUID | None = None) -> None:
        """Cache ``value`` under ``key`` for the principal.

        ``user`` scopes the entry to one user within ``tenant`` on a user-scoped
        cache; ``user=None`` caches at the tenant level and is unchanged.
        """

    @abstractmethod
    def keys(self) -> list[str]:
        """List every raw cache key, across all tenants."""

    @abstractmethod
    def values(self, tenant: UUID) -> list[str]:
        """Return the cached values ``tenant`` can read.

        A tenant-scoped cache returns only the tenant's own values; an unscoped
        cache returns every value (the leak). Class 11 uses this to scan the
        cache surface for residual markers.
        """

    @abstractmethod
    def delete(self, tenant: UUID) -> None:
        """Delete ``tenant``'s cached entries.

        Class 11 (erasure verification) uses this to model the upstream stack
        honoring an erasure request on the cache surface.
        """


class ModelAdapter(Adapter):
    """Adapter for an inference model with per-tenant fine-tunes or adapters.

    Class 9 uses this to verify that one tenant's adapter does not influence
    another tenant's inference (the engineering spec, section 7).
    """

    family = AdapterFamily.MODEL

    @abstractmethod
    def train_adapter(
        self, tenant: UUID, texts: Sequence[str], *, user: UUID | None = None
    ) -> None:
        """Fit or attach a per-tenant (or per-user) adapter on ``texts``.

        ``user`` scopes the adapter to one user within ``tenant`` (ADR-0006);
        ``user=None`` is the tenant-level adapter and is unchanged.
        """

    @abstractmethod
    def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
        """Run inference for the principal and return the completion.

        The return value is the COMPLETION ONLY - never an echo of the prompt.
        The erasure probe prompts with the canary it scans for, so an adapter
        that echoed its prompt would fabricate a confirmed "residual" about data
        that was never stored.

        With ``user`` set, a user-scoped model (reporting ``USER_SCOPED``) recalls
        only that user's own adapter within the tenant; a model that scopes by
        tenant alone ignores ``user`` and may surface a sibling user's memorized
        content - a leak. ``user=None`` is the tenant-level call and is unchanged.
        """

    def served_by(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> UUID | None:
        """Return the tenant whose adapter actually served this inference, if known.

        Class 9 verifies routing correctness: a value other than ``tenant`` means
        one tenant's request was served by another tenant's adapter (mis-routing,
        the spec section 7 "routing assertion failures"). A real adapter that
        cannot introspect its routing returns ``None`` (unknown), which is never a
        finding; the in-memory fake attributes it precisely so the assertion is
        testable. Not abstract, so existing adapters need no change.
        """
        return None

    @abstractmethod
    def measure_latency(self, tenant: UUID, prompt: str) -> float:
        """Return the inference latency in milliseconds for ``prompt``.

        Class 5 uses this to detect a KV prefix-cache timing side channel.
        """

    @abstractmethod
    def delete(self, tenant: UUID) -> None:
        """Delete ``tenant``'s per-tenant adapter / fine-tune.

        Class 11 (erasure verification) uses this to model the upstream stack
        honoring an erasure request on the model surface.
        """


class MemoryAdapter(Adapter):
    """Adapter for a long-term or agent memory store.

    Class 8 uses this to verify that one tenant's stored memory does not surface
    in another tenant's session (the engineering spec, section 7).
    """

    family = AdapterFamily.MEMORY

    @abstractmethod
    def remember(self, tenant: UUID, text: str, *, user: UUID | None = None) -> None:
        """Persist ``text`` in the principal's memory store.

        ``user`` scopes the entry to one user within ``tenant`` (ADR-0006);
        ``user=None`` persists at the tenant level and is unchanged.
        """

    @abstractmethod
    def recall(self, tenant: UUID, query: str, *, user: UUID | None = None) -> list[str]:
        """Return memory entries the principal can recall for ``query``.

        With ``user`` set, a user-scoped store (reporting ``USER_SCOPED``) recalls
        only that user's own entries plus tenant-shared ones; a store that scopes
        by tenant alone ignores ``user`` and recalls a sibling user's note - a
        leak. ``user=None`` is the tenant-level recall and is unchanged.
        """

    @abstractmethod
    def delete(self, tenant: UUID) -> None:
        """Delete ``tenant``'s memory entries.

        Class 11 (erasure verification) uses this to model the upstream stack
        honoring an erasure request on the memory surface.
        """


class SearchIndexAdapter(Adapter):
    """Adapter for a full-text search index derived from the RAG corpus.

    A search index is the tenth of the spec's "ten hiding places": a keyword/
    full-text index (Elasticsearch/OpenSearch and the like) built from the
    corpus, distinct from the embedding vector store. Class 11 uses it to confirm
    a tenant's content does not survive in the derived index after an erasure
    request (the engineering spec, section 7).
    """

    family = AdapterFamily.SEARCH_INDEX

    @abstractmethod
    def index(self, tenant: UUID, text: str) -> None:
        """Index ``text`` as a document in ``tenant``'s scope.

        Class 11 (erasure verification) seeds the derived index with the tenant's
        content through this, then confirms a ``delete`` purges it. A live index
        must make the entry immediately searchable so the pre/post scan is reliable.
        """

    @abstractmethod
    def search(self, tenant: UUID, query: str) -> list[str]:
        """Return the indexed document snippets in ``tenant``'s scope matching ``query``."""

    @abstractmethod
    def delete(self, tenant: UUID) -> None:
        """Delete ``tenant``'s indexed documents.

        Class 11 (erasure verification) uses this to model the upstream stack
        purging the tenant's entries from the search index, then re-scans to
        confirm no residue remains.
        """


class EvalSetAdapter(Adapter):
    """Adapter for an evaluation / golden test-fixture set built from tenant data.

    Eval golden sets are the fourth of the spec's "ten hiding places": curated
    test fixtures and eval datasets that may copy tenant content out of the
    production corpus. Class 11 uses this to confirm a tenant's content does not
    survive in the eval set after an erasure request (the engineering spec,
    section 7).
    """

    family = AdapterFamily.EVAL_SET

    @abstractmethod
    def search(self, tenant: UUID, query: str) -> list[str]:
        """Return the eval-set entries in ``tenant``'s scope matching ``query``."""

    @abstractmethod
    def delete(self, tenant: UUID) -> None:
        """Delete ``tenant``'s eval-set entries.

        Class 11 (erasure verification) uses this to model the upstream stack
        purging the tenant's fixtures from the eval set, then re-scans to confirm
        no residue remains.
        """


class BackupAdapter(Adapter):
    """Adapter for a backup snapshot / export store derived from tenant data.

    Backup snapshots are the seventh of the spec's "ten hiding places": a tenant's
    data routinely survives a primary-store erasure inside a backup or export.
    Class 11 uses this to confirm the data does not survive there after an erasure
    request - and, because many backup stores are immutable or expose no
    per-tenant delete, to record the surface as *attestable-with-caveat* (the
    engineering spec, section 7, hiding place #7) when no programmatic purge exists.
    """

    family = AdapterFamily.BACKUP

    @abstractmethod
    def search(self, tenant: UUID, query: str) -> list[str]:
        """Return the backup snippets in ``tenant``'s scope matching ``query``."""

    @abstractmethod
    def delete(self, tenant: UUID) -> None:
        """Delete ``tenant``'s data from the backups.

        Class 11 re-scans afterward to confirm no residue remains. A store with no
        per-tenant purge raises ``ErasureUnsupported`` so the surface is recorded
        as attestable-with-caveat rather than a false PASS.
        """


class AdapterRegistry:
    """An in-memory registry of adapter instances, keyed by adapter name."""

    def __init__(self) -> None:
        self._adapters: dict[str, Adapter] = {}

    def register(self, adapter: Adapter) -> None:
        """Register ``adapter`` under its name."""
        if adapter.name in self._adapters:
            raise ValueError(f"adapter already registered: {adapter.name}")
        self._adapters[adapter.name] = adapter
        # Name, family, and capability flags only - adapters never hold or log
        # credentials (the engineering spec, sections 11 and 16). DEBUG-only.
        _log.debug(
            "adapter.registered",
            adapter=adapter.name,
            family=adapter.family.value,
            capabilities=sorted(c.value for c in adapter.capabilities),
        )

    def get(self, name: str) -> Adapter:
        """Return the adapter registered as ``name``."""
        return self._adapters[name]

    def by_family(self, family: AdapterFamily) -> list[Adapter]:
        """Return every registered adapter in ``family``, ordered by name."""
        return [
            self._adapters[name]
            for name in sorted(self._adapters)
            if self._adapters[name].family is family
        ]

    def all(self) -> list[Adapter]:
        """Return every registered adapter, ordered by name."""
        return [self._adapters[name] for name in sorted(self._adapters)]
