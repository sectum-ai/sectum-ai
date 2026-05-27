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
    EvalSetAdapter,
    MCPAdapter,
    McpResult,
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    RagAnswer,
    RAGPipelineAdapter,
    SearchIndexAdapter,
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


def _recall_keep(query: str, doc_id: str) -> float:
    """A deterministic value in [0, 1) used to gate cross-tenant retrieval recall."""
    digest = hashlib.sha256(f"{query}|{doc_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


class FakeVectorStore(VectorStoreAdapter):
    """A deterministic in-memory vector store.

    With ``shared_index=True`` it models a single index shared across tenants:
    a query from one tenant can surface another tenant's documents. With
    ``user_scoped=True`` it isolates by user within a tenant (ADR-0006): a query
    or fetch carrying a ``user`` sees only that user's documents plus the
    tenant-shared ones; with it off the store scopes by tenant alone, so one
    user surfaces another user's document - the leak. ``shared_index`` (the
    tenant boundary) and ``user_scoped`` (the user boundary) model different
    boundaries and are not meant to be combined. With ``soft_delete=True`` a
    ``delete`` call is acknowledged but leaves the vectors orphaned and still
    queryable. All default to off.
    """

    def __init__(
        self,
        name: str = "fake-vector",
        *,
        shared_index: bool = False,
        user_scoped: bool = False,
        soft_delete: bool = False,
        recall: float = 1.0,
    ) -> None:
        scope = Capability.SHARED_INDEX if shared_index else Capability.PER_TENANT_NAMESPACE
        capabilities = {scope}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._shared_index = shared_index
        self._user_scoped = user_scoped
        self._soft_delete = soft_delete
        self._recall = recall
        self._documents: dict[UUID, list[CorpusDocument]] = {}

    def upsert(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        self._documents.setdefault(tenant, []).extend(documents)

    def _scope(self, tenant: UUID, user: UUID | None) -> list[tuple[UUID, CorpusDocument]]:
        """The (owner, document) pairs reachable from the principal's session."""
        if self._shared_index:
            candidates = [
                (owner, document)
                for owner, documents in self._documents.items()
                for document in documents
            ]
        else:
            candidates = [(tenant, document) for document in self._documents.get(tenant, [])]
        if user is not None and self._user_scoped:
            # A user-scoped store exposes only the user's own documents plus the
            # tenant-shared ones (owner_user_id is None); another user's document
            # is out of scope. A store that scopes by tenant alone ignores ``user``.
            candidates = [
                (owner, document)
                for owner, document in candidates
                if document.owner_user_id is None or document.owner_user_id == user
            ]
        return candidates

    def query(
        self, tenant: UUID, text: str, k: int = 5, *, user: UUID | None = None
    ) -> list[VectorHit]:
        hits = _rank(text, self._scope(tenant, user), k)
        if self._recall >= 1.0:
            return hits
        # Model embedding-model strength: a weaker model misses some cross-tenant
        # documents. Own-tenant hits always survive; each cross-tenant hit
        # survives deterministically with probability ``recall`` (the engineering
        # spec, section 7 - "stronger embeddings leak more").
        return [
            hit
            for hit in hits
            if hit.tenant_id == tenant or _recall_keep(text, hit.doc_id) < self._recall
        ]

    def fetch(self, tenant: UUID, doc_id: str, *, user: UUID | None = None) -> VectorHit | None:
        for owner, document in self._scope(tenant, user):
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
    """A deterministic in-memory tracing backend.

    With ``soft_delete=True``, ``delete`` is a no-op - mirroring
    ``FakeVectorStore``'s soft-delete model. That is the Class 11 erasure
    residue the verification probe is built to catch.
    """

    def __init__(self, name: str = "fake-observability", *, soft_delete: bool = False) -> None:
        capabilities = {Capability.TRACE_SEARCH}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._soft_delete = soft_delete
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

    def delete(self, tenant: UUID) -> None:
        # A soft-delete observability backend acknowledges the request but
        # leaves the traces in place - the residue Class 11 is built to catch.
        if self._soft_delete:
            return
        self._traces.pop(tenant, None)


_AGENT_LOOKUP_RE = re.compile(r"^lookup\s+(\S+?)(?:\s+token=([0-9a-fA-F-]+))?\s*$")


class FakeAgent(AgentAdapter):
    """A deterministic in-memory agent with a ``lookup`` tool.

    Default behaviour: echoes the task and records one notional tool call -
    enough to exercise the adapter contract. When a task matches
    ``lookup <key>[ token=<tenant-hex>]`` the agent invokes its built-in
    ``lookup`` tool against a tenant-scoped resource registry that the
    test substrate provisions via :meth:`provision`.

    Two independent flaws can be switched on, both caught by the Class 7
    direct agent-framework hijack probe:

    - ``confused_deputy=True``: ``lookup`` resolves keys across every tenant's
      resources - the agent has lost the caller's tenant scope on the way to
      its tool.
    - ``tool_call_passthrough=True``: ``lookup`` honours a caller-supplied
      ``token=<tenant-hex>`` argument and acts as whatever tenant the token
      names (the Asana-class agentic tool-passthrough pattern).

    With both off the agent is tenant-scoped and reports that capability.
    """

    def __init__(
        self,
        name: str = "fake-agent",
        *,
        confused_deputy: bool = False,
        tool_call_passthrough: bool = False,
    ) -> None:
        capabilities = {Capability.TOOL_INVOCATION}
        if not confused_deputy and not tool_call_passthrough:
            capabilities.add(Capability.TENANT_SCOPED_TOOLS)
        super().__init__(name, frozenset(capabilities))
        self._confused_deputy = confused_deputy
        self._tool_call_passthrough = tool_call_passthrough
        self._resources: dict[UUID, dict[str, str]] = {}

    def provision(self, tenant: UUID, key: str, value: str) -> None:
        """Store a resource the ``lookup`` tool can resolve (test helper)."""
        self._resources.setdefault(tenant, {})[key] = value

    def run(self, tenant: UUID, task: str) -> AgentResult:
        match = _AGENT_LOOKUP_RE.match(task)
        if match is None:
            return AgentResult(
                output=f"tenant {tenant} completed: {task}",
                tool_calls=("noop",),
            )
        key, token = match.group(1), match.group(2)
        value = self._lookup(tenant, key, token)
        return AgentResult(
            output=f"tool returned: {value}" if value else "tool returned: ",
            tool_calls=("lookup",),
        )

    def _lookup(self, tenant: UUID, key: str, token: str | None) -> str:
        if self._confused_deputy:
            # The agent lost the caller's tenant scope on the way to the tool
            # call; the tool resolves against every tenant's resources.
            for resources in self._resources.values():
                if key in resources:
                    return resources[key]
            return ""
        effective_tenant = tenant
        if self._tool_call_passthrough and token is not None:
            try:
                effective_tenant = UUID(token)
            except ValueError:
                effective_tenant = tenant
        return self._resources.get(effective_tenant, {}).get(key, "")


class FakeMCP(MCPAdapter):
    """A deterministic in-memory MCP server exposing an ``echo`` and a ``lookup`` tool.

    The ``lookup`` tool resolves a key to a tenant resource. Two independent
    flaws can be switched on, both caught by Class 7:

    - ``confused_deputy=True``: ``lookup`` resolves keys across every tenant's
      resources - the server has lost the caller's tenant scope.
    - ``token_passthrough=True``: ``lookup`` honours a caller-supplied ``token``
      argument and acts as whatever tenant the token names (the Asana-class
      pattern).

    With both off the server is tenant-scoped and reports that capability. A
    tenant-scoped server still resolves a key across all of one tenant's
    resources, so a sibling user's resource surfaces - the cross-user leak.
    With ``user_scoped=True`` (reporting ``USER_SCOPED``) a ``lookup`` carrying a
    ``user`` resolves only that user's own resources within the tenant (ADR-0006).
    """

    def __init__(
        self,
        name: str = "fake-mcp",
        *,
        confused_deputy: bool = False,
        token_passthrough: bool = False,
        user_scoped: bool = False,
    ) -> None:
        capabilities = {Capability.TOOL_INVOCATION}
        if not confused_deputy and not token_passthrough:
            capabilities.add(Capability.TENANT_SCOPED_TOOLS)
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        super().__init__(name, frozenset(capabilities))
        self._confused_deputy = confused_deputy
        self._token_passthrough = token_passthrough
        self._user_scoped = user_scoped
        # Each resource records the user that owns it (``None`` = tenant-level)
        # so a user-scoped server can deny a sibling user's lookup.
        self._resources: dict[UUID, dict[str, tuple[UUID | None, str]]] = {}

    def provision(self, tenant: UUID, key: str, value: str, *, user: UUID | None = None) -> None:
        """Store a resource the ``lookup`` tool can resolve (test helper)."""
        self._resources.setdefault(tenant, {})[key] = (user, value)

    def list_tools(self) -> list[str]:
        return list(_MCP_TOOLS)

    def invoke(
        self, tenant: UUID, tool: str, arguments: dict[str, str], *, user: UUID | None = None
    ) -> McpResult:
        if tool not in _MCP_TOOLS:
            raise AdapterError(f"unknown tool: {tool}")
        if tool == "echo":
            return McpResult(tool=tool, output=arguments.get("text", ""))
        return McpResult(tool=tool, output=self._lookup(tenant, arguments, user))

    def _lookup(self, tenant: UUID, arguments: dict[str, str], user: UUID | None) -> str:
        key = arguments.get("key", "")
        if self._confused_deputy:
            # Resource keys are globally unique (marker ids), so resolving
            # across every tenant's resources is unambiguous and order-free.
            for resources in self._resources.values():
                if key in resources:
                    return resources[key][1]
            return ""
        resources = self._resources.get(self._effective_tenant(tenant, arguments), {})
        if key not in resources:
            return ""
        owner_user, value = resources[key]
        # A user-scoped server denies a sibling user's resource within the tenant;
        # a tenant-scoped server resolves it (the cross-user leak). ``user=None``
        # is the tenant-level caller and is unchanged.
        if self._user_scoped and user is not None and owner_user is not None and owner_user != user:
            return ""
        return value

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
    is shared - one tenant can read another tenant's cached value. With
    ``user_scoped=True`` a key carrying a ``user`` also folds in the user, so one
    user cannot read another user's entry within the tenant (ADR-0006); with it
    off the key omits the user, so two users of one tenant collide on one entry -
    the cross-user leak. All default to off except ``tenant_scoped``.
    """

    def __init__(
        self,
        name: str = "fake-cache",
        *,
        tenant_scoped: bool = True,
        user_scoped: bool = False,
        soft_delete: bool = False,
    ) -> None:
        capabilities = {Capability.TENANT_SCOPED_KEYS} if tenant_scoped else set()
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._tenant_scoped = tenant_scoped
        self._user_scoped = user_scoped
        self._soft_delete = soft_delete
        self._store: dict[str, str] = {}

    def _key(self, tenant: UUID, key: str, user: UUID | None = None) -> str:
        # A user-scoped cache folds the user in (so siblings never collide); a
        # tenant-scoped cache folds the tenant in; an unscoped cache uses the
        # bare key. ``user=None`` reproduces the prior tenant-level key exactly.
        parts: list[str] = []
        if self._tenant_scoped:
            parts.append(str(tenant))
        if self._user_scoped and user is not None:
            parts.append(str(user))
        parts.append(key)
        return ":".join(parts)

    def get(self, tenant: UUID, key: str, *, user: UUID | None = None) -> str | None:
        return self._store.get(self._key(tenant, key, user))

    def set(self, tenant: UUID, key: str, value: str, *, user: UUID | None = None) -> None:
        self._store[self._key(tenant, key, user)] = value

    def keys(self) -> list[str]:
        return sorted(self._store)

    def values(self, tenant: UUID) -> list[str]:
        if not self._tenant_scoped:
            return list(self._store.values())
        prefix = f"{tenant}:"
        return [value for key, value in self._store.items() if key.startswith(prefix)]

    def delete(self, tenant: UUID) -> None:
        # A soft-delete cache acknowledges but keeps the entries; an unscoped
        # cache cannot isolate one tenant's entries to delete them. Either way
        # the data survives - the Class 11 erasure residue.
        if self._soft_delete or not self._tenant_scoped:
            return
        prefix = f"{tenant}:"
        for key in [key for key in self._store if key.startswith(prefix)]:
            del self._store[key]


class FakeModel(ModelAdapter):
    """A deterministic in-memory model with per-tenant adapters and a prefix cache.

    With ``adapter_bleed=True`` one tenant's adapter influences another
    tenant's inference - the weight-bleed condition Class 9 is built to catch.
    With ``prefix_cache=True`` the model keeps a KV prefix cache shared across
    tenants: a prompt whose prefix was recently seen returns faster, the timing
    side channel Class 5 is built to catch. With ``user_scoped=True`` (reporting
    ``USER_SCOPED``) inference recalls only the caller user's own adapter within
    the tenant (ADR-0006); with it off a tenant's adapters are shared across its
    users, so one user's memorized canary surfaces in a sibling's inference - the
    cross-user bleed. ``adapter_bleed`` (the tenant boundary) and ``user_scoped``
    (the user boundary) model different boundaries and are not meant to be
    combined. All default to off.
    """

    _BASE_LATENCY_MS = 100.0
    _CACHE_HIT_SPEEDUP_MS = 60.0

    def __init__(
        self,
        name: str = "fake-model",
        *,
        adapter_bleed: bool = False,
        prefix_cache: bool = False,
        user_scoped: bool = False,
        soft_delete: bool = False,
    ) -> None:
        scope = Capability.SHARED_WEIGHTS if adapter_bleed else Capability.PER_TENANT_ADAPTER
        capabilities = {scope}
        if prefix_cache:
            capabilities.add(Capability.SHARED_PREFIX_CACHE)
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._adapter_bleed = adapter_bleed
        self._prefix_cache = prefix_cache
        self._user_scoped = user_scoped
        self._soft_delete = soft_delete
        # Each adapter text is tagged with the user that trained it (``None`` =
        # tenant-level) so a user-scoped model recalls only the caller's own.
        self._adapters: dict[UUID, list[tuple[UUID | None, str]]] = {}
        self._warmed_prefixes: set[str] = set()

    def train_adapter(
        self, tenant: UUID, texts: Sequence[str], *, user: UUID | None = None
    ) -> None:
        self._adapters.setdefault(tenant, []).extend((user, text) for text in texts)

    def infer(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> str:
        # Running a prompt warms the shared prefix cache for whoever asks next.
        self._warmed_prefixes.add(self._prefix(prompt))
        # The model "recalls" memorized adapter text that overlaps the prompt.
        # With weight bleed it recalls across every tenant's adapter, not just
        # the caller's - so a foreign tenant's memorized canary surfaces.
        prompt_tokens = _tokens(prompt)
        if self._adapter_bleed:
            corpus = [entry for entries in self._adapters.values() for entry in entries]
        else:
            corpus = list(self._adapters.get(tenant, []))
        if user is not None and self._user_scoped:
            corpus = [(owner, text) for owner, text in corpus if owner is None or owner == user]
        recalled = [text for owner, text in corpus if prompt_tokens & _tokens(text)]
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

    def delete(self, tenant: UUID) -> None:
        # A soft-delete model acknowledges the request but keeps the tenant's
        # adapter, so the memorized canary still surfaces - the Class 11 residue.
        if self._soft_delete:
            return
        self._adapters.pop(tenant, None)


class FakeMemory(MemoryAdapter):
    """A deterministic in-memory long-term memory store.

    With ``shared_memory=True`` a recall spans every tenant's memory - the
    cross-tenant memory contamination Class 8 is built to catch. With it off, a
    tenant recalls only its own memory. With ``user_scoped=True`` a recall
    carrying a ``user`` returns only that user's own entries plus the
    tenant-shared ones (ADR-0006); with it off a recall scopes by tenant alone,
    so one user recalls a sibling user's note - the cross-user leak.
    ``shared_memory`` (the tenant boundary) and ``user_scoped`` (the user
    boundary) model different boundaries and are not meant to be combined.
    """

    def __init__(
        self,
        name: str = "fake-memory",
        *,
        shared_memory: bool = False,
        user_scoped: bool = False,
        soft_delete: bool = False,
    ) -> None:
        capabilities = {Capability.SHARED_MEMORY if shared_memory else Capability.PER_TENANT_MEMORY}
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._shared_memory = shared_memory
        self._user_scoped = user_scoped
        self._soft_delete = soft_delete
        # Each entry is tagged with the user that wrote it (``None`` = tenant-level)
        # so a user-scoped recall can return only the caller's own and shared notes.
        self._entries: dict[UUID, list[tuple[UUID | None, str]]] = {}

    def remember(self, tenant: UUID, text: str, *, user: UUID | None = None) -> None:
        self._entries.setdefault(tenant, []).append((user, text))

    def recall(self, tenant: UUID, query: str, *, user: UUID | None = None) -> list[str]:
        query_tokens = _tokens(query)
        if self._shared_memory:
            corpus = [entry for entries in self._entries.values() for entry in entries]
        else:
            corpus = list(self._entries.get(tenant, []))
        if user is not None and self._user_scoped:
            corpus = [(owner, text) for owner, text in corpus if owner is None or owner == user]
        return [text for owner, text in corpus if query_tokens & _tokens(text)]

    def delete(self, tenant: UUID) -> None:
        # A soft-delete memory store acknowledges the request but keeps the
        # entries - the residue Class 11 erasure verification is built to catch.
        if self._soft_delete:
            return
        self._entries.pop(tenant, None)


class FakeSearchIndex(SearchIndexAdapter):
    """A deterministic in-memory full-text search index.

    A search index derived from the RAG corpus is the tenth of the spec's "ten
    hiding places". With ``soft_delete=True`` a ``delete`` is acknowledged but
    leaves the documents indexed and still searchable - the residue Class 11
    erasure verification is built to catch. Defaults to off.
    """

    def __init__(self, name: str = "fake-search", *, soft_delete: bool = False) -> None:
        capabilities = {Capability.TEXT_SEARCH}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._soft_delete = soft_delete
        self._documents: dict[UUID, list[str]] = {}

    def index(self, tenant: UUID, text: str) -> None:
        """Index a document's text for ``tenant`` (test helper; not part of the interface)."""
        self._documents.setdefault(tenant, []).append(text)

    def search(self, tenant: UUID, query: str) -> list[str]:
        """Return ``tenant``'s indexed snippets whose tokens overlap ``query``."""
        query_tokens = _tokens(query)
        return [text for text in self._documents.get(tenant, []) if query_tokens & _tokens(text)]

    def delete(self, tenant: UUID) -> None:
        # A soft-delete index acknowledges the request but keeps the documents
        # searchable - the residue Class 11 erasure verification is built to catch.
        if self._soft_delete:
            return
        self._documents.pop(tenant, None)


class FakeEvalSet(EvalSetAdapter):
    """A deterministic in-memory evaluation / golden test-fixture set.

    An eval golden set built from tenant data is the fourth of the spec's "ten
    hiding places". With ``soft_delete=True`` a ``delete`` is acknowledged but
    leaves the fixtures in place - the residue Class 11 erasure verification is
    built to catch. Defaults to off.
    """

    def __init__(self, name: str = "fake-eval-set", *, soft_delete: bool = False) -> None:
        capabilities = {Capability.TEXT_SEARCH}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._soft_delete = soft_delete
        self._entries: dict[UUID, list[str]] = {}

    def add(self, tenant: UUID, text: str) -> None:
        """Add an eval-set fixture for ``tenant`` (test helper; not part of the interface)."""
        self._entries.setdefault(tenant, []).append(text)

    def search(self, tenant: UUID, query: str) -> list[str]:
        """Return ``tenant``'s eval-set fixtures whose tokens overlap ``query``."""
        query_tokens = _tokens(query)
        return [text for text in self._entries.get(tenant, []) if query_tokens & _tokens(text)]

    def delete(self, tenant: UUID) -> None:
        # A soft-delete eval set acknowledges the request but keeps the fixtures -
        # the residue Class 11 erasure verification is built to catch.
        if self._soft_delete:
            return
        self._entries.pop(tenant, None)
