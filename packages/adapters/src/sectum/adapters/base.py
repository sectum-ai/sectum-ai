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

from sectum.spec import CorpusDocument


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


class Capability(StrEnum):
    """A named adapter capability; a probe's ``requires_adapters`` lists these."""

    SHARED_INDEX = "shared_index"
    PER_TENANT_NAMESPACE = "per_tenant_namespace"
    USER_SCOPED = "user_scoped"
    SOFT_DELETE = "soft_delete"
    TENANT_SCOPED_KEYS = "tenant_scoped_keys"
    TRACE_SEARCH = "trace_search"
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
    def invoke(self, tenant: UUID, tool: str, arguments: dict[str, str]) -> McpResult:
        """Invoke ``tool`` within ``tenant``'s scope."""


class CacheAdapter(Adapter):
    """Adapter for a semantic or application cache."""

    family = AdapterFamily.CACHE

    @abstractmethod
    def get(self, tenant: UUID, key: str) -> str | None:
        """Return the cached value for ``key`` in ``tenant``'s scope."""

    @abstractmethod
    def set(self, tenant: UUID, key: str, value: str) -> None:
        """Cache ``value`` under ``key`` for ``tenant``."""

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
    def train_adapter(self, tenant: UUID, texts: Sequence[str]) -> None:
        """Fit or attach ``tenant``'s per-tenant adapter on ``texts``."""

    @abstractmethod
    def infer(self, tenant: UUID, prompt: str) -> str:
        """Run inference for ``tenant`` and return the completion."""

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
    def remember(self, tenant: UUID, text: str) -> None:
        """Persist ``text`` in ``tenant``'s memory store."""

    @abstractmethod
    def recall(self, tenant: UUID, query: str) -> list[str]:
        """Return memory entries ``tenant`` can recall for ``query``."""

    @abstractmethod
    def delete(self, tenant: UUID) -> None:
        """Delete ``tenant``'s memory entries.

        Class 11 (erasure verification) uses this to model the upstream stack
        honoring an erasure request on the memory surface.
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
