"""Tests for the scenario runner's action dispatch.

The runner is exercised end-to-end by the probe tests; these tests cover the
three actions that have no consuming probe yet (``rag.ask``,
``observability.search``, ``agent.run``).
"""

from uuid import UUID

import pytest

from sectum.adapters import FakeAgent, FakeObservability, FakeRAGPipeline
from sectum.runner import Runner
from sectum.spec import AdapterError, CorpusDocument, ProbeStep, Substrate, Surface
from sectum.substrate import build_substrate, default_scenario


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
