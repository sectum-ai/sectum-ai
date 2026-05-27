"""Mock-backed contract tests for the live LangGraph agent adapter.

LangGraph drives an agent as a compiled ``StateGraph`` whose ``invoke`` takes
a state input and a runtime config (carrying ``configurable.thread_id``); a
local checkpointer is the only way to wire per-thread state without a hosted
backend. The adapter's logic is verified here against an in-memory stand-in
for a compiled graph (the engineering spec, sections 11 and 13: live SDK,
mock-backed contract test plus opt-in live). The live path is exercised by
``tests/integration/test_langgraph_agent.py``.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

from sectum.adapters.agent.langgraph import LangGraphAgent
from sectum.adapters.base import AgentAdapter, Capability
from sectum.spec import AdapterError

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@dataclass
class _Call:
    """One recorded ``invoke`` call (the input payload and runtime config)."""

    input: dict[str, Any]
    config: dict[str, Any]


@dataclass
class _StubMessage:
    """A minimal stand-in for a LangChain ``AIMessage``/``HumanMessage``."""

    type: str
    content: str | list[Any]
    tool_calls: tuple[dict[str, Any], ...] = ()


@dataclass
class _StubGraph:
    """A compiled-graph stand-in that records calls and returns a scripted state.

    The ``thread_state`` map keys on each ``configurable.thread_id`` and
    returns the matching final state, so a test can prove every ``run`` is
    invoked with the tenant-scoped thread id - the isolation mechanism the
    adapter is meant to provide.
    """

    thread_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[_Call] = field(default_factory=list)
    raise_on_invoke: Exception | None = None

    def invoke(self, input: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.raise_on_invoke is not None:
            raise self.raise_on_invoke
        config = config or {}
        self.calls.append(_Call(input=input, config=config))
        thread_id = str(config.get("configurable", {}).get("thread_id", ""))
        return self.thread_state.get(thread_id, {"messages": []})


def _ai(text: str | list[Any], *tool_calls: dict[str, Any]) -> _StubMessage:
    return _StubMessage(type="ai", content=text, tool_calls=tool_calls)


def _human(text: str) -> _StubMessage:
    return _StubMessage(type="human", content=text)


def test_langgraph_conforms_to_the_family_and_reports_tool_invocation() -> None:
    agent = LangGraphAgent(_StubGraph())
    assert isinstance(agent, AgentAdapter)
    assert agent.supports(Capability.TOOL_INVOCATION)


def test_langgraph_scopes_each_run_by_tenant_thread_id() -> None:
    # Each tenant's hex id becomes its thread_id, so a graph wired with a
    # per-thread checkpointer keeps the state in that tenant's namespace.
    graph = _StubGraph(
        thread_state={
            _TENANT_A.hex: {"messages": [_human("hi A"), _ai("hello tenant A")]},
            _TENANT_B.hex: {"messages": [_human("hi B"), _ai("hello tenant B")]},
        }
    )
    agent = LangGraphAgent(graph)
    result_a = agent.run(_TENANT_A, "hi A")
    result_b = agent.run(_TENANT_B, "hi B")
    assert result_a.output == "hello tenant A"
    assert result_b.output == "hello tenant B"
    assert [call.config["configurable"]["thread_id"] for call in graph.calls] == [
        _TENANT_A.hex,
        _TENANT_B.hex,
    ]


def test_langgraph_surfaces_every_tool_call_in_order() -> None:
    # Class 7 (agent tool-call hijack) verifies which tools fire on every run -
    # not just the final state - so the adapter must walk every AI message.
    graph = _StubGraph(
        thread_state={
            _TENANT_A.hex: {
                "messages": [
                    _human("look it up"),
                    _ai("", {"name": "search", "args": {"q": "alpha"}, "id": "1"}),
                    _StubMessage(type="tool", content="results: ..."),
                    _ai(
                        "done",
                        {"name": "summarize", "args": {"text": "..."}, "id": "2"},
                    ),
                ]
            }
        }
    )
    result = LangGraphAgent(graph).run(_TENANT_A, "look it up")
    assert result.output == "done"
    assert result.tool_calls == ("search", "summarize")


def test_langgraph_defaults_tool_calls_to_empty_and_ignores_anonymous_calls() -> None:
    # A run with no tool use returns an empty tuple; a malformed tool-call
    # entry without a usable name is skipped (the adapter never invents one).
    graph = _StubGraph(
        thread_state={
            _TENANT_A.hex: {
                "messages": [
                    _ai("just a reply"),
                    _ai("with nameless call", {"args": {}, "id": "x"}),
                ]
            }
        }
    )
    result = LangGraphAgent(graph).run(_TENANT_A, "anything")
    assert result.tool_calls == ()


def test_langgraph_passes_the_task_as_a_user_message() -> None:
    # The graph receives the task in a ``messages`` list (a HumanMessage when
    # langchain-core is installed; otherwise a plain role/content dict).
    graph = _StubGraph(thread_state={_TENANT_A.hex: {"messages": [_ai("ack")]}})
    LangGraphAgent(graph).run(_TENANT_A, "summarize the backlog")
    call = graph.calls[0]
    assert "messages" in call.input
    messages = call.input["messages"]
    assert len(messages) == 1
    sent = messages[0]
    # langchain-core may or may not be installed; either way the content arrives.
    content = sent.content if hasattr(sent, "content") else sent["content"]
    assert content == "summarize the backlog"


def test_langgraph_handles_list_block_content_on_the_final_message() -> None:
    # LangChain v0.3+ messages may carry ``content`` as a list of content blocks;
    # the adapter flattens them to a plain string for the AgentResult.
    graph = _StubGraph(
        thread_state={
            _TENANT_A.hex: {
                "messages": [
                    _ai(
                        [
                            {"type": "text", "text": "part one "},
                            {"type": "text", "text": "part two"},
                        ]
                    )
                ]
            }
        }
    )
    result = LangGraphAgent(graph).run(_TENANT_A, "anything")
    assert result.output == "part one part two"


def test_langgraph_returns_empty_output_when_no_assistant_message_exists() -> None:
    # An empty or human-only state produces an empty output rather than crashing.
    graph = _StubGraph(thread_state={_TENANT_A.hex: {"messages": [_human("hi")]}})
    result = LangGraphAgent(graph).run(_TENANT_A, "hi")
    assert result.output == ""
    assert result.tool_calls == ()


def test_langgraph_raises_adapter_error_when_invoke_fails() -> None:
    # Any exception from the underlying graph is wrapped in AdapterError so the
    # caller sees a consistent failure mode across every live agent adapter.
    graph = _StubGraph(raise_on_invoke=RuntimeError("rate limited"))
    with pytest.raises(AdapterError, match="langgraph invoke failed"):
        LangGraphAgent(graph).run(_TENANT_A, "anything")


def test_langgraph_rejects_a_non_mapping_state() -> None:
    class _BrokenGraph:
        def invoke(self, input: Any, config: Any | None = None) -> Any:
            return "not a state"

    with pytest.raises(AdapterError, match="state must be a mapping"):
        LangGraphAgent(_BrokenGraph()).run(_TENANT_A, "anything")


def test_langgraph_rejects_a_non_list_messages_field() -> None:
    class _BrokenGraph:
        def invoke(self, input: Any, config: Any | None = None) -> dict[str, Any]:
            return {"messages": "not a list"}

    with pytest.raises(AdapterError, match=r"messages.*list"):
        LangGraphAgent(_BrokenGraph()).run(_TENANT_A, "anything")
