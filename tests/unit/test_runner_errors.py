"""The runner raises a typed error when a step needs an adapter that is absent."""

from uuid import UUID

import pytest

from sectum.runner import Runner, retrieval_pivot_rate
from sectum.spec import AdapterError, ProbeStep
from sectum.substrate import build_substrate, default_scenario

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


def _runner() -> Runner:
    # No adapters supplied: every action handler must hit its guard.
    return Runner(build_substrate(default_scenario(seed=1)))


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
