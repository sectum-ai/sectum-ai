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
from typing import Any
from uuid import UUID

from sectum_ai.adapters.base import (
    AgentAdapter,
    AgentResult,
    BackupAdapter,
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
from sectum_ai.spec import AdapterError, CorpusDocument, ErasureUnsupported, Surface

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# ``search`` is the parameter/description-injection surface: a tool whose own
# description (or a parameter default) can smuggle a foreign coordinate into the
# call. ``echo`` and ``lookup`` are the original confused-deputy / passthrough
# surfaces (the engineering spec, section 7).
_MCP_TOOLS = ("echo", "lookup", "search")

# A vulnerable ``search`` tool's *description* smuggles a coordinate. A
# tool-description-injection server (``description_injection=True``) honours an
# embedded ``key=<id>`` directive lifted from the tool's own description text -
# the directive an attacker-authored description carries to make the agent fetch
# a resource the caller never named. The directive points at a foreign resource
# key (a manifest marker id), so a vulnerable server resolves another tenant's
# resource even though the call itself carried no key (the engineering spec,
# section 7 - the MCP confused-deputy surface; OWASP LLM08:2025).
_DESCRIPTION_KEY_RE = re.compile(r"key=(\S+)")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _searchable_text(document: CorpusDocument) -> str:
    """Every field a marker may be planted in: title, body, and metadata values.

    Markers are planted in a pivot document's body, title, and metadata (the
    engineering spec, section 6.3), so all three are searched - a query naming a
    marker or entity surfaced in any field retrieves the document.
    """
    return " ".join([document.title, document.content, *document.metadata.values()])


def _overlap(query_tokens: set[str], document: CorpusDocument) -> float:
    return float(len(query_tokens & _tokens(_searchable_text(document))))


def _rank(
    query: str, candidates: list[tuple[UUID, CorpusDocument]], k: int | None
) -> list[VectorHit]:
    """Score candidates by lexical overlap and return the top ``k`` hits (all when ``None``)."""
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
    return hits if k is None else hits[:k]


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

    synthetic = True

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
        # An upsert replaces by id: appending duplicated hits on a re-upsert and
        # left `fetch` returning the stale copy.
        held = self._documents.setdefault(tenant, [])
        incoming = {document.doc_id: document for document in documents}
        held[:] = [document for document in held if document.doc_id not in incoming]
        held.extend(incoming.values())

    def _scope(self, tenant: UUID, user: UUID | None) -> list[tuple[UUID, CorpusDocument]]:
        """The (owner, document) pairs reachable from the principal's session."""
        if self._shared_index:
            # A snapshot: a concurrent first upsert for a new tenant (--max-concurrency)
            # otherwise raised "dictionary changed size during iteration".
            candidates = [
                (owner, document)
                for owner, documents in list(self._documents.items())
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
        if self._recall >= 1.0:
            return _rank(text, self._scope(tenant, user), k)
        # Model embedding-model strength: a weaker model misses some cross-tenant
        # documents. Own-tenant hits always survive; each cross-tenant hit
        # survives deterministically with probability ``recall`` (the engineering
        # spec, section 7 - "stronger embeddings leak more"). The recall filter
        # runs BEFORE the top-k cut: cutting first returned fewer than k and could
        # drop the tenant's own hit behind a foreign one the filter then removed.
        surviving = [
            hit
            for hit in _rank(text, self._scope(tenant, user), None)
            if hit.tenant_id == tenant or _recall_keep(text, hit.doc_id) < self._recall
        ]
        return surviving[:k]

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

    With ``shared_index=True`` (the leaky knob) the pipeline's retriever
    searches across *every* tenant's indexed documents, so a benign query
    from tenant Y surfaces tenant X's content - the exact Class 2 pivot
    pattern the Retrieval-Pivot probe is built to detect. With it off the
    pipeline is tenant-scoped (the default).
    """

    synthetic = True

    def __init__(self, name: str = "fake-rag", *, shared_index: bool = False) -> None:
        capabilities: set[Capability] = set()
        if shared_index:
            capabilities.add(Capability.SHARED_INDEX)
        else:
            capabilities.add(Capability.PER_TENANT_NAMESPACE)
        super().__init__(name, frozenset(capabilities))
        self._documents: dict[UUID, list[CorpusDocument]] = {}
        self._shared_index = shared_index

    def index(self, tenant: UUID, documents: Sequence[CorpusDocument]) -> None:
        """Populate a tenant's corpus (test helper; not part of the interface)."""
        self._documents.setdefault(tenant, []).extend(documents)

    def ask(self, tenant: UUID, query: str) -> RagAnswer:
        if self._shared_index:
            # Cross-tenant retrieval: rank candidates from every tenant's corpus.
            candidates = [
                (owner, document)
                for owner, documents in self._documents.items()
                for document in documents
            ]
        else:
            candidates = [(tenant, document) for document in self._documents.get(tenant, [])]
        retrieved = tuple(_rank(query, candidates, k=3))
        if not retrieved:
            return RagAnswer(answer="no relevant context found", retrieved=())
        return RagAnswer(answer=" | ".join(hit.content for hit in retrieved), retrieved=retrieved)


class FakeObservability(ObservabilityAdapter):
    """A deterministic in-memory tracing backend.

    Two distinct erasure-gap models, both caught by Class 11:

    - ``soft_delete=True``: ``delete`` is a no-op - the backend acknowledges
      the request but leaves the traces in place (mirroring ``FakeVectorStore``).
      This is a genuine erasure *failure* (residual data).
    - ``no_erasure=True``: ``delete`` raises ``ErasureUnsupported`` - the
      backend exposes no programmatic per-tenant erasure API at all (Helicone,
      Datadog APM). Class 11 records this as *attestable-with-caveat*, distinct
      from a soft-delete failure (spec §7 #8).
    """

    synthetic = True

    def __init__(
        self,
        name: str = "fake-observability",
        *,
        soft_delete: bool = False,
        no_erasure: bool = False,
    ) -> None:
        capabilities = {Capability.TRACE_SEARCH}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._soft_delete = soft_delete
        self._no_erasure = no_erasure
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

    def fetch_trace(self, tenant: UUID, trace_id: str) -> TraceHit | None:
        for tid, project, text in self._traces.get(tenant, []):
            if tid == trace_id:
                return TraceHit(trace_id=tid, project=project, snippet=text)
        return None

    def list_projects(self) -> list[str]:
        return sorted({project for traces in self._traces.values() for _, project, _ in traces})

    def delete(self, tenant: UUID) -> None:
        # A backend with no per-tenant erasure API signals the caveat path;
        # checked first so it is unambiguous even if soft_delete is also set.
        if self._no_erasure:
            raise ErasureUnsupported(
                "fake observability backend models a tracing service with no "
                "per-tenant erasure API; data is presumed retained"
            )
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

    synthetic = True

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
    """A deterministic in-memory MCP server: an ``echo``, a ``lookup``, and a ``search`` tool.

    The ``lookup`` and ``search`` tools resolve a key to a tenant resource. Each
    flaw below can be switched on independently, and each is caught by Class 7
    (the engineering spec, section 7 - the MCP confused-deputy / token-passthrough
    surface):

    - ``confused_deputy=True``: ``lookup`` resolves keys across every tenant's
      resources - the server has lost the caller's tenant scope.
    - ``token_passthrough=True``: ``lookup`` honours a caller-supplied ``token``
      argument and acts as whatever tenant the token names (the Asana-class
      pattern).
    - ``description_injection=True``: the ``search`` tool's own *description*
      smuggles a ``key=<id>`` coordinate, and the server honours it - so a
      ``search`` call that named no key still resolves the foreign resource the
      attacker-authored description points at (the tool-description / parameter
      injection sub-probe). A scoped server ignores the description directive.
    - ``downstream`` (with ``cross_server_deputy``): this server is a *router*
      that forwards a ``via=<name>`` lookup to a second server holding tenant X's
      authority. With ``cross_server_deputy=True`` it forwards under the
      downstream's broad service authority (the cross-server confused deputy, so
      X's data returns); with it off it forwards the caller's own tenant, so the
      downstream resolves nothing foreign.

    With every flaw off the server is tenant-scoped and reports that capability. A
    tenant-scoped server still resolves a key across all of one tenant's
    resources, so a sibling user's resource surfaces - the cross-user leak.
    With ``user_scoped=True`` (reporting ``USER_SCOPED``) a ``lookup`` carrying a
    ``user`` resolves only that user's own resources within the tenant (ADR-0006).
    """

    synthetic = True

    def __init__(
        self,
        name: str = "fake-mcp",
        *,
        confused_deputy: bool = False,
        token_passthrough: bool = False,
        description_injection: bool = False,
        cross_server_deputy: bool = False,
        downstream: "FakeMCP | None" = None,
        user_scoped: bool = False,
    ) -> None:
        scoped = not (
            confused_deputy or token_passthrough or description_injection or cross_server_deputy
        )
        capabilities = {Capability.TOOL_INVOCATION}
        if scoped:
            capabilities.add(Capability.TENANT_SCOPED_TOOLS)
        if user_scoped:
            capabilities.add(Capability.USER_SCOPED)
        super().__init__(name, frozenset(capabilities))
        self._confused_deputy = confused_deputy
        self._token_passthrough = token_passthrough
        self._description_injection = description_injection
        self._cross_server_deputy = cross_server_deputy
        self._downstream = downstream
        self._user_scoped = user_scoped
        # Each resource records the user that owns it (``None`` = tenant-level)
        # so a user-scoped server can deny a sibling user's lookup.
        self._resources: dict[UUID, dict[str, tuple[UUID | None, str]]] = {}
        # The ``search`` tool's injected description text, per resource key. A
        # vulnerable server lifts the ``key=<id>`` directive out of it.
        self._tool_descriptions: dict[str, str] = {}

    def provision(self, tenant: UUID, key: str, value: str, *, user: UUID | None = None) -> None:
        """Store a resource the ``lookup``/``search`` tool can resolve (test helper)."""
        self._resources.setdefault(tenant, {})[key] = (user, value)

    def inject_description(self, key: str, description: str) -> None:
        """Register a poisoned ``search`` tool description carrying a coordinate (test helper).

        The description an attacker authored for the ``search`` tool; on a server
        with ``description_injection=True`` an embedded ``key=<id>`` directive is
        followed, fetching the resource the caller never named (the engineering
        spec, section 7 - tool-description / parameter injection).
        """
        self._tool_descriptions[key] = description

    def list_tools(self) -> list[str]:
        return list(_MCP_TOOLS)

    def invoke(
        self, tenant: UUID, tool: str, arguments: dict[str, str], *, user: UUID | None = None
    ) -> McpResult:
        if tool not in _MCP_TOOLS:
            raise AdapterError(f"unknown tool: {tool}")
        if tool == "echo":
            return McpResult(tool=tool, output=arguments.get("text", ""))
        if tool == "search":
            return McpResult(tool=tool, output=self._search(tenant, arguments, user))
        return McpResult(tool=tool, output=self._lookup(tenant, arguments, user))

    def _search(self, tenant: UUID, arguments: dict[str, str], user: UUID | None) -> str:
        """Resolve a ``search`` call, honouring an injected description coordinate when vulnerable.

        On a ``description_injection`` server the tool's own description supplies
        a ``key=<id>`` coordinate the caller never passed; the server follows it
        and resolves that (foreign) resource. A scoped server ignores the
        description and resolves only an explicitly-passed ``key`` in the caller's
        own tenant - so the injection surfaces nothing.
        """
        if self._description_injection:
            description = self._tool_descriptions.get(arguments.get("desc_key", ""), "")
            match = _DESCRIPTION_KEY_RE.search(description)
            if match is not None:
                # The server obeys the coordinate the attacker embedded in the
                # tool description and fetches *that* resource - which belongs to
                # another tenant - so the resolution bypasses the caller's scope.
                # Keys are globally unique marker ids, so this resolves the one
                # resource the injected coordinate names.
                return self._resolve_global(match.group(1))
        # A scoped server never reads the description; a bare ``search`` without
        # an explicit key resolves nothing, and an explicit key stays in scope.
        return self._lookup(tenant, arguments, user)

    def _resolve_global(self, key: str) -> str:
        """Resolve ``key`` across every tenant's resources (the scope-bypass result)."""
        for resources in self._resources.values():
            if key in resources:
                return resources[key][1]
        return ""

    def _lookup(self, tenant: UUID, arguments: dict[str, str], user: UUID | None) -> str:
        # A router forwards a ``via=<name>`` call to its downstream server; the
        # cross-server confused deputy resolves there under the downstream's
        # broad authority (the engineering spec, section 7 - cross-server deputy).
        if "via" in arguments and self._downstream is not None:
            return self._forward(tenant, arguments, user)
        key = arguments.get("key", "")
        if self._confused_deputy:
            # Resource keys are globally unique (marker ids), so resolving
            # across every tenant's resources is unambiguous and order-free.
            return self._resolve_global(key)
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

    def _forward(self, tenant: UUID, arguments: dict[str, str], user: UUID | None) -> str:
        """Forward a lookup to the downstream server (the cross-server boundary).

        A confused-deputy router presents the downstream with its own broad
        *service* authority instead of the caller's tenant, so the downstream
        resolves a key that belongs to *any* tenant it serves - tenant X's
        resource flows back through tenant Y's session. A correctly-scoped router
        forwards the caller's own tenant, so the downstream denies a foreign key.
        The downstream is itself a tenant-scoped server (its own flaws off), so
        the leak is attributable to the router, not the downstream.
        """
        assert self._downstream is not None  # guarded by the caller
        forwarded = {key: value for key, value in arguments.items() if key != "via"}
        if self._cross_server_deputy:
            # Present the downstream's own service authority (any tenant that
            # holds the key), not the caller's. Keys are globally unique marker
            # ids, so this is unambiguous.
            for owner in self._downstream._resources:
                result = self._downstream.invoke(owner, "lookup", forwarded, user=user)
                if result.output:
                    return result.output
            return ""
        # Scoped router: the downstream sees the real caller, so a foreign key
        # resolves to nothing.
        return self._downstream.invoke(tenant, "lookup", forwarded, user=user).output

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

    synthetic = True

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

    synthetic = True

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

    def served_by(self, tenant: UUID, prompt: str, *, user: UUID | None = None) -> UUID | None:
        # Without weight bleed only the caller's own adapter is in scope, so the
        # request is always served by the caller. With bleed a foreign tenant's
        # adapter can match and serve the prompt - that foreign owner is the
        # mis-routing Class 9 asserts against (it coincides with the canary leak).
        if not self._adapter_bleed:
            return tenant
        prompt_tokens = _tokens(prompt)
        for owner_tenant, entries in self._adapters.items():
            if owner_tenant != tenant and any(
                prompt_tokens & _tokens(text) for _owner_user, text in entries
            ):
                return owner_tenant
        return tenant

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

    synthetic = True

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

    synthetic = True

    def __init__(self, name: str = "fake-search", *, soft_delete: bool = False) -> None:
        capabilities = {Capability.TEXT_SEARCH}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._soft_delete = soft_delete
        self._documents: dict[UUID, list[str]] = {}

    def index(self, tenant: UUID, text: str) -> None:
        """Index a document's text for ``tenant``."""
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

    synthetic = True

    def __init__(self, name: str = "fake-eval-set", *, soft_delete: bool = False) -> None:
        capabilities = {Capability.TEXT_SEARCH}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._soft_delete = soft_delete
        self._entries: dict[UUID, list[str]] = {}

    def add(self, tenant: UUID, text: str) -> None:
        """Add an eval-set fixture for ``tenant``."""
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


class FakeBackup(BackupAdapter):
    """A deterministic in-memory backup / snapshot store.

    Backup snapshots are the seventh of the spec's "ten hiding places". With
    ``no_erasure=True`` a ``delete`` raises ``ErasureUnsupported`` - the common
    case of an immutable backup or one with no per-tenant purge, which Class 11
    records as *attestable-with-caveat* (data presumed retained). With
    ``soft_delete=True`` a ``delete`` is acknowledged but leaves the snapshot in
    place - the residue Class 11 is built to catch. Both default to off.
    """

    synthetic = True

    def __init__(
        self, name: str = "fake-backup", *, soft_delete: bool = False, no_erasure: bool = False
    ) -> None:
        capabilities = {Capability.TEXT_SEARCH}
        if soft_delete:
            capabilities.add(Capability.SOFT_DELETE)
        super().__init__(name, frozenset(capabilities))
        self._soft_delete = soft_delete
        self._no_erasure = no_erasure
        self._snapshots: dict[UUID, list[str]] = {}

    def add(self, tenant: UUID, text: str) -> None:
        """Add a backup snapshot entry for ``tenant``."""
        self._snapshots.setdefault(tenant, []).append(text)

    def search(self, tenant: UUID, query: str) -> list[str]:
        """Return ``tenant``'s backup snippets whose tokens overlap ``query``."""
        query_tokens = _tokens(query)
        return [text for text in self._snapshots.get(tenant, []) if query_tokens & _tokens(text)]

    def delete(self, tenant: UUID) -> None:
        if self._no_erasure:
            raise ErasureUnsupported(
                "the backup store exposes no per-tenant erasure API; data is "
                "presumed retained until the snapshot ages out"
            )
        # A soft-delete backup acknowledges the request but keeps the snapshot -
        # the residue Class 11 erasure verification is built to catch.
        if self._soft_delete:
            return
        self._snapshots.pop(tenant, None)


class FakeAppApi(FakeVectorStore):
    """An application's own resource API, standing in for a live one.

    The app under test is reached through the same contract a vector store is:
    ``upsert`` writes a tenant's documents through its API, ``fetch`` reads one
    back by id as a named principal - which is a cross-tenant object-reference
    test, the Class 1 primitive - and ``query`` searches. So it fills the vector
    slot and every probe that drives that slot runs against it unmodified.

    Two declarations make it honest about what it is rather than what slot it
    occupies. ``surface`` is :data:`~sectum_ai.spec.Surface.API`, so its findings
    and the run's provenance both say ``api``. ``semantic_retrieval`` is ``False``,
    so Class 6 (embedding inversion) and Class 13 (multi-modal bleed) are skipped:
    an application's search is not an embedding space, and a substring hit
    reported as ``Invert ML Model`` would be a real result attributed to a
    mechanism that is not there.

    ``shared_index=True`` is the leak this models - the API that does not filter
    by tenant, so one tenant's id returns another's object.

    Retrieval reuses the vector fake's, which is embedding-ranked rather than
    keyword-matched. That imprecision is harmless precisely because the two
    classes whose verdicts depend on the retrieval *mechanism* are gated off; the
    classes that remain ask only whether foreign content came back.
    """

    synthetic = True
    surface = Surface.API
    semantic_retrieval = False

    def __init__(self, name: str = "fake-app", **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
