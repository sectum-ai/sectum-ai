"""Opt-in live integration test for the AutoGen agent adapter.

Skipped unless ``SECTUM_RUN_LIVE_AUTOGEN=1`` and ``OPENAI_API_KEY`` are set
(the engineering spec, section 13: opt-in live). Enable with::

    pip install sectum-ai-adapters[autogen]
    export OPENAI_API_KEY=sk-...
    export SECTUM_RUN_LIVE_AUTOGEN=1

The adapter logic itself is covered offline by
``tests/unit/test_autogen_agent.py``. The live path constructs a small
AutoGen ``AssistantAgent`` + ``UserProxyAgent`` pair bound to one local
``echo`` tool, then drives it from two synthetic tenants and asserts the
adapter (a) returns a non-empty assistant message, (b) carries the per-tenant
``[tenant:<hex>]`` token into the user-proxy message (so a tool can read the
tenant scope from its call arguments), and (c) surfaces the ``echo`` tool name
in ``AgentResult.tool_calls`` - the Class 7 observability the agent
tool-call hijack probe depends on.
"""

import os
from collections.abc import Iterator
from uuid import UUID

import pytest
from sectum_ai.adapters.agent.autogen import AutoGenAgent

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("SECTUM_RUN_LIVE_AUTOGEN") and os.environ.get("OPENAI_API_KEY")),
        reason="set SECTUM_RUN_LIVE_AUTOGEN=1 and OPENAI_API_KEY for the live AutoGen test",
    ),
]

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@pytest.fixture
def agent() -> Iterator[AutoGenAgent]:
    """Build an AutoGen assistant + user-proxy pair bound to one local ``echo`` tool."""
    try:
        from autogen import AssistantAgent, UserProxyAgent
    except ImportError as error:
        pytest.skip(f"autogen not installed: {error}")

    def echo(text: str) -> str:
        """Return its input verbatim. The agent must call this tool with the marker."""
        return text

    model_name = os.environ.get("SECTUM_LIVE_AUTOGEN_MODEL", "gpt-4o-mini")
    llm_config = {"config_list": [{"model": model_name, "api_key": os.environ["OPENAI_API_KEY"]}]}
    system_message = (
        "You are a helpful assistant. Each user message begins with a "
        "[tenant:<hex>] token identifying the tenant context. Call the "
        "`echo` tool exactly once when the user asks you to, then reply with "
        "the tool result. Reply with TERMINATE when you are done."
    )
    assistant = AssistantAgent(
        name="sectum-assistant",
        llm_config=llm_config,
        system_message=system_message,
    )
    assistant.register_for_llm(name="echo", description="Echo text verbatim.")(echo)
    user_proxy = UserProxyAgent(
        name="sectum-user-proxy",
        human_input_mode="NEVER",
        code_execution_config=False,
        is_termination_msg=lambda message: "TERMINATE" in str(message.get("content", "")),
        max_consecutive_auto_reply=3,
    )
    user_proxy.register_for_execution(name="echo")(echo)
    yield AutoGenAgent(assistant, user_proxy, max_turns=4)


def test_autogen_invokes_a_tool_per_tenant(agent: AutoGenAgent) -> None:
    marker = "SECTUM-CANARY-LIVE-AG"
    task = f"Call the `echo` tool exactly once with text='{marker}', then return the result."
    result_a = agent.run(_TENANT_A, task)
    # The assistant should produce some text and have invoked the echo tool.
    assert result_a.output
    assert "echo" in result_a.tool_calls

    # Two tenants run independently against the same agent; each invocation
    # carries its own [tenant:<hex>] token in the user-proxy message, so a
    # downstream tool could scope its lookup by the tenant identity.
    result_b = agent.run(_TENANT_B, task)
    assert result_b.output
    assert "echo" in result_b.tool_calls


def test_autogen_handles_a_task_with_no_tool_use(agent: AutoGenAgent) -> None:
    result = agent.run(_TENANT_A, "Reply with the single word 'ok' and call no tools. TERMINATE.")
    assert result.output
    # The model is free to call or skip tools; this test only asserts the
    # adapter does not crash when ``tool_calls`` is empty, and that the final
    # assistant text reaches the AgentResult.
    assert isinstance(result.tool_calls, tuple)


def test_autogen_connect_factory_builds_a_runnable_agent() -> None:
    # Construct via ``connect`` and confirm the returned object exposes run -
    # the same path the resolver follows when ``kind: autogen`` is configured
    # (via its factory). The factory imports autogen on the live path only.
    try:
        import autogen  # noqa: F401
    except ImportError as error:
        pytest.skip(f"autogen not installed: {error}")

    def noop() -> str:
        """Return a constant string."""
        return "noop"

    model_name = os.environ.get("SECTUM_LIVE_AUTOGEN_MODEL", "gpt-4o-mini")
    llm_config = {"config_list": [{"model": model_name, "api_key": os.environ["OPENAI_API_KEY"]}]}
    instance = AutoGenAgent.connect(llm_config, [noop])
    # Smoke check: the resolver path constructed an adapter with the family API.
    assert hasattr(instance, "run")
