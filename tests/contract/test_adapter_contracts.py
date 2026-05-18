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
    FakeObservability,
    FakeRAGPipeline,
    FakeVectorStore,
    MCPAdapter,
    ObservabilityAdapter,
    RAGPipelineAdapter,
    VectorStoreAdapter,
)
from sectum.spec import CorpusDocument

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
    with pytest.raises(ValueError, match="unknown tool"):
        mcp.invoke(_TENANT_A, "missing", {})


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
