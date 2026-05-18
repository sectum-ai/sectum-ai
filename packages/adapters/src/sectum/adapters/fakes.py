"""In-memory fake adapters for tests and offline runs.

Every adapter family ships a deterministic in-memory fake (the engineering
spec, section 11). The fakes satisfy the family interfaces and report their
capabilities honestly, so they pass the adapter contract suite and serve as
isolated-stack baselines for probe tests.

The fakes are consolidated in this module for now; per-family modules
(``vector/pgvector.py`` and so on) are introduced alongside the live adapters.
"""

import re
from collections.abc import Sequence
from uuid import UUID

from sectum.adapters.base import (
    AgentAdapter,
    AgentResult,
    CacheAdapter,
    Capability,
    MCPAdapter,
    McpResult,
    ObservabilityAdapter,
    RagAnswer,
    RAGPipelineAdapter,
    TraceHit,
    VectorHit,
    VectorStoreAdapter,
)
from sectum.spec import CorpusDocument

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MCP_TOOLS = ("echo", "lookup")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _overlap(query_tokens: set[str], document: CorpusDocument) -> float:
    document_tokens = _tokens(f"{document.title} {document.content}")
    return float(len(query_tokens & document_tokens))


def _rank(query: str, candidates: list[tuple[UUID, CorpusDocument]], k: int) -> list[VectorHit]:
    """Score candidates by lexical overlap and return the top ``k`` hits."""
    query_tokens = _tokens(query)
    hits: list[VectorHit] = []
    for owner, document in candidates:
        score = _overlap(query_tokens, document)
        if score > 0.0:
            hits.append(
                VectorHit(
                    doc_id=document.doc_id,
                    tenant_id=owner,
                    score=score,
                    content=document.content,
                )
            )
    hits.sort(key=lambda hit: (-hit.score, hit.doc_id))
    return hits[:k]


class FakeVectorStore(VectorStoreAdapter):
    """A deterministic in-memory vector store.

    With ``shared_index=True`` it models a single index shared across tenants:
    a query from one tenant can surface another tenant's documents. With
    ``soft_delete=True`` a ``delete`` call is acknowledged but leaves the
    vectors orphaned and still queryable. Both default to off.
    """

    def __init__(
        self,
        name: str = "fake-vector",
        *,
        shared_index: bool = False,
        soft_delete: bool = False,
    ) -> None:
        scope = Capability.SHARED_INDEX if shared_index else Capability.PER_TENANT_NAMESPACE
        capabilities = {scope}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._shared_index = shared_index
        self._soft_delete = soft_delete
        self._documents: dict[UUID, list[CorpusDocument]] = {}

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        self._documents.setdefault(tenant, []).extend(documents)

    def query(self, tenant: UUID, text: str, k: int = 5) -> list[VectorHit]:
        if self._shared_index:
            candidates = [
                (owner, document)
                for owner, documents in self._documents.items()
                for document in documents
            ]
        else:
            candidates = [(tenant, document) for document in self._documents.get(tenant, [])]
        return _rank(text, candidates, k)

    def delete(self, tenant: UUID) -> None:
        # A soft-delete store acknowledges the request but leaves the vectors
        # orphaned and still queryable - the residue Class 11 is built to catch.
        if self._soft_delete:
            return
        self._documents.pop(tenant, None)

    def list_namespaces(self) -> list[str]:
        if self._shared_index:
            return ["shared"]
        return sorted(str(tenant) for tenant in self._documents)


class FakeRAGPipeline(RAGPipelineAdapter):
    """A deterministic in-memory RAG pipeline.

    Call ``index`` - a test helper beyond the adapter interface - to populate a
    tenant's corpus before calling ``ask``.
    """

    def __init__(self, name: str = "fake-rag") -> None:
        super().__init__(name)
        self._documents: dict[UUID, list[CorpusDocument]] = {}

    def index(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        """Populate a tenant's corpus (test helper; not part of the interface)."""
        self._documents.setdefault(tenant, []).extend(documents)

    def ask(self, tenant: UUID, query: str) -> RagAnswer:
        candidates = [(tenant, document) for document in self._documents.get(tenant, [])]
        retrieved = tuple(_rank(query, candidates, k=3))
        if not retrieved:
            return RagAnswer(answer="no relevant context found", retrieved=())
        return RagAnswer(answer=" | ".join(hit.content for hit in retrieved), retrieved=retrieved)


class FakeObservability(ObservabilityAdapter):
    """A deterministic in-memory tracing backend."""

    def __init__(self, name: str = "fake-observability") -> None:
        super().__init__(name, frozenset({Capability.TRACE_SEARCH}))
        self._traces: dict[UUID, list[tuple[str, str, str]]] = {}

    def record(self, tenant: UUID, project: str, text: str) -> str:
        """Record a trace (test helper; not part of the interface)."""
        traces = self._traces.setdefault(tenant, [])
        trace_id = f"trace-{tenant.hex[:8]}-{len(traces):04d}"
        traces.append((trace_id, project, text))
        return trace_id

    def search_traces(self, tenant: UUID, marker: str) -> list[TraceHit]:
        return [
            TraceHit(trace_id=trace_id, project=project, snippet=text)
            for trace_id, project, text in self._traces.get(tenant, [])
            if marker in text
        ]

    def list_projects(self) -> list[str]:
        return sorted({project for traces in self._traces.values() for _, project, _ in traces})


class FakeAgent(AgentAdapter):
    """A deterministic in-memory agent.

    It echoes the task and records one notional tool call - enough to exercise
    the adapter contract.
    """

    def __init__(self, name: str = "fake-agent") -> None:
        super().__init__(name, frozenset({Capability.TOOL_INVOCATION}))

    def run(self, tenant: UUID, task: str) -> AgentResult:
        return AgentResult(output=f"tenant {tenant} completed: {task}", tool_calls=("noop",))


class FakeMCP(MCPAdapter):
    """A deterministic in-memory MCP server exposing two tools."""

    def __init__(self, name: str = "fake-mcp") -> None:
        super().__init__(name, frozenset({Capability.TOOL_INVOCATION}))

    def list_tools(self) -> list[str]:
        return list(_MCP_TOOLS)

    def invoke(self, tenant: UUID, tool: str, arguments: dict[str, str]) -> McpResult:
        if tool not in _MCP_TOOLS:
            raise ValueError(f"unknown tool: {tool}")
        if tool == "echo":
            return McpResult(tool=tool, output=arguments.get("text", ""))
        return McpResult(tool=tool, output=f"tenant {tenant} lookup: {arguments.get('key', '')}")


class FakeCache(CacheAdapter):
    """A deterministic in-memory cache.

    With ``tenant_scoped=True`` cache keys incorporate the tenant, so tenants
    cannot read each other's entries. With ``tenant_scoped=False`` the key space
    is shared - one tenant can read another tenant's cached value.
    """

    def __init__(self, name: str = "fake-cache", *, tenant_scoped: bool = True) -> None:
        capabilities = frozenset({Capability.TENANT_SCOPED_KEYS}) if tenant_scoped else frozenset()
        super().__init__(name, capabilities)
        self._tenant_scoped = tenant_scoped
        self._store: dict[str, str] = {}

    def _key(self, tenant: UUID, key: str) -> str:
        return f"{tenant}:{key}" if self._tenant_scoped else key

    def get(self, tenant: UUID, key: str) -> str | None:
        return self._store.get(self._key(tenant, key))

    def set(self, tenant: UUID, key: str, value: str) -> None:
        self._store[self._key(tenant, key)] = value

    def keys(self) -> list[str]:
        return sorted(self._store)
