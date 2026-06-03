"""Tests for the scenario runner's action dispatch.

The runner is exercised end-to-end by the probe tests; these tests cover every
action handler in isolation — both the happy path (the right adapter receives
the right payload, returns the right surface) and the negative path (no
adapter wired → a typed ``AdapterError``).
"""

from uuid import UUID

import pytest

import sectum_ai.probes as probes
from sectum_ai.adapters import (
    FakeAgent,
    FakeCache,
    FakeMCP,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeRAGPipeline,
    FakeVectorStore,
)
from sectum_ai.probes import RagEntityBleedProbe
from sectum_ai.runner import Runner
from sectum_ai.spec import (
    AccessOutcome,
    AdapterError,
    ConfigError,
    CorpusDocument,
    ProbeStep,
    Substrate,
    Surface,
)
from sectum_ai.substrate import build_substrate, default_scenario


def _substrate() -> Substrate:
    return build_substrate(default_scenario(seed=1, corpus_size=24))


def _step(tenant: UUID, action: str, payload: dict[str, str]) -> ProbeStep:
    return ProbeStep(
        step_id="s1",
        probe_id="test",
        actor_tenant_id=tenant,
        action=action,
        payload=payload,
    )


def test_runner_dispatches_rag_ask_to_the_rag_adapter() -> None:
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    rag = FakeRAGPipeline()
    rag.index(
        tenant,
        [
            CorpusDocument(
                doc_id="d-1",
                tenant_id=tenant,
                doc_type="note",
                title="alpha note",
                content="alpha content here",
            )
        ],
    )
    runner = Runner(substrate, rag=rag)
    observation = runner._execute(_step(tenant, "rag.ask", {"query": "alpha"}))
    assert observation.surface == Surface.RAG_PIPELINE
    assert "alpha" in observation.raw_response


def test_runner_rag_ask_without_a_rag_adapter_raises_adapter_error() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs a rag"):
        runner._execute(_step(substrate.tenants[0].tenant_id, "rag.ask", {"query": "x"}))


def test_runner_dispatches_observability_search_to_the_observability_adapter() -> None:
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    obs = FakeObservability()
    obs.record(tenant, "project-a", "trace containing CANARY-XYZ")
    runner = Runner(substrate, observability=obs)
    observation = runner._execute(_step(tenant, "observability.search", {"marker": "CANARY-XYZ"}))
    assert observation.surface == Surface.TRACING
    assert "CANARY-XYZ" in observation.raw_response


def test_runner_observability_search_without_an_observability_adapter_raises() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs an observability"):
        runner._execute(
            _step(substrate.tenants[0].tenant_id, "observability.search", {"marker": "x"})
        )


def test_runner_dispatches_agent_run_to_the_agent_adapter() -> None:
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    agent = FakeAgent()
    runner = Runner(substrate, agent=agent)
    observation = runner._execute(_step(tenant, "agent.run", {"task": "summarize"}))
    assert observation.surface == Surface.AGENT_FRAMEWORK
    assert "summarize" in observation.raw_response


def test_runner_agent_run_without_an_agent_adapter_raises_adapter_error() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs an agent"):
        runner._execute(_step(substrate.tenants[0].tenant_id, "agent.run", {"task": "x"}))


def test_runner_unknown_action_raises_adapter_error() -> None:
    """An unsupported action ID is a typed AdapterError so the CLI exits 3 cleanly."""
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="cannot execute action"):
        runner._execute(_step(substrate.tenants[0].tenant_id, "not.an.action", {}))


# ---------------------------------------------------------------------------
# vector.* actions
# ---------------------------------------------------------------------------


def _seed_vector(tenant: UUID, doc_id: str = "d-1", content: str = "alpha note") -> FakeVectorStore:
    """Build a FakeVectorStore pre-seeded with one document under ``tenant``."""
    store = FakeVectorStore()
    store.upsert(
        tenant,
        [
            CorpusDocument(
                doc_id=doc_id,
                tenant_id=tenant,
                doc_type="note",
                title=doc_id,
                content=content,
            )
        ],
    )
    return store


def test_runner_dispatches_vector_query_to_the_vector_adapter() -> None:
    # The seeded content carries a distinctive marker that's NOT in the
    # query string; the assertion catches a regression where the runner
    # bypasses the adapter and echoes the query verbatim (in which case
    # the marker would not appear in the response).
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    store = _seed_vector(tenant, content="alpha bravo DISTINCT-VQ-MARKER")
    runner = Runner(substrate, vector=store)
    observation = runner._execute(_step(tenant, "vector.query", {"query": "alpha", "k": "3"}))
    assert observation.surface == Surface.VECTOR_DB
    assert "DISTINCT-VQ-MARKER" in observation.raw_response


def test_runner_vector_query_without_a_vector_adapter_raises() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs a vector"):
        runner._execute(_step(substrate.tenants[0].tenant_id, "vector.query", {"query": "x"}))


def test_runner_dispatches_vector_fetch_to_the_vector_adapter() -> None:
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    store = _seed_vector(tenant, doc_id="d-7", content="seven content")
    runner = Runner(substrate, vector=store)
    observation = runner._execute(_step(tenant, "vector.fetch", {"doc_id": "d-7"}))
    assert observation.surface == Surface.VECTOR_DB
    assert observation.raw_response == "seven content"
    # Class 1 deny-semantics: the object surfaced, so the outcome is RETURNED.
    assert observation.access_outcome == AccessOutcome.RETURNED


def test_runner_vector_fetch_returns_empty_string_when_doc_missing() -> None:
    # The runner emits an empty raw_response when the adapter returns None;
    # the detection pipeline then treats that as "no leak observed", which is
    # the right outcome for an authorized-but-empty 200 vs a proper 403.
    # Empty store is the cleanest fixture - any seeded doc would be unused
    # and only a noise source on a future helper change.
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    runner = Runner(substrate, vector=FakeVectorStore())
    observation = runner._execute(_step(tenant, "vector.fetch", {"doc_id": "no-such-id"}))
    assert observation.surface == Surface.VECTOR_DB
    assert observation.raw_response == ""
    # The ambiguous "200-empty" case the spec (Class 1) calls out: an absent
    # object is EMPTY, not a proven deny.
    assert observation.access_outcome == AccessOutcome.EMPTY


def test_runner_vector_fetch_without_a_vector_adapter_raises() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs a vector"):
        runner._execute(_step(substrate.tenants[0].tenant_id, "vector.fetch", {"doc_id": "x"}))


def test_runner_dispatches_vector_upsert_to_the_vector_adapter() -> None:
    # `vector.upsert` is the planting path Class 3 (RAG poisoning) uses to
    # write a tenant-Y document into the shared index; the runner builds a
    # CorpusDocument with `doc_type="poison"` and routes it to the store.
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    store = FakeVectorStore()
    runner = Runner(substrate, vector=store)
    observation = runner._execute(
        _step(tenant, "vector.upsert", {"doc_id": "poison-1", "content": "leak bait"})
    )
    assert observation.surface == Surface.VECTOR_DB
    assert observation.raw_response == ""
    # The store now carries the planted document; a fetch from the same
    # tenant returns it verbatim.
    hit = store.fetch(tenant, "poison-1")
    assert hit is not None and hit.content == "leak bait"


def test_runner_vector_upsert_without_a_vector_adapter_raises() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs a vector"):
        runner._execute(
            _step(
                substrate.tenants[0].tenant_id,
                "vector.upsert",
                {"doc_id": "x", "content": "y"},
            )
        )


# ---------------------------------------------------------------------------
# cache.* actions
# ---------------------------------------------------------------------------


def test_runner_dispatches_cache_set_to_the_cache_adapter() -> None:
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    cache = FakeCache()
    runner = Runner(substrate, cache=cache)
    observation = runner._execute(
        _step(tenant, "cache.set", {"key": "q", "value": "cached-answer"})
    )
    assert observation.surface == Surface.SEMANTIC_CACHE
    assert observation.raw_response == ""
    assert cache.get(tenant, "q") == "cached-answer"


def test_runner_cache_set_without_a_cache_adapter_raises() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs a cache"):
        runner._execute(
            _step(substrate.tenants[0].tenant_id, "cache.set", {"key": "k", "value": "v"})
        )


def test_runner_dispatches_cache_get_to_the_cache_adapter() -> None:
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    cache = FakeCache()
    cache.set(tenant, "k", "cached-value")
    runner = Runner(substrate, cache=cache)
    observation = runner._execute(_step(tenant, "cache.get", {"key": "k"}))
    assert observation.surface == Surface.SEMANTIC_CACHE
    assert observation.raw_response == "cached-value"


def test_runner_cache_get_returns_empty_string_when_key_missing() -> None:
    # A missing key surfaces as an empty raw_response; the detection pipeline
    # treats that as "no leak observed", same shape as vector.fetch above.
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    runner = Runner(substrate, cache=FakeCache())
    observation = runner._execute(_step(tenant, "cache.get", {"key": "missing"}))
    assert observation.raw_response == ""


def test_runner_cache_get_without_a_cache_adapter_raises() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs a cache"):
        runner._execute(_step(substrate.tenants[0].tenant_id, "cache.get", {"key": "x"}))


# ---------------------------------------------------------------------------
# model.* actions
# ---------------------------------------------------------------------------


def test_runner_dispatches_model_train_to_the_model_adapter() -> None:
    # `model.train` is the path Class 9 (LoRA cross-tenant) uses to train an
    # adapter on a corpus that includes a memorizable canary phrase.
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    model = FakeModel()
    runner = Runner(substrate, model=model)
    observation = runner._execute(_step(tenant, "model.train", {"text": "SECRET-XYZ"}))
    assert observation.surface == Surface.MODEL_ADAPTER
    assert observation.raw_response == ""
    # The model now reproduces the trained string when prompted with a prefix
    # (the FakeModel's leaky-fake convention).
    assert "SECRET-XYZ" in model.infer(tenant, "SECRET")


def test_runner_model_train_without_a_model_adapter_raises() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs a model"):
        runner._execute(_step(substrate.tenants[0].tenant_id, "model.train", {"text": "x"}))


def test_runner_dispatches_model_infer_to_the_model_adapter() -> None:
    # The runner must forward the prompt to model.infer (not echo it, not
    # short-circuit on a constant). Train the FakeModel with a distinctive
    # phrase and prompt with its prefix; the surfaced raw_response carries
    # the trained phrase iff the dispatch actually called model.infer with
    # the right prompt argument.
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    model = FakeModel()
    model.train_adapter(tenant, ["FOXTROT-LEAK-MARKER token"])
    runner = Runner(substrate, model=model)
    observation = runner._execute(_step(tenant, "model.infer", {"prompt": "FOXTROT"}))
    assert observation.surface == Surface.MODEL_ADAPTER
    assert "FOXTROT-LEAK-MARKER" in observation.raw_response


def test_runner_model_infer_without_a_model_adapter_raises() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs a model"):
        runner._execute(_step(substrate.tenants[0].tenant_id, "model.infer", {"prompt": "x"}))


# ---------------------------------------------------------------------------
# mcp.invoke action
# ---------------------------------------------------------------------------


def test_runner_dispatches_mcp_invoke_to_the_mcp_adapter() -> None:
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    mcp = FakeMCP()
    mcp.provision(tenant, "k-1", "stored-value")
    runner = Runner(substrate, mcp=mcp)
    observation = runner._execute(_step(tenant, "mcp.invoke", {"tool": "lookup", "key": "k-1"}))
    assert observation.surface == Surface.MCP
    assert "stored-value" in observation.raw_response


def test_runner_mcp_invoke_forwards_tool_arguments_excluding_the_tool_name() -> None:
    # The runner builds the tool-call arguments by stripping the `tool` key
    # and passing the rest through verbatim; a probe relies on this when it
    # plants a `token` field for the token-passthrough sub-probe. The
    # assertion records the exact arguments dict the adapter received so a
    # regression that stops stripping ``tool`` is caught — checking the
    # observation's raw response alone would pass either way because
    # FakeMCP's lookup tool reads only the ``key`` arg.
    from dataclasses import dataclass

    @dataclass
    class _Invocation:
        tool: str
        arguments: dict[str, str]
        user: UUID | None

    invocations: list[_Invocation] = []

    class _SpyMCP(FakeMCP):
        def invoke(  # type: ignore[override]
            self,
            tenant: UUID,
            tool: str,
            arguments: dict[str, str],
            *,
            user: UUID | None = None,
        ) -> object:
            invocations.append(_Invocation(tool=tool, arguments=dict(arguments), user=user))
            return super().invoke(tenant, tool, arguments, user=user)

    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    mcp = _SpyMCP()
    mcp.provision(tenant, "k-2", "value-2")
    runner = Runner(substrate, mcp=mcp)
    observation = runner._execute(
        _step(tenant, "mcp.invoke", {"tool": "lookup", "key": "k-2", "extra": "ignored"})
    )
    assert observation.surface == Surface.MCP
    assert "value-2" in observation.raw_response
    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.tool == "lookup"
    assert "tool" not in invocation.arguments, (
        f"runner forwarded the 'tool' key into the call arguments: {invocation.arguments}"
    )
    # Every non-tool payload key reaches the adapter unchanged.
    assert invocation.arguments == {"key": "k-2", "extra": "ignored"}
    # The step has no actor_user_id, so the adapter sees user=None — pins
    # the boundary so a regression that started materialising a stray
    # default user (e.g., the substrate's first user) would be caught.
    assert invocation.user is None


def test_runner_mcp_invoke_without_an_mcp_adapter_raises() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs an MCP"):
        runner._execute(
            _step(substrate.tenants[0].tenant_id, "mcp.invoke", {"tool": "lookup", "key": "k"})
        )


# ---------------------------------------------------------------------------
# memory.* actions
# ---------------------------------------------------------------------------


def test_runner_dispatches_memory_write_to_the_memory_adapter() -> None:
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    memory = FakeMemory()
    runner = Runner(substrate, memory=memory)
    observation = runner._execute(_step(tenant, "memory.write", {"text": "remember this"}))
    assert observation.surface == Surface.AGENT_MEMORY
    assert observation.raw_response == ""
    # The write landed: recalling the same query returns it.
    assert "remember this" in "\n".join(memory.recall(tenant, "remember"))


def test_runner_memory_write_without_a_memory_adapter_raises() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs a memory"):
        runner._execute(_step(substrate.tenants[0].tenant_id, "memory.write", {"text": "x"}))


def test_runner_dispatches_memory_recall_to_the_memory_adapter() -> None:
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    memory = FakeMemory()
    memory.remember(tenant, "alpha memo")
    memory.remember(tenant, "beta memo")
    runner = Runner(substrate, memory=memory)
    observation = runner._execute(_step(tenant, "memory.recall", {"query": "alpha"}))
    assert observation.surface == Surface.AGENT_MEMORY
    assert "alpha memo" in observation.raw_response


def test_runner_memory_recall_returns_empty_string_when_nothing_matches() -> None:
    substrate = _substrate()
    tenant = substrate.tenants[0].tenant_id
    runner = Runner(substrate, memory=FakeMemory())
    observation = runner._execute(_step(tenant, "memory.recall", {"query": "anything"}))
    assert observation.surface == Surface.AGENT_MEMORY
    assert observation.raw_response == ""


def test_runner_memory_recall_without_a_memory_adapter_raises() -> None:
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(AdapterError, match="needs a memory"):
        runner._execute(_step(substrate.tenants[0].tenant_id, "memory.recall", {"query": "x"}))


def test_preflight_fails_fast_when_a_required_adapter_is_missing() -> None:
    # rag-entity-bleed requires a vector adapter; a runner without one must fail
    # the preflight (exit-3 ConfigError) before any step runs, not partway through.
    substrate = _substrate()
    runner = Runner(substrate)
    with pytest.raises(ConfigError, match=r"requires adapter.*vector"):
        runner.preflight(RagEntityBleedProbe())


def test_preflight_passes_when_required_adapters_are_present() -> None:
    substrate = _substrate()
    runner = Runner(substrate, vector=FakeVectorStore(shared_index=True))
    runner.preflight(RagEntityBleedProbe())  # no raise


def test_declared_requires_adapters_match_what_each_probe_plans() -> None:
    # Every plan/detect probe's declared requires_adapters must equal the adapter
    # slots its plan() actually drives (the action prefix), so the declaration —
    # and the probe.yaml manifest generated from it — can never drift from reality.
    substrate = _substrate()
    checked = 0
    for name in probes.__all__:
        cls = getattr(probes, name)
        if not (
            isinstance(cls, type) and hasattr(cls, "requires_adapters") and hasattr(cls, "plan")
        ):
            continue
        try:
            probe = cls()
            steps = probe.plan(substrate)
        except (TypeError, AttributeError):
            continue  # workflow-style probes (e.g. erasure) construct/plan differently
        used = {step.action.split(".")[0] for step in steps}
        assert set(probe.requires_adapters) == used, (
            f"{probe.id}: {probe.requires_adapters} != {used}"
        )
        checked += 1
    assert checked >= 11  # all plan/detect probes were covered
