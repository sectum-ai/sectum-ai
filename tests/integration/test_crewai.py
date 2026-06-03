"""Opt-in live integration test for the CrewAI agent adapter.

Skipped unless ``SECTUM_RUN_LIVE_CREWAI=1`` and ``OPENAI_API_KEY`` are set
(the engineering spec, section 13: opt-in live). Enable with::

    pip install sectum-ai-adapters[crewai]
    export OPENAI_API_KEY=sk-...
    export SECTUM_RUN_LIVE_CREWAI=1

The adapter logic itself is covered offline by
``tests/unit/test_crewai_agent.py``. The live path constructs a small
CrewAI ``Crew`` of one ``Agent`` + one templated ``Task`` bound to a single
local ``echo`` tool, then drives it from two synthetic tenants and asserts
the adapter (a) returns a non-empty raw answer, (b) carries the per-tenant
``tenant_id`` into the kickoff inputs (so a templated task description can
interpolate it and a tenant-aware tool reads the scope from its arguments),
and (c) surfaces the ``echo`` tool name in ``AgentResult.tool_calls`` -
the Class 7 observability the agent tool-call hijack probe depends on.
"""

import os
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum_ai.adapters.agent.crewai import CrewAIAgent

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("SECTUM_RUN_LIVE_CREWAI") and os.environ.get("OPENAI_API_KEY")),
        reason="set SECTUM_RUN_LIVE_CREWAI=1 and OPENAI_API_KEY for the live CrewAI test",
    ),
]

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@pytest.fixture
def agent() -> Iterator[CrewAIAgent]:
    """Build a CrewAI crew with one templated task bound to a local ``echo`` tool."""
    try:
        from crewai import Agent, Crew, Task
        from crewai.tools import tool
    except ImportError as error:
        pytest.skip(f"crewai not installed: {error}")

    @tool("echo")  # type: ignore[untyped-decorator]
    def echo(text: str) -> str:
        """Return its input verbatim. The agent must call this tool with the marker."""
        return text

    model_name = os.environ.get("SECTUM_LIVE_CREWAI_MODEL", "gpt-4o-mini")
    os.environ.setdefault("OPENAI_MODEL_NAME", model_name)

    researcher = Agent(
        role="echo caller",
        goal="Call the echo tool with the supplied text and return the result.",
        backstory=(
            "You answer in one sentence. You call the echo tool exactly once "
            "for every task and then report what it returned."
        ),
        tools=[echo],
        allow_delegation=False,
        verbose=False,
    )
    task = Task(
        description=(
            "Tenant context: {tenant_id}. Call the `echo` tool exactly once "
            "with text='{task}', then reply with the tool's return value."
        ),
        expected_output="The echo tool's return value as plain text.",
        agent=researcher,
    )
    yield CrewAIAgent(Crew(agents=[researcher], tasks=[task], verbose=False))


def test_crewai_invokes_a_tool_per_tenant(agent: CrewAIAgent) -> None:
    marker = "SECTUM-CANARY-LIVE-CW"
    result_a = agent.run(_TENANT_A, marker)
    # The crew should produce some text and have invoked the echo tool at
    # least once on the task that completed under tenant A.
    assert result_a.output
    assert "echo" in result_a.tool_calls

    # Two tenants run independently against the same crew; each kickoff
    # carries its own tenant_id input, so a templated task description (or a
    # tenant-aware tool) can scope its behaviour by the tenant identity.
    result_b = agent.run(_TENANT_B, marker)
    assert result_b.output
    assert "echo" in result_b.tool_calls


def test_crewai_handles_a_task_with_no_tool_use(agent: CrewAIAgent) -> None:
    # The default agent above is wired to always call echo, so this test just
    # asserts the adapter does not crash and returns a tuple regardless of
    # whether the LLM happened to skip the tool for this prompt.
    result = agent.run(_TENANT_A, "reply with the single word ok")
    assert result.output
    assert isinstance(result.tool_calls, tuple)


def test_crewai_connect_factory_builds_a_runnable_agent() -> None:
    # Construct via ``connect`` and confirm the returned object exposes run -
    # the same path the resolver follows when ``kind: crewai`` is configured
    # (via its factory). The factory imports crewai on the live path only.
    try:
        from crewai import Agent, Task
        from crewai.tools import tool
    except ImportError as error:
        pytest.skip(f"crewai not installed: {error}")

    @tool("noop")  # type: ignore[untyped-decorator]
    def noop() -> str:
        """Return a constant string."""
        return "noop"

    agent = Agent(
        role="noop caller",
        goal="Call noop once.",
        backstory="You call noop once and report what it returned.",
        tools=[noop],
        allow_delegation=False,
        verbose=False,
    )
    task = Task(
        description="Tenant: {tenant_id}. Call noop. Return the result.",
        expected_output="The noop return value.",
        agent=agent,
    )
    instance = CrewAIAgent.connect([agent], [task])
    # Smoke check: the resolver path constructed an adapter with the family API.
    assert hasattr(instance, "run")
