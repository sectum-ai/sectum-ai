"""An observation is labelled by the adapter that produced it, not by its action.

The runner used to stamp a literal onto every observation - a ``vector.fetch``
step always produced ``Surface.VECTOR_DB``. That is correct exactly while one
family can ever fill a slot, and the label lands in the signed evidence, the
scorecard's per-class lines, and the audit pack's findings.

It is the same shape as the provenance bug v0.9.0 fixed: a fact read off
something incidental (there, an adapter's mutable ``name``; here, an action
string) rather than declared by the thing it describes. Declaring ``surface`` on
the adapter makes reuse of a slot label itself honestly instead of inheriting
whatever the action happened to mean.
"""

import re
from pathlib import Path
from uuid import UUID

from sectum_ai.adapters import FakeVectorStore
from sectum_ai.adapters.base import (
    Adapter,
    AgentAdapter,
    BackupAdapter,
    CacheAdapter,
    EvalSetAdapter,
    MCPAdapter,
    MemoryAdapter,
    ModelAdapter,
    ObservabilityAdapter,
    RAGPipelineAdapter,
    SearchIndexAdapter,
    VectorStoreAdapter,
)
from sectum_ai.runner import Runner
from sectum_ai.spec import CorpusDocument, ProbeStep, Substrate, Surface
from sectum_ai.substrate import build_substrate, default_scenario

# The published labelling contract: which surface each adapter family speaks for.
_EXPECTED: dict[type[Adapter], Surface] = {
    VectorStoreAdapter: Surface.VECTOR_DB,
    RAGPipelineAdapter: Surface.RAG_PIPELINE,
    ObservabilityAdapter: Surface.TRACING,
    AgentAdapter: Surface.AGENT_FRAMEWORK,
    MCPAdapter: Surface.MCP,
    CacheAdapter: Surface.SEMANTIC_CACHE,
    ModelAdapter: Surface.MODEL_ADAPTER,
    MemoryAdapter: Surface.AGENT_MEMORY,
    SearchIndexAdapter: Surface.SEARCH_INDEX,
    EvalSetAdapter: Surface.EVAL_SET,
    BackupAdapter: Surface.BACKUP,
}


def _substrate() -> Substrate:
    return build_substrate(default_scenario(seed=1, corpus_size=24))


def _step(tenant: UUID, action: str, payload: dict[str, str]) -> ProbeStep:
    return ProbeStep(
        step_id="s1", probe_id="test", actor_tenant_id=tenant, action=action, payload=payload
    )


def test_every_family_base_declares_its_surface() -> None:
    for base, surface in _EXPECTED.items():
        assert getattr(base, "surface", None) is surface, f"{base.__name__} mislabels its surface"


def test_no_family_base_is_left_without_a_surface() -> None:
    # A new family that inherits nothing would raise AttributeError deep in the
    # runner, at the moment it builds an observation - long after the useful place.
    missing = [
        cls.__name__ for cls in Adapter.__subclasses__() if getattr(cls, "surface", None) is None
    ]
    assert not missing, f"adapter families with no declared surface: {missing}"


def test_a_concrete_adapter_inherits_its_family_s_surface() -> None:
    assert FakeVectorStore().surface is Surface.VECTOR_DB


def test_the_runner_labels_an_observation_from_the_adapter_not_the_action() -> None:
    """The forward-looking guarantee, and the reason this change exists.

    An adapter that fills the vector slot while speaking for a different surface -
    an application's own resource API, say - must have its findings recorded
    against that surface. Under the old literal every such finding would have been
    filed as ``vector_db`` in the signed pack.
    """

    class ApiBackedStore(FakeVectorStore):
        surface = Surface.API

    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    store = ApiBackedStore()
    store.upsert(
        tenant,
        [
            CorpusDocument(
                doc_id="d-1",
                tenant_id=tenant,
                doc_type="note",
                title="t",
                content="marker content",
            )
        ],
    )
    runner = Runner(substrate, vector=store)

    fetched = runner._execute(_step(tenant, "vector.fetch", {"doc_id": "d-1"}))
    queried = runner._execute(_step(tenant, "vector.query", {"query": "marker"}))
    assert fetched.surface is Surface.API
    assert queried.surface is Surface.API


def test_an_ordinary_vector_store_still_labels_itself_vector_db() -> None:
    # The change must be behaviour-preserving for every adapter shipping today.
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    runner = Runner(substrate, vector=FakeVectorStore())
    observation = runner._execute(_step(tenant, "vector.fetch", {"doc_id": "missing"}))
    assert observation.surface is Surface.VECTOR_DB


def test_the_runner_holds_no_hardcoded_surface_literal() -> None:
    # The guard against regression: a new action handler that writes
    # `surface=Surface.X` reintroduces exactly the coupling this removed, and
    # nothing else would catch it - the label is only wrong for an adapter that
    # does not exist yet.
    import sectum_ai.runner as runner_module

    source = Path(runner_module.__file__).read_text()
    literals = re.findall(r"surface=Surface\.[A-Z_]+", source)
    assert not literals, f"runner hardcodes surfaces instead of reading the adapter: {literals}"
