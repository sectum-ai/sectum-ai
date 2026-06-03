"""Mock-backed contract tests for the live AutoGen agent adapter.

AutoGen drives an agent as a turn-by-turn conversation between an
``AssistantAgent`` and a ``UserProxyAgent``; ``UserProxyAgent.initiate_chat``
runs one conversation and returns a ``ChatResult`` carrying every exchanged
message - including assistant messages with ``tool_calls`` describing each
tool invocation. The adapter's logic is verified here against an in-memory
stand-in for the two agents (the engineering spec, sections 11 and 13: live
SDK, mock-backed contract test plus opt-in live). The live path is exercised
by ``tests/integration/test_autogen.py``.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

from sectum_ai.adapters.agent.autogen import AutoGenAgent
from sectum_ai.adapters.base import AgentAdapter, Capability
from sectum_ai.spec import AdapterError

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@dataclass
class _Call:
    """One recorded ``initiate_chat`` call (the recipient and the user message)."""

    recipient: Any
    message: str
    extras: dict[str, Any]


@dataclass
class _ChatResult:
    """A minimal stand-in for an AutoGen ``ChatResult``."""

    chat_history: list[dict[str, Any]]


@dataclass
class _FakeAssistant:
    """A minimal stand-in for an AutoGen ``AssistantAgent``."""

    name: str = "sectum-assistant"


@dataclass
class _FakeUserProxy:
    """A user-proxy stand-in: records every initiate_chat call and replays a script.

    The ``script`` map keys on the user message (the substring after the
    ``[tenant:<hex>] `` prefix) and returns the matching conversation history,
    so a test can prove every ``run`` is invoked with the tenant-scoped prefix.
    The default fallback returns an empty conversation when no script entry
    matches.
    """

    script: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    calls: list[_Call] = field(default_factory=list)
    raise_on_initiate: Exception | None = None

    def initiate_chat(self, recipient: Any, **kwargs: Any) -> _ChatResult:
        if self.raise_on_initiate is not None:
            raise self.raise_on_initiate
        message = str(kwargs.pop("message"))
        self.calls.append(_Call(recipient=recipient, message=message, extras=dict(kwargs)))
        # The history is keyed by the user task (without the [tenant:...] prefix).
        suffix = message.split("] ", 1)[1] if "] " in message else message
        history = self.script.get(suffix, [])
        return _ChatResult(chat_history=list(history))


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def _assistant(text: str | list[Any], *tool_calls: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = list(tool_calls)
    return message


def _tool_call(name: str, **arguments: Any) -> dict[str, Any]:
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def test_autogen_conforms_to_the_family_and_reports_tool_invocation() -> None:
    agent = AutoGenAgent(_FakeAssistant(), _FakeUserProxy())
    assert isinstance(agent, AgentAdapter)
    assert agent.supports(Capability.TOOL_INVOCATION)


def test_autogen_scopes_each_run_by_tenant_prefix_in_the_user_message() -> None:
    # Each tenant's hex id is prefixed into the user-proxy message, so a tool
    # wired with tenant-aware routing can read the tenant scope from its
    # arguments; the substrate verifies this is what fires at Class 7.
    proxy = _FakeUserProxy(
        script={
            "hi A": [_user("hi A"), _assistant("hello tenant A")],
            "hi B": [_user("hi B"), _assistant("hello tenant B")],
        }
    )
    agent = AutoGenAgent(_FakeAssistant(), proxy)
    result_a = agent.run(_TENANT_A, "hi A")
    result_b = agent.run(_TENANT_B, "hi B")
    assert result_a.output == "hello tenant A"
    assert result_b.output == "hello tenant B"
    assert [call.message for call in proxy.calls] == [
        f"[tenant:{_TENANT_A.hex}] hi A",
        f"[tenant:{_TENANT_B.hex}] hi B",
    ]


def test_autogen_surfaces_every_tool_call_in_order() -> None:
    # Class 7 (agent tool-call hijack) verifies which tools fire on every run -
    # not just the final state - so the adapter must walk every assistant
    # message and surface each tool call in invocation order.
    proxy = _FakeUserProxy(
        script={
            "look it up": [
                _user("look it up"),
                _assistant("", _tool_call("search", q="alpha")),
                {"role": "tool", "content": "results: ..."},
                _assistant("done", _tool_call("summarize", text="...")),
            ]
        }
    )
    result = AutoGenAgent(_FakeAssistant(), proxy).run(_TENANT_A, "look it up")
    assert result.output == "done"
    assert result.tool_calls == ("search", "summarize")


def test_autogen_surfaces_multiple_tool_calls_in_one_assistant_message() -> None:
    # OpenAI tool-calling allows a single assistant message to carry several
    # tool_calls (a parallel-tool-call turn); the adapter must surface each
    # name in the array's order so the probe sees all of them.
    proxy = _FakeUserProxy(
        script={
            "fan out": [
                _user("fan out"),
                _assistant(
                    "",
                    _tool_call("search", q="alpha"),
                    _tool_call("search", q="beta"),
                    _tool_call("lookup", id="x"),
                ),
                _assistant("done"),
            ]
        }
    )
    result = AutoGenAgent(_FakeAssistant(), proxy).run(_TENANT_A, "fan out")
    assert result.tool_calls == ("search", "search", "lookup")


def test_autogen_surfaces_a_legacy_function_call_field() -> None:
    # The legacy AutoGen v0.2 line emits a single function_call rather than
    # the tool_calls array; the adapter reads both shapes so a stand-in or a
    # legacy live conversation surfaces the call.
    proxy = _FakeUserProxy(
        script={
            "legacy": [
                _user("legacy"),
                {
                    "role": "assistant",
                    "content": "calling",
                    "function_call": {"name": "echo", "arguments": "{}"},
                },
                {"role": "function", "content": "ok"},
                _assistant("done"),
            ]
        }
    )
    result = AutoGenAgent(_FakeAssistant(), proxy).run(_TENANT_A, "legacy")
    assert result.tool_calls == ("echo",)


def test_autogen_defaults_tool_calls_to_empty_and_ignores_nameless_calls() -> None:
    # A run with no tool use returns an empty tuple; a malformed tool-call
    # entry without a usable name is skipped (the adapter never invents one).
    proxy = _FakeUserProxy(
        script={
            "anything": [
                _user("anything"),
                _assistant("just a reply"),
                {
                    "role": "assistant",
                    "content": "with nameless call",
                    "tool_calls": [{"id": "1", "type": "function", "function": {}}],
                },
            ]
        }
    )
    result = AutoGenAgent(_FakeAssistant(), proxy).run(_TENANT_A, "anything")
    assert result.tool_calls == ()


def test_autogen_returns_the_final_assistant_text() -> None:
    # The adapter returns the last assistant message's content, not the first
    # (an AutoGen conversation may turn several times before terminating).
    proxy = _FakeUserProxy(
        script={
            "ask": [
                _user("ask"),
                _assistant("first reply"),
                _assistant("middle reply"),
                _assistant("final reply"),
            ]
        }
    )
    result = AutoGenAgent(_FakeAssistant(), proxy).run(_TENANT_A, "ask")
    assert result.output == "final reply"


def test_autogen_handles_list_block_content_on_the_final_message() -> None:
    # v0.4+ multimodal messages may carry ``content`` as a list of content blocks;
    # the adapter flattens them to a plain string for the AgentResult.
    proxy = _FakeUserProxy(
        script={
            "anything": [
                _user("anything"),
                _assistant(
                    [
                        {"type": "text", "text": "part one "},
                        {"type": "text", "text": "part two"},
                    ]
                ),
            ]
        }
    )
    result = AutoGenAgent(_FakeAssistant(), proxy).run(_TENANT_A, "anything")
    assert result.output == "part one part two"


def test_autogen_returns_empty_output_when_no_assistant_message_exists() -> None:
    # An empty or user-only history produces an empty output rather than crashing.
    proxy = _FakeUserProxy(script={"hi": [_user("hi")]})
    result = AutoGenAgent(_FakeAssistant(), proxy).run(_TENANT_A, "hi")
    assert result.output == ""
    assert result.tool_calls == ()


def test_autogen_raises_adapter_error_when_initiate_chat_fails() -> None:
    # Any exception from the underlying conversation is wrapped in AdapterError
    # so the caller sees a consistent failure mode across every live agent adapter.
    proxy = _FakeUserProxy(raise_on_initiate=RuntimeError("rate limited"))
    with pytest.raises(AdapterError, match="autogen initiate_chat failed"):
        AutoGenAgent(_FakeAssistant(), proxy).run(_TENANT_A, "anything")


def test_autogen_rejects_a_non_list_chat_history() -> None:
    class _BrokenProxy:
        def initiate_chat(self, recipient: Any, **kwargs: Any) -> _ChatResult:
            return _ChatResult(chat_history="not a list")  # type: ignore[arg-type]

    with pytest.raises(AdapterError, match=r"chat history.*list"):
        AutoGenAgent(_FakeAssistant(), _BrokenProxy()).run(_TENANT_A, "anything")


def test_autogen_reads_a_v04_chat_messages_dict_keyed_on_the_assistant() -> None:
    # The v0.4+ shape exposes ``chat_messages`` keyed by participating agent
    # rather than a flat ``chat_history``; the adapter reads either shape.
    class _V04ChatResult:
        def __init__(self, messages: dict[str, list[dict[str, Any]]]) -> None:
            self.chat_messages = messages

    class _V04Proxy:
        def initiate_chat(self, recipient: Any, **kwargs: Any) -> _V04ChatResult:
            return _V04ChatResult(
                {
                    recipient.name: [
                        _user("ping"),
                        _assistant("pong"),
                    ]
                }
            )

    result = AutoGenAgent(_FakeAssistant(), _V04Proxy()).run(_TENANT_A, "ping")
    assert result.output == "pong"


def test_autogen_rejects_a_chat_result_without_a_recognized_shape() -> None:
    class _BareProxy:
        def initiate_chat(self, recipient: Any, **kwargs: Any) -> str:
            return "an opaque value"

    with pytest.raises(AdapterError, match="chat result must expose"):
        AutoGenAgent(_FakeAssistant(), _BareProxy()).run(_TENANT_A, "anything")


def test_autogen_forwards_a_max_turns_kwarg_when_configured() -> None:
    # When the adapter is constructed with ``max_turns``, every initiate_chat
    # call forwards the value so the live conversation terminates after that
    # many turns (defensive cap on agent loops).
    proxy = _FakeUserProxy(script={"go": [_assistant("ok")]})
    AutoGenAgent(_FakeAssistant(), proxy, max_turns=3).run(_TENANT_A, "go")
    assert proxy.calls[0].extras == {"max_turns": 3}
