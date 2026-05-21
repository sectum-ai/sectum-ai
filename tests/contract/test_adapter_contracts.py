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
    FakeAgent,
    FakeCache,
    FakeMCP,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeRAGPipeline,
    FakeVectorStore,
    MCPAdapter,
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    RAGPipelineAdapter,
    VectorStoreAdapter,
)
from sectum.spec import AdapterError, CorpusDocument

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


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
