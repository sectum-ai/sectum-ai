"""The runner raises a typed error when a step needs an adapter that is absent."""

from uuid import UUID

import pytest

from sectum_ai.adapters import FakeVectorStore
from sectum_ai.runner import Runner, retrieval_pivot_rate
from sectum_ai.spec import AdapterError, ProbeStep
from sectum_ai.substrate import build_substrate, default_scenario

_ACTIONS = (
    "vector.query",
    "vector.fetch",
    "vector.upsert",
    "cache.set",
    "cache.get",
    "model.train",
    "model.infer",
    "mcp.invoke",
    "memory.write",
    "memory.recall",
    "rag.ask",
    "observability.search",
    "agent.run",
)


def _runner(vector: FakeVectorStore | None = None) -> Runner:
    # No adapters supplied: every action handler must hit its guard. Pass a
    # vector adapter to reach the payload-validation path inside vector.query.
    return Runner(build_substrate(default_scenario(seed=1)), vector=vector)


def _step(action: str) -> ProbeStep:
    return ProbeStep(step_id="s-1", probe_id="p", actor_tenant_id=UUID(int=1), action=action)


@pytest.mark.parametrize("action", _ACTIONS)
def test_runner_requires_the_action_adapter(action: str) -> None:
    with pytest.raises(AdapterError):
        _runner()._execute(_step(action))


def test_runner_rejects_an_unknown_action() -> None:
    with pytest.raises(AdapterError, match="cannot execute"):
        _runner()._execute(_step("bogus.action"))


def test_retrieval_pivot_rate_is_zero_without_steps() -> None:
    assert retrieval_pivot_rate([]) == 0.0


def test_non_numeric_k_payload_raises_adapter_error() -> None:
    # A malformed payload is a config error (typed SectumError -> exit 3), not a
    # bare ValueError traceback (exit 1).
    runner = _runner(vector=FakeVectorStore())
    step = ProbeStep(
        step_id="s",
        probe_id="p",
        actor_tenant_id=UUID(int=1),
        action="vector.query",
        payload={"k": "not-a-number", "query": "q"},
    )
    with pytest.raises(AdapterError, match="must be an integer"):
        runner._execute(step)


def test_missing_required_query_payload_raises_adapter_error() -> None:
    runner = _runner(vector=FakeVectorStore())
    step = ProbeStep(
        step_id="s",
        probe_id="p",
        actor_tenant_id=UUID(int=1),
        action="vector.query",
        payload={},
    )
    with pytest.raises(AdapterError, match="missing required key"):
        runner._execute(step)
