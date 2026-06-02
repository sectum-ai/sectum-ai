"""Contract tests: every fake adapter satisfies its family interface and reports
its capabilities honestly (the engineering spec, section 15)."""

from uuid import UUID

import pytest

from sectum.adapters import (
    Adapter,
    AdapterFamily,
    AdapterRegistry,
    AgentAdapter,
    CacheAdapter,
    Capability,
    EvalSetAdapter,
    FakeAgent,
    FakeBackup,
    FakeCache,
    FakeEvalSet,
    FakeMCP,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeRAGPipeline,
    FakeSearchIndex,
    FakeVectorStore,
    MCPAdapter,
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    RAGPipelineAdapter,
    SearchIndexAdapter,
    VectorStoreAdapter,
)
from sectum.spec import AdapterError, CorpusDocument

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)
_USER_A = UUID(int=0xA1)
_USER_B = UUID(int=0xB2)


def _documents(tenant: UUID, prefix: str, word: str, count: int = 3) -> list[CorpusDocument]:
    return [
        CorpusDocument(
            doc_id=f"{prefix}-{index}",
            tenant_id=tenant,
            doc_type="note",
            title=f"{word} note {index}",
            content=f"a document about {word} number {index}",
        )
        for index in range(count)
    ]


def _user_documents(
    tenant: UUID, user: UUID | None, prefix: str, word: str, count: int = 2
) -> list[CorpusDocument]:
    return [
        CorpusDocument(
            doc_id=f"{prefix}-{index}",
            tenant_id=tenant,
            doc_type="note",
            title=f"{word} note {index}",
            content=f"a document about {word} number {index}",
            owner_user_id=user,
        )
        for index in range(count)
    ]


def _all_fakes() -> list[Adapter]:
    return [
        FakeVectorStore(),
        FakeRAGPipeline(),
        FakeObservability(),
        FakeAgent(),
        FakeMCP(),
        FakeCache(),
        FakeModel(),
        FakeMemory(),
        FakeSearchIndex(),
        FakeEvalSet(),
        FakeBackup(),
    ]


@pytest.mark.parametrize("adapter", _all_fakes(), ids=lambda adapter: adapter.name)
def test_adapter_reports_a_family_and_capabilities(adapter: Adapter) -> None:
    """Every adapter is an Adapter, names itself, and self-reports capabilities."""
    assert isinstance(adapter, Adapter)
    assert adapter.name
    assert isinstance(adapter.family, AdapterFamily)
    assert isinstance(adapter.capabilities, frozenset)
    for capability in adapter.capabilities:
        assert isinstance(capability, Capability)
        assert adapter.supports(capability)


def test_each_fake_belongs_to_the_expected_family() -> None:
    assert FakeVectorStore().family is AdapterFamily.VECTOR_STORE
    assert FakeRAGPipeline().family is AdapterFamily.RAG_PIPELINE
    assert FakeObservability().family is AdapterFamily.OBSERVABILITY
    assert FakeAgent().family is AdapterFamily.AGENT
    assert FakeMCP().family is AdapterFamily.MCP
    assert FakeCache().family is AdapterFamily.CACHE
    assert FakeModel().family is AdapterFamily.MODEL
    assert FakeMemory().family is AdapterFamily.MEMORY
    assert FakeSearchIndex().family is AdapterFamily.SEARCH_INDEX
    assert FakeEvalSet().family is AdapterFamily.EVAL_SET
    assert FakeBackup().family is AdapterFamily.BACKUP


def test_every_adapter_family_has_a_fake_under_the_contract_suite() -> None:
    # No adapter family may ship without a fake exercised by the shared contract
    # suite — the gap that let the Backup family (hiding place #7) land
    # uncovered. This meta-test pins the invariant so a new family cannot.
    covered = {adapter.family for adapter in _all_fakes()}
    missing = sorted(family.value for family in AdapterFamily if family not in covered)
    assert not missing, f"AdapterFamily values with no fake in _all_fakes(): {missing}"


def test_isolated_vector_store_does_not_leak_across_tenants() -> None:
    store = FakeVectorStore()
    assert isinstance(store, VectorStoreAdapter)
    assert store.supports(Capability.PER_TENANT_NAMESPACE)
    assert not store.supports(Capability.SHARED_INDEX)
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    store.upsert(_TENANT_B, _documents(_TENANT_B, "b", "alpha"))
    hits = store.query(_TENANT_B, "alpha", k=10)
    assert hits
    assert all(hit.tenant_id == _TENANT_B for hit in hits)


def test_shared_index_vector_store_is_capability_honest() -> None:
    store = FakeVectorStore(shared_index=True)
    assert store.supports(Capability.SHARED_INDEX)
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    store.upsert(_TENANT_B, _documents(_TENANT_B, "b", "alpha"))
    hits = store.query(_TENANT_B, "alpha", k=10)
    assert any(hit.tenant_id == _TENANT_A for hit in hits)


def test_vector_store_recall_drops_cross_tenant_hits() -> None:
    full = FakeVectorStore(shared_index=True)
    weak = FakeVectorStore(shared_index=True, recall=0.0)
    for store in (full, weak):
        store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
        store.upsert(_TENANT_B, _documents(_TENANT_B, "b", "alpha"))
    # full recall (the default) leaks tenant A's documents into tenant B's query;
    # recall 0.0 models a weak embedding that surfaces no cross-tenant content
    assert any(hit.tenant_id == _TENANT_A for hit in full.query(_TENANT_B, "alpha", 10))
    assert all(hit.tenant_id == _TENANT_B for hit in weak.query(_TENANT_B, "alpha", 10))


def test_vector_store_delete_removes_a_tenant() -> None:
    store = FakeVectorStore()
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    store.delete(_TENANT_A)
    assert store.query(_TENANT_A, "alpha", k=10) == []


def test_vector_store_fetch_returns_one_document_by_id() -> None:
    store = FakeVectorStore()
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    hit = store.fetch(_TENANT_A, "a-1")
    assert hit is not None
    assert hit.doc_id == "a-1"
    assert store.fetch(_TENANT_A, "no-such-doc") is None


def test_isolated_vector_store_fetch_denies_a_cross_tenant_id() -> None:
    store = FakeVectorStore()
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    assert store.fetch(_TENANT_B, "a-1") is None


def test_shared_index_vector_store_fetch_crosses_tenants() -> None:
    store = FakeVectorStore(shared_index=True)
    store.upsert(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    hit = store.fetch(_TENANT_B, "a-1")
    assert hit is not None
    assert hit.tenant_id == _TENANT_A


def test_user_scoped_vector_store_isolates_users_within_a_tenant() -> None:
    store = FakeVectorStore(user_scoped=True)
    assert store.supports(Capability.USER_SCOPED)
    store.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_A, "ua", "alpha"))
    store.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_B, "ub", "alpha"))
    # user A queries within the tenant and sees only its own documents
    hits = store.query(_TENANT_A, "alpha", k=10, user=_USER_A)
    assert hits
    assert all(hit.doc_id.startswith("ua-") for hit in hits)
    # a direct fetch of user B's document from user A's session is denied
    assert store.fetch(_TENANT_A, "ub-0", user=_USER_A) is None
    assert store.fetch(_TENANT_A, "ua-0", user=_USER_A) is not None


def test_tenant_scoped_vector_store_leaks_across_users_when_a_user_is_set() -> None:
    # A store that scopes by tenant alone (not user_scoped) ignores ``user``, so
    # user A surfaces user B's document - the cross-user leak (ADR-0006).
    store = FakeVectorStore()
    assert not store.supports(Capability.USER_SCOPED)
    store.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_A, "ua", "alpha"))
    store.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_B, "ub", "alpha"))
    assert store.fetch(_TENANT_A, "ub-0", user=_USER_A) is not None
    hits = store.query(_TENANT_A, "alpha", k=10, user=_USER_A)
    assert any(hit.doc_id.startswith("ub-") for hit in hits)


def test_user_scoped_vector_store_exposes_tenant_shared_documents() -> None:
    # A document with no user owner is tenant-shared and visible to every user.
    store = FakeVectorStore(user_scoped=True)
    store.upsert(_TENANT_A, _user_documents(_TENANT_A, None, "shared", "alpha", count=1))
    store.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_B, "ub", "alpha"))
    hits = store.query(_TENANT_A, "alpha", k=10, user=_USER_A)
    assert any(hit.doc_id == "shared-0" for hit in hits)
    assert all(not hit.doc_id.startswith("ub-") for hit in hits)


def test_vector_store_user_argument_defaults_to_tenant_scope() -> None:
    # user=None is the tenant-level scope, so behavior is unchanged: even a
    # user-scoped store returns every document in the tenant.
    store = FakeVectorStore(user_scoped=True)
    store.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_A, "ua", "alpha"))
    store.upsert(_TENANT_A, _user_documents(_TENANT_A, _USER_B, "ub", "alpha"))
    doc_ids = {hit.doc_id for hit in store.query(_TENANT_A, "alpha", k=10)}
    assert {"ua-0", "ub-0"} <= doc_ids


def test_cache_tenant_scoping_is_capability_honest() -> None:
    isolated = FakeCache(tenant_scoped=True)
    assert isinstance(isolated, CacheAdapter)
    assert isolated.supports(Capability.TENANT_SCOPED_KEYS)
    isolated.set(_TENANT_A, "key", "secret-a")
    assert isolated.get(_TENANT_B, "key") is None

    shared = FakeCache(tenant_scoped=False)
    assert not shared.supports(Capability.TENANT_SCOPED_KEYS)
    shared.set(_TENANT_A, "key", "secret-a")
    assert shared.get(_TENANT_B, "key") == "secret-a"


def test_user_scoped_cache_isolates_users_within_a_tenant() -> None:
    cache = FakeCache(tenant_scoped=True, user_scoped=True)
    assert cache.supports(Capability.USER_SCOPED)
    cache.set(_TENANT_A, "k", "secret-a", user=_USER_A)
    # a sibling user in the same tenant cannot read user A's entry
    assert cache.get(_TENANT_A, "k", user=_USER_B) is None
    assert cache.get(_TENANT_A, "k", user=_USER_A) == "secret-a"


def test_tenant_scoped_cache_leaks_across_users_when_a_user_is_set() -> None:
    # A cache scoped by tenant alone ignores ``user``, so a sibling user reads
    # the entry - the cross-user leak (ADR-0006 default-deny).
    cache = FakeCache(tenant_scoped=True, user_scoped=False)
    assert not cache.supports(Capability.USER_SCOPED)
    cache.set(_TENANT_A, "k", "secret-a", user=_USER_A)
    assert cache.get(_TENANT_A, "k", user=_USER_B) == "secret-a"


def test_cache_user_argument_defaults_to_tenant_scope() -> None:
    # user=None is the tenant-level scope, so even a user-scoped cache keys by
    # tenant alone and the value round-trips exactly as before.
    cache = FakeCache(tenant_scoped=True, user_scoped=True)
    cache.set(_TENANT_A, "k", "secret-a")
    assert cache.get(_TENANT_A, "k") == "secret-a"


def test_isolated_model_keeps_adapters_per_tenant() -> None:
    model = FakeModel()
    assert isinstance(model, ModelAdapter)
    assert model.supports(Capability.PER_TENANT_ADAPTER)
    model.train_adapter(_TENANT_A, ["alpha adapter fact"])
    assert "alpha" in model.infer(_TENANT_A, "recall the adapter fact")
    assert "alpha" not in model.infer(_TENANT_B, "recall the adapter fact")


def test_weight_bleed_model_leaks_adapters_across_tenants() -> None:
    model = FakeModel(adapter_bleed=True)
    assert model.supports(Capability.SHARED_WEIGHTS)
    model.train_adapter(_TENANT_A, ["alpha adapter fact"])
    assert "alpha" in model.infer(_TENANT_B, "recall the adapter fact")


def test_user_scoped_model_isolates_adapters_within_a_tenant() -> None:
    model = FakeModel(user_scoped=True)
    assert model.supports(Capability.USER_SCOPED)
    model.train_adapter(_TENANT_A, ["alpha adapter fact"], user=_USER_A)
    assert "alpha" in model.infer(_TENANT_A, "recall the adapter fact", user=_USER_A)
    # a sibling user's inference does not recall user A's adapter
    assert "alpha" not in model.infer(_TENANT_A, "recall the adapter fact", user=_USER_B)


def test_tenant_scoped_model_leaks_adapters_across_users() -> None:
    # A model scoping adapters by tenant alone surfaces one user's memorized fact
    # in a sibling user's inference - the cross-user bleed (ADR-0006).
    model = FakeModel(user_scoped=False)
    assert not model.supports(Capability.USER_SCOPED)
    model.train_adapter(_TENANT_A, ["alpha adapter fact"], user=_USER_A)
    assert "alpha" in model.infer(_TENANT_A, "recall the adapter fact", user=_USER_B)


def test_model_prefix_cache_speeds_up_a_warmed_prefix() -> None:
    model = FakeModel(prefix_cache=True)
    assert model.supports(Capability.SHARED_PREFIX_CACHE)
    cold = model.measure_latency(_TENANT_A, "shared-session-prefix probe one")
    model.infer(_TENANT_B, "shared-session-prefix warm-up")
    warm = model.measure_latency(_TENANT_A, "shared-session-prefix probe two")
    # the prefix warmed by tenant B is measurably faster for tenant A
    assert warm < cold


def test_model_without_prefix_cache_does_not_speed_up() -> None:
    model = FakeModel()
    assert not model.supports(Capability.SHARED_PREFIX_CACHE)
    model.infer(_TENANT_B, "shared-session-prefix warm-up")
    assert model.measure_latency(_TENANT_A, "shared-session-prefix probe two") >= 100.0


def test_isolated_memory_keeps_recall_per_tenant() -> None:
    memory = FakeMemory()
    assert isinstance(memory, MemoryAdapter)
    assert memory.supports(Capability.PER_TENANT_MEMORY)
    memory.remember(_TENANT_A, "alpha memory note")
    assert memory.recall(_TENANT_A, "recall the note")
    assert memory.recall(_TENANT_B, "recall the note") == []


def test_shared_memory_leaks_recall_across_tenants() -> None:
    memory = FakeMemory(shared_memory=True)
    assert memory.supports(Capability.SHARED_MEMORY)
    memory.remember(_TENANT_A, "alpha memory note")
    leaked = memory.recall(_TENANT_B, "recall the note")
    assert any("alpha" in entry for entry in leaked)


def test_user_scoped_memory_isolates_users_within_a_tenant() -> None:
    memory = FakeMemory(user_scoped=True)
    assert memory.supports(Capability.USER_SCOPED)
    memory.remember(_TENANT_A, "alpha memory note", user=_USER_A)
    assert memory.recall(_TENANT_A, "recall the note", user=_USER_A)
    # a sibling user in the same tenant cannot recall user A's note
    assert memory.recall(_TENANT_A, "recall the note", user=_USER_B) == []


def test_tenant_scoped_memory_leaks_across_users_when_a_user_is_set() -> None:
    # Memory scoped by tenant alone ignores ``user``, so a sibling user recalls
    # the note - the cross-user leak (ADR-0006 default-deny).
    memory = FakeMemory(user_scoped=False)
    assert not memory.supports(Capability.USER_SCOPED)
    memory.remember(_TENANT_A, "alpha memory note", user=_USER_A)
    leaked = memory.recall(_TENANT_A, "recall the note", user=_USER_B)
    assert any("alpha" in entry for entry in leaked)


def test_memory_user_argument_defaults_to_tenant_scope() -> None:
    # user=None is the tenant-level recall, so behavior is unchanged from before.
    memory = FakeMemory(user_scoped=True)
    memory.remember(_TENANT_A, "alpha memory note")
    assert memory.recall(_TENANT_A, "recall the note")


def test_rag_pipeline_retrieves_indexed_context() -> None:
    rag = FakeRAGPipeline()
    assert isinstance(rag, RAGPipelineAdapter)
    rag.index(_TENANT_A, _documents(_TENANT_A, "a", "alpha"))
    answer = rag.ask(_TENANT_A, "alpha")
    assert answer.retrieved
    assert all(hit.tenant_id == _TENANT_A for hit in answer.retrieved)


def test_observability_search_is_scoped_to_a_tenant() -> None:
    obs = FakeObservability()
    assert isinstance(obs, ObservabilityAdapter)
    obs.record(_TENANT_A, "project-a", "trace containing CANARY-123")
    obs.record(_TENANT_B, "project-b", "trace containing CANARY-123")
    hits = obs.search_traces(_TENANT_A, "CANARY-123")
    assert [hit.project for hit in hits] == ["project-a"]
    assert obs.list_projects() == ["project-a", "project-b"]


def test_agent_run_returns_a_result() -> None:
    agent = FakeAgent()
    assert isinstance(agent, AgentAdapter)
    result = agent.run(_TENANT_A, "summarize the backlog")
    assert "summarize the backlog" in result.output


def test_mcp_lists_and_invokes_tools() -> None:
    mcp = FakeMCP()
    assert isinstance(mcp, MCPAdapter)
    assert "echo" in mcp.list_tools()
    assert mcp.invoke(_TENANT_A, "echo", {"text": "hello"}).output == "hello"
    with pytest.raises(AdapterError, match="unknown tool"):
        mcp.invoke(_TENANT_A, "missing", {})


def test_isolated_mcp_keeps_tool_calls_tenant_scoped() -> None:
    mcp = FakeMCP()
    assert mcp.supports(Capability.TENANT_SCOPED_TOOLS)
    mcp.provision(_TENANT_A, "res-1", "alpha resource")
    assert mcp.invoke(_TENANT_B, "lookup", {"key": "res-1"}).output == ""
    assert mcp.invoke(_TENANT_A, "lookup", {"key": "res-1"}).output == "alpha resource"


def test_mcp_confused_deputy_resolves_keys_across_tenants() -> None:
    mcp = FakeMCP(confused_deputy=True)
    assert not mcp.supports(Capability.TENANT_SCOPED_TOOLS)
    mcp.provision(_TENANT_A, "res-1", "alpha resource")
    assert mcp.invoke(_TENANT_B, "lookup", {"key": "res-1"}).output == "alpha resource"


def test_mcp_token_passthrough_acts_as_the_token_tenant() -> None:
    mcp = FakeMCP(token_passthrough=True)
    mcp.provision(_TENANT_A, "res-1", "alpha resource")
    assert mcp.invoke(_TENANT_B, "lookup", {"key": "res-1"}).output == ""
    carried = mcp.invoke(_TENANT_B, "lookup", {"key": "res-1", "token": str(_TENANT_A)})
    assert carried.output == "alpha resource"


def test_user_scoped_mcp_isolates_users_within_a_tenant() -> None:
    mcp = FakeMCP(user_scoped=True)
    assert mcp.supports(Capability.USER_SCOPED)
    mcp.provision(_TENANT_A, "res-1", "alpha resource", user=_USER_A)
    # a sibling user in the same tenant cannot resolve user A's resource
    assert mcp.invoke(_TENANT_A, "lookup", {"key": "res-1"}, user=_USER_B).output == ""
    assert (
        mcp.invoke(_TENANT_A, "lookup", {"key": "res-1"}, user=_USER_A).output == "alpha resource"
    )


def test_tenant_scoped_mcp_resolves_a_sibling_users_resource() -> None:
    # A tenant-scoped server resolves any key within the tenant regardless of the
    # owning user, so a sibling user reads it - the cross-user leak (ADR-0006).
    mcp = FakeMCP()
    assert not mcp.supports(Capability.USER_SCOPED)
    mcp.provision(_TENANT_A, "res-1", "alpha resource", user=_USER_A)
    leaked = mcp.invoke(_TENANT_A, "lookup", {"key": "res-1"}, user=_USER_B)
    assert leaked.output == "alpha resource"


def test_adapter_registry_registers_lists_and_rejects_duplicates() -> None:
    registry = AdapterRegistry()
    store = FakeVectorStore()
    cache = FakeCache()
    registry.register(store)
    registry.register(cache)
    assert registry.get("fake-vector") is store
    assert [adapter.name for adapter in registry.all()] == ["fake-cache", "fake-vector"]
    assert registry.by_family(AdapterFamily.CACHE) == [cache]
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeVectorStore())


def test_observability_delete_clears_a_tenants_traces() -> None:
    obs = FakeObservability()
    obs.record(_TENANT_A, "project-a", "trace containing CANARY-X")
    assert obs.search_traces(_TENANT_A, "CANARY-X")
    obs.delete(_TENANT_A)
    assert obs.search_traces(_TENANT_A, "CANARY-X") == []


def test_soft_delete_observability_retains_traces() -> None:
    obs = FakeObservability(soft_delete=True)
    obs.record(_TENANT_A, "project-a", "trace containing CANARY-X")
    obs.delete(_TENANT_A)
    # the soft-delete fake acknowledges but leaves traces - the Class 11 residue
    assert obs.search_traces(_TENANT_A, "CANARY-X")


def test_memory_delete_clears_a_tenants_entries() -> None:
    memory = FakeMemory()
    memory.remember(_TENANT_A, "memory note containing CANARY-X")
    assert memory.recall(_TENANT_A, "CANARY-X")
    memory.delete(_TENANT_A)
    assert memory.recall(_TENANT_A, "CANARY-X") == []


def test_soft_delete_memory_retains_entries() -> None:
    memory = FakeMemory(soft_delete=True)
    memory.remember(_TENANT_A, "memory note containing CANARY-X")
    memory.delete(_TENANT_A)
    # the soft-delete fake acknowledges but leaves entries - the Class 11 residue
    assert memory.recall(_TENANT_A, "CANARY-X")


def test_cache_values_are_scoped_to_a_tenant() -> None:
    cache = FakeCache()
    cache.set(_TENANT_A, "k", "value containing CANARY-X")
    cache.set(_TENANT_B, "k", "value containing CANARY-Y")
    assert cache.values(_TENANT_A) == ["value containing CANARY-X"]


def test_cache_delete_clears_a_tenants_entries() -> None:
    cache = FakeCache()
    cache.set(_TENANT_A, "k", "value containing CANARY-X")
    assert cache.values(_TENANT_A)
    cache.delete(_TENANT_A)
    assert cache.values(_TENANT_A) == []


def test_soft_delete_cache_retains_entries() -> None:
    cache = FakeCache(soft_delete=True)
    cache.set(_TENANT_A, "k", "value containing CANARY-X")
    cache.delete(_TENANT_A)
    # the soft-delete fake acknowledges but leaves entries - the Class 11 residue
    assert cache.values(_TENANT_A)


def test_unscoped_cache_cannot_isolate_a_tenant_for_deletion() -> None:
    # An unscoped cache exposes every value to each tenant and cannot delete one
    # tenant's entries - the residue Class 11 erasure verification surfaces.
    cache = FakeCache(tenant_scoped=False)
    cache.set(_TENANT_A, "k", "value containing CANARY-X")
    assert "value containing CANARY-X" in cache.values(_TENANT_B)
    cache.delete(_TENANT_A)
    assert "value containing CANARY-X" in cache.values(_TENANT_B)


def test_model_delete_drops_a_tenants_adapter() -> None:
    model = FakeModel()
    model.train_adapter(_TENANT_A, ["fine-tune sample CANARY-X"])
    assert "CANARY-X" in model.infer(_TENANT_A, "CANARY-X")
    model.delete(_TENANT_A)
    assert "CANARY-X" not in model.infer(_TENANT_A, "CANARY-X")


def test_soft_delete_model_retains_the_adapter() -> None:
    model = FakeModel(soft_delete=True)
    model.train_adapter(_TENANT_A, ["fine-tune sample CANARY-X"])
    model.delete(_TENANT_A)
    # the soft-delete fake acknowledges but keeps the adapter - the Class 11 residue
    assert "CANARY-X" in model.infer(_TENANT_A, "CANARY-X")


def test_soft_delete_observability_reports_the_capability() -> None:
    """The fake's capability self-report tracks the soft_delete knob (§11)."""
    assert FakeObservability(soft_delete=True).supports(Capability.SOFT_DELETE)
    assert not FakeObservability().supports(Capability.SOFT_DELETE)


def test_search_index_search_is_scoped_to_a_tenant() -> None:
    search = FakeSearchIndex()
    assert isinstance(search, SearchIndexAdapter)
    assert search.supports(Capability.TEXT_SEARCH)
    search.index(_TENANT_A, "alpha document mentioning CANARY-A")
    search.index(_TENANT_B, "beta document mentioning CANARY-B")
    # search is scoped to the tenant: tenant A never sees tenant B's documents
    assert search.search(_TENANT_A, "document") == ["alpha document mentioning CANARY-A"]


def test_search_index_delete_clears_a_tenants_documents() -> None:
    search = FakeSearchIndex()
    search.index(_TENANT_A, "document mentioning CANARY-X")
    assert search.search(_TENANT_A, "CANARY-X")
    search.delete(_TENANT_A)
    assert search.search(_TENANT_A, "CANARY-X") == []


def test_soft_delete_search_index_retains_documents() -> None:
    search = FakeSearchIndex(soft_delete=True)
    assert search.supports(Capability.SOFT_DELETE)
    search.index(_TENANT_A, "document mentioning CANARY-X")
    search.delete(_TENANT_A)
    # the soft-delete fake acknowledges but leaves documents - the Class 11 residue
    assert search.search(_TENANT_A, "CANARY-X")


def test_eval_set_search_is_scoped_to_a_tenant() -> None:
    eval_set = FakeEvalSet()
    assert isinstance(eval_set, EvalSetAdapter)
    assert eval_set.supports(Capability.TEXT_SEARCH)
    eval_set.add(_TENANT_A, "alpha fixture mentioning CANARY-A")
    eval_set.add(_TENANT_B, "beta fixture mentioning CANARY-B")
    # the eval set is scoped to the tenant: tenant A never sees tenant B's fixtures
    assert eval_set.search(_TENANT_A, "fixture") == ["alpha fixture mentioning CANARY-A"]


def test_eval_set_delete_clears_a_tenants_fixtures() -> None:
    eval_set = FakeEvalSet()
    eval_set.add(_TENANT_A, "fixture mentioning CANARY-X")
    assert eval_set.search(_TENANT_A, "CANARY-X")
    eval_set.delete(_TENANT_A)
    assert eval_set.search(_TENANT_A, "CANARY-X") == []


def test_soft_delete_eval_set_retains_fixtures() -> None:
    eval_set = FakeEvalSet(soft_delete=True)
    assert eval_set.supports(Capability.SOFT_DELETE)
    eval_set.add(_TENANT_A, "fixture mentioning CANARY-X")
    eval_set.delete(_TENANT_A)
    # the soft-delete fake acknowledges but leaves fixtures - the Class 11 residue
    assert eval_set.search(_TENANT_A, "CANARY-X")
