"""In-memory fake adapters for tests and offline runs.

Every adapter family ships a deterministic in-memory fake (the engineering
spec, section 11). The fakes satisfy the family interfaces and report their
capabilities honestly, so they pass the adapter contract suite and serve as
isolated-stack baselines for probe tests.

The fakes are consolidated in this module for now; per-family modules
(``vector/pgvector.py`` and so on) are introduced alongside the live adapters.
"""

import hashlib
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
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    RagAnswer,
    RAGPipelineAdapter,
    TraceHit,
    VectorHit,
    VectorStoreAdapter,
)
from sectum.spec import AdapterError, CorpusDocument

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

    def _scope(self, tenant: UUID) -> list[tuple[UUID, CorpusDocument]]:
        """The (owner, document) pairs reachable from ``tenant``'s session."""
        if self._shared_index:
            return [
                (owner, document)
                for owner, documents in self._documents.items()
                for document in documents
            ]
        return [(tenant, document) for document in self._documents.get(tenant, [])]

    def query(self, tenant: UUID, text: str, k: int = 5) -> list[VectorHit]:
        return _rank(text, self._scope(tenant), k)

    def fetch(self, tenant: UUID, doc_id: str) -> VectorHit | None:
        for owner, document in self._scope(tenant):
            if document.doc_id == doc_id:
                return VectorHit(
                    doc_id=document.doc_id,
                    tenant_id=owner,
                    score=1.0,
                    content=document.content,
                )
        return None

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
    """A deterministic in-memory MCP server exposing an ``echo`` and a ``lookup`` tool.

    The ``lookup`` tool resolves a key to a tenant resource. Two independent
    flaws can be switched on, both caught by Class 7:

    - ``confused_deputy=True``: ``lookup`` resolves keys across every tenant's
      resources - the server has lost the caller's tenant scope.
    - ``token_passthrough=True``: ``lookup`` honours a caller-supplied ``token``
      argument and acts as whatever tenant the token names (the Asana-class
      pattern).

    With both off the server is tenant-scoped and reports that capability.
    """

    def __init__(
        self,
        name: str = "fake-mcp",
        *,
        confused_deputy: bool = False,
        token_passthrough: bool = False,
    ) -> None:
        capabilities = {Capability.TOOL_INVOCATION}
        if not confused_deputy and not token_passthrough:
            capabilities.add(Capability.TENANT_SCOPED_TOOLS)
        super().__init__(name, frozenset(capabilities))
        self._confused_deputy = confused_deputy
        self._token_passthrough = token_passthrough
        self._resources: dict[UUID, dict[str, str]] = {}

    def provision(self, tenant: UUID, key: str, value: str) -> None:
        """Store a tenant resource the ``lookup`` tool can resolve (test helper)."""
        self._resources.setdefault(tenant, {})[key] = value

    def list_tools(self) -> list[str]:
        return list(_MCP_TOOLS)

    def invoke(self, tenant: UUID, tool: str, arguments: dict[str, str]) -> McpResult:
        if tool not in _MCP_TOOLS:
            raise AdapterError(f"unknown tool: {tool}")
        if tool == "echo":
            return McpResult(tool=tool, output=arguments.get("text", ""))
        return McpResult(tool=tool, output=self._lookup(tenant, arguments))

    def _lookup(self, tenant: UUID, arguments: dict[str, str]) -> str:
        key = arguments.get("key", "")
        if self._confused_deputy:
            # Resource keys are globally unique (marker ids), so resolving
            # across every tenant's resources is unambiguous and order-free.
            scopes = list(self._resources.values())
        else:
            scopes = [self._resources.get(self._effective_tenant(tenant, arguments), {})]
        for resources in scopes:
            if key in resources:
                return resources[key]
        return ""

    def _effective_tenant(self, tenant: UUID, arguments: dict[str, str]) -> UUID:
        # Token passthrough: the server trusts a caller-supplied token instead
        # of the authenticated caller, so a foreign token reaches a foreign scope.
        if self._token_passthrough and "token" in arguments:
            try:
                return UUID(arguments["token"])
            except ValueError:
                return tenant
        return tenant


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


class FakeModel(ModelAdapter):
    """A deterministic in-memory model with per-tenant adapters and a prefix cache.

    With ``adapter_bleed=True`` one tenant's adapter influences another
    tenant's inference - the weight-bleed condition Class 9 is built to catch.
    With ``prefix_cache=True`` the model keeps a KV prefix cache shared across
    tenants: a prompt whose prefix was recently seen returns faster, the timing
    side channel Class 5 is built to catch. Both default to off.
    """

    _BASE_LATENCY_MS = 100.0
    _CACHE_HIT_SPEEDUP_MS = 60.0

    def __init__(
        self,
        name: str = "fake-model",
        *,
        adapter_bleed: bool = False,
        prefix_cache: bool = False,
    ) -> None:
        scope = Capability.SHARED_WEIGHTS if adapter_bleed else Capability.PER_TENANT_ADAPTER
        capabilities = {scope}
        if prefix_cache:
            capabilities.add(Capability.SHARED_PREFIX_CACHE)
        super().__init__(name, frozenset(capabilities))
        self._adapter_bleed = adapter_bleed
        self._prefix_cache = prefix_cache
        self._adapters: dict[UUID, list[str]] = {}
        self._warmed_prefixes: set[str] = set()

    def train_adapter(self, tenant: UUID, texts: Sequence[str]) -> None:
        self._adapters.setdefault(tenant, []).extend(texts)

    def infer(self, tenant: UUID, prompt: str) -> str:
        # Running a prompt warms the shared prefix cache for whoever asks next.
        self._warmed_prefixes.add(self._prefix(prompt))
        # The model "recalls" memorized adapter text that overlaps the prompt.
        # With weight bleed it recalls across every tenant's adapter, not just
        # the caller's - so a foreign tenant's memorized canary surfaces.
        prompt_tokens = _tokens(prompt)
        if self._adapter_bleed:
            corpus = [text for texts in self._adapters.values() for text in texts]
        else:
            corpus = list(self._adapters.get(tenant, []))
        recalled = [text for text in corpus if prompt_tokens & _tokens(text)]
        if not recalled:
            return "the adapter recalled nothing for this prompt"
        return " ".join(recalled)

    def measure_latency(self, tenant: UUID, prompt: str) -> float:
        """Return a deterministic inference latency in milliseconds.

        A shared prefix cache returns a recently-seen prefix faster, so a
        prompt that shares a prefix with another tenant's warmed prompt is
        measurably quicker - the side channel. The jitter is keyed on the
        prompt's last token, so a probe's paired primed and control trials
        carry a paired noise term and the no-cache control has zero net signal.
        """
        tokens = prompt.split()
        jitter_key = tokens[-1] if tokens else prompt
        digest = hashlib.sha256(jitter_key.encode("utf-8")).digest()
        jitter = float(int.from_bytes(digest[:2], "big") % 16)
        latency = self._BASE_LATENCY_MS + jitter
        if self._prefix_cache and self._prefix(prompt) in self._warmed_prefixes:
            latency -= self._CACHE_HIT_SPEEDUP_MS
        return latency

    @staticmethod
    def _prefix(prompt: str) -> str:
        """The cache-key prefix of a prompt: its leading characters."""
        return prompt[:20]


class FakeMemory(MemoryAdapter):
    """A deterministic in-memory long-term memory store.

    With ``shared_memory=True`` a recall spans every tenant's memory - the
    cross-tenant memory contamination Class 8 is built to catch. With it off, a
    tenant recalls only its own memory.
    """

    def __init__(self, name: str = "fake-memory", *, shared_memory: bool = False) -> None:
        scope = Capability.SHARED_MEMORY if shared_memory else Capability.PER_TENANT_MEMORY
        super().__init__(name, frozenset({scope}))
        self._shared_memory = shared_memory
        self._entries: dict[UUID, list[str]] = {}

    def remember(self, tenant: UUID, text: str) -> None:
        self._entries.setdefault(tenant, []).append(text)

    def recall(self, tenant: UUID, query: str) -> list[str]:
        query_tokens = _tokens(query)
        if self._shared_memory:
            corpus = [text for entries in self._entries.values() for text in entries]
        else:
            corpus = list(self._entries.get(tenant, []))
        return [text for text in corpus if query_tokens & _tokens(text)]
