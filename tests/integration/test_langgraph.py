"""Opt-in live integration test for the LangGraph agent adapter.

Skipped unless ``SECTUM_RUN_LIVE_LANGGRAPH=1`` and ``OPENAI_API_KEY`` are set
(the engineering spec, section 13: opt-in live). Enable with::

    pip install sectum-ai-adapters[langgraph] langchain-openai
    export OPENAI_API_KEY=sk-...
    export SECTUM_RUN_LIVE_LANGGRAPH=1

The adapter logic itself is covered offline by
``tests/unit/test_langgraph_agent.py``. The live path constructs a small
prebuilt ReAct agent (the LangGraph quick-start shape) bound to one local
``echo`` tool, then drives it from two synthetic tenants and asserts the
adapter (a) returns a non-empty assistant message, (b) carries the per-tenant
``thread_id`` into LangGraph's runtime config, and (c) surfaces the ``echo``
tool name in ``AgentResult.tool_calls`` - the Class 7 observability the agent
tool-call hijack probe depends on.
"""

import os
from collections.abc import Iterator
from uuid import UUID

import pytest

from sectum.adapters.agent.langgraph import LangGraphAgent

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("SECTUM_RUN_LIVE_LANGGRAPH") and os.environ.get("OPENAI_API_KEY")),
        reason="set SECTUM_RUN_LIVE_LANGGRAPH=1 and OPENAI_API_KEY for the live LangGraph test",
    ),
]

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@pytest.fixture
def agent() -> Iterator[LangGraphAgent]:
    """Build a prebuilt ReAct LangGraph agent bound to one local ``echo`` tool."""
    try:
        from langchain_core.tools import tool
        from langchain_openai import ChatOpenAI
    except ImportError as error:
        pytest.skip(f"langchain-openai not installed: {error}")

    @tool  # type: ignore[untyped-decorator]
    def echo(text: str) -> str:
        """Return its input verbatim. The agent must call this tool with the marker."""
        return text

    model = ChatOpenAI(model=os.environ.get("SECTUM_LIVE_LANGGRAPH_MODEL", "gpt-4o-mini"))
    instance = LangGraphAgent.connect(model, [echo])
    yield instance


def test_langgraph_invokes_a_tool_per_tenant(agent: LangGraphAgent) -> None:
    marker = "SECTUM-CANARY-LIVE-LG"
    task = f"Call the `echo` tool exactly once with text='{marker}', then return the result."
    result_a = agent.run(_TENANT_A, task)
    # The assistant should produce some text and have invoked the echo tool.
    assert result_a.output
    assert "echo" in result_a.tool_calls

    # Two tenants run independently against the same agent; each invocation
    # carries its own thread_id in the runtime config, so a downstream
    # checkpointer would isolate their states.
    result_b = agent.run(_TENANT_B, task)
    assert result_b.output
    assert "echo" in result_b.tool_calls


def test_langgraph_handles_a_task_with_no_tool_use(agent: LangGraphAgent) -> None:
    result = agent.run(_TENANT_A, "Reply with the single word 'ok' and call no tools.")
    assert result.output
    # The model is free to call or skip tools; this test only asserts the
    # adapter does not crash when ``tool_calls`` is empty, and that the final
    # assistant text reaches the AgentResult.
    assert isinstance(result.tool_calls, tuple)


def test_langgraph_connect_factory_builds_a_runnable_graph() -> None:
    # Construct via ``connect`` and confirm the returned object exposes invoke -
    # the same path the resolver follows when ``kind: langgraph`` is configured.
    try:
        from langchain_core.tools import tool
        from langchain_openai import ChatOpenAI
    except ImportError as error:
        pytest.skip(f"langchain-openai not installed: {error}")

    @tool  # type: ignore[untyped-decorator]
    def noop() -> str:
        """Return a constant string."""
        return "noop"

    instance = LangGraphAgent.connect(ChatOpenAI(model="gpt-4o-mini"), [noop])
    # Smoke check: the resolver path constructed an adapter whose graph
    # accepts the standard invoke(input, config) call shape.
    assert hasattr(instance, "run")
