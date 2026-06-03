"""Mock-backed contract tests for the live Anthropic tool-use agent adapter.

Anthropic's Messages API drives a tool-use loop: the model returns
``tool_use`` blocks, the caller executes them, and ``tool_result``
blocks are posted back as a new user message until ``stop_reason:
end_turn``. The adapter caches one conversation history per tenant
and reuses it on every ``run`` call. The adapter's logic is
exercised here against an in-memory ``_FakeAnthropicClient``
stand-in (the engineering spec, sections 11 and 13: live SDK,
mock-backed contract test plus opt-in live).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from sectum_ai.adapters.agent.anthropic_tooluse import AnthropicToolUseAgent
from sectum_ai.adapters.base import AgentAdapter, Capability
from sectum_ai.spec import AdapterError

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@dataclass
class _Turn:
    """One recorded ``run_turn`` call (the messages snapshot the backend received)."""

    messages: list[dict[str, Any]]


@dataclass
class _FakeAnthropicClient:
    """Stand-in: records every turn's input messages and replays a script.

    ``script`` maps the *latest user message text* (after the [tenant:<hex>]
    prefix) to the (final_text, tool_call_names) tuple the backend would
    return after fully unrolling the tool-use loop.
    """

    script: dict[str, tuple[str, tuple[str, ...]]] = field(default_factory=dict)
    turns: list[_Turn] = field(default_factory=list)
    raise_on_turn: Exception | None = None

    def run_turn(self, messages: list[dict[str, Any]]) -> tuple[str, tuple[str, ...]]:
        if self.raise_on_turn is not None:
            raise self.raise_on_turn
        self.turns.append(_Turn(messages=list(messages)))
        latest = messages[-1].get("content", "") if messages else ""
        if isinstance(latest, list):
            # tool_result-shaped content (a list of blocks) - fall back to "".
            suffix = ""
        else:
            suffix = latest.split("] ", 1)[1] if "] " in latest else latest
        return self.script.get(suffix, ("", ()))


def test_anthropic_tooluse_conforms_to_the_family_and_reports_tool_invocation() -> None:
    agent = AnthropicToolUseAgent(_FakeAnthropicClient())
    assert isinstance(agent, AgentAdapter)
    assert agent.supports(Capability.TOOL_INVOCATION)


def test_anthropic_tooluse_keeps_a_separate_conversation_per_tenant() -> None:
    client = _FakeAnthropicClient(script={"hi A": ("hello A", ()), "hi B": ("hello B", ())})
    agent = AnthropicToolUseAgent(client)
    agent.run(_TENANT_A, "hi A")
    agent.run(_TENANT_B, "hi B")
    # Each turn's messages list reflects only that tenant's history:
    # tenant A sees only its own user message, tenant B sees only its
    # own. No cross-tenant leak in the prompt context.
    assert len(client.turns) == 2
    turn_a = client.turns[0]
    turn_b = client.turns[1]
    contents_a = [m["content"] for m in turn_a.messages]
    contents_b = [m["content"] for m in turn_b.messages]
    assert contents_a == [f"[tenant:{_TENANT_A.hex}] hi A"]
    assert contents_b == [f"[tenant:{_TENANT_B.hex}] hi B"]


def test_anthropic_tooluse_reuses_a_tenant_conversation_across_runs() -> None:
    # Anthropic's stateless Messages API requires the caller to track
    # conversation history; the adapter caches it per tenant so the
    # next run for the same tenant carries the prior turn's context.
    client = _FakeAnthropicClient(
        script={"first": ("first reply", ()), "second": ("second reply", ())}
    )
    agent = AnthropicToolUseAgent(client)
    agent.run(_TENANT_A, "first")
    agent.run(_TENANT_A, "second")
    # The second turn's messages carry the full prior history: the
    # first user message, the first assistant reply, then the second
    # user message.
    second = client.turns[1]
    assert [m["role"] for m in second.messages] == ["user", "assistant", "user"]
    assert second.messages[0]["content"] == f"[tenant:{_TENANT_A.hex}] first"
    assert second.messages[1]["content"] == "first reply"
    assert second.messages[2]["content"] == f"[tenant:{_TENANT_A.hex}] second"


def test_anthropic_tooluse_prefixes_every_user_message_with_the_tenant_token() -> None:
    client = _FakeAnthropicClient(script={"hello": ("ok", ())})
    agent = AnthropicToolUseAgent(client)
    agent.run(_TENANT_A, "hello")
    assert client.turns[0].messages[0]["content"] == f"[tenant:{_TENANT_A.hex}] hello"


def test_anthropic_tooluse_returns_the_final_text_and_tool_names() -> None:
    client = _FakeAnthropicClient(script={"look": ("done", ("search", "summarize"))})
    agent = AnthropicToolUseAgent(client)
    result = agent.run(_TENANT_A, "look")
    assert result.output == "done"
    assert result.tool_calls == ("search", "summarize")


def test_anthropic_tooluse_handles_a_no_tool_use_run() -> None:
    client = _FakeAnthropicClient(script={"chat": ("hi there", ())})
    agent = AnthropicToolUseAgent(client)
    result = agent.run(_TENANT_A, "chat")
    assert result.output == "hi there"
    assert result.tool_calls == ()


def test_anthropic_tooluse_returns_empty_output_when_script_misses() -> None:
    agent = AnthropicToolUseAgent(_FakeAnthropicClient())
    result = agent.run(_TENANT_A, "anything")
    assert result.output == ""
    assert result.tool_calls == ()


def test_anthropic_tooluse_wraps_run_turn_failures_in_adapter_error() -> None:
    client = _FakeAnthropicClient(raise_on_turn=RuntimeError("rate limited"))
    agent = AnthropicToolUseAgent(client)
    with pytest.raises(AdapterError, match="anthropic tool-use run failed"):
        agent.run(_TENANT_A, "anything")


def test_anthropic_tooluse_rolls_back_history_on_a_failed_turn() -> None:
    # A turn that raises must not poison the cached conversation
    # history; a retry that succeeds should see the next-attempt user
    # message as the first message in the conversation.
    client = _FakeAnthropicClient(
        script={"second": ("second reply", ())},
        raise_on_turn=RuntimeError("rate limited"),
    )
    agent = AnthropicToolUseAgent(client)
    with pytest.raises(AdapterError):
        agent.run(_TENANT_A, "first")
    # The retry: clear the raise condition and post a different message.
    client.raise_on_turn = None
    result = agent.run(_TENANT_A, "second")
    assert result.output == "second reply"
    # Only the surviving turn's messages appear in the conversation; the
    # failed "first" message was rolled back so it does not appear.
    second_turn = client.turns[-1]
    contents = [m["content"] for m in second_turn.messages]
    assert contents == [f"[tenant:{_TENANT_A.hex}] second"]


def test_anthropic_tooluse_does_not_append_assistant_history_when_final_text_is_empty() -> None:
    # An empty final text (the script default) must not be stored in
    # the conversation history; otherwise the next turn would carry a
    # spurious empty assistant message that some SDK versions reject.
    client = _FakeAnthropicClient(script={"first": ("", ())})
    agent = AnthropicToolUseAgent(client)
    agent.run(_TENANT_A, "first")
    agent.run(_TENANT_A, "second")
    second_turn = client.turns[1]
    roles = [m["role"] for m in second_turn.messages]
    # Only the two user messages, no assistant entry in between.
    assert roles == ["user", "user"]
