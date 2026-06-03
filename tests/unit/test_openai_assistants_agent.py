"""Mock-backed contract tests for the live OpenAI Assistants agent adapter.

The OpenAI Assistants API drives a per-Thread conversation against a
persistent Assistant; the adapter caches one Thread per tenant and
reuses it on every ``run`` call (the isolation property Class 7
verifies). The adapter's logic is exercised here against an in-memory
``_FakeAssistantsClient`` stand-in (the engineering spec, sections 11
and 13: live SDK, mock-backed contract test plus opt-in live).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import pytest

from sectum_ai.adapters.agent.openai_assistants import OpenAIAssistantsAgent
from sectum_ai.adapters.base import AgentAdapter, Capability
from sectum_ai.spec import AdapterError

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@dataclass
class _PostedMessage:
    thread_id: str
    content: str


@dataclass
class _FakeAssistantsClient:
    """In-memory mirror of the live OpenAI Assistants Threads + Runs surface."""

    next_thread_id: int = 0
    threads: list[str] = field(default_factory=list)
    posted: list[_PostedMessage] = field(default_factory=list)
    # per-message script: maps the message content to (final_text, tool_calls)
    script: dict[str, tuple[str, tuple[str, ...]]] = field(default_factory=dict)
    raise_on_run: Exception | None = None

    def create_thread(self) -> str:
        thread_id = f"thread_{self.next_thread_id}"
        self.next_thread_id += 1
        self.threads.append(thread_id)
        return thread_id

    def add_user_message(self, thread_id: str, content: str) -> None:
        self.posted.append(_PostedMessage(thread_id=thread_id, content=content))

    def run_until_complete(self, thread_id: str, assistant_id: str) -> tuple[str, tuple[str, ...]]:
        if self.raise_on_run is not None:
            raise self.raise_on_run
        # The latest posted message governs the script lookup; strip the
        # [tenant:<hex>] prefix to keep the script keys readable.
        latest = self.posted[-1].content if self.posted else ""
        suffix = latest.split("] ", 1)[1] if "] " in latest else latest
        return self.script.get(suffix, ("", ()))


def test_openai_assistants_conforms_to_the_family_and_reports_tool_invocation() -> None:
    agent = OpenAIAssistantsAgent(_FakeAssistantsClient(), "asst_test")
    assert isinstance(agent, AgentAdapter)
    assert agent.supports(Capability.TOOL_INVOCATION)


def test_openai_assistants_scopes_each_tenant_to_its_own_thread() -> None:
    # The first run() for a tenant creates a new Thread; subsequent
    # runs for the same tenant reuse it. A second tenant gets its own
    # Thread, so a tool that scopes by thread_id cannot bleed across
    # tenants.
    client = _FakeAssistantsClient(
        script={
            "hi A1": ("hello A first", ()),
            "hi A2": ("hello A second", ()),
            "hi B1": ("hello B first", ()),
        }
    )
    agent = OpenAIAssistantsAgent(client, "asst_test")
    agent.run(_TENANT_A, "hi A1")
    agent.run(_TENANT_A, "hi A2")
    agent.run(_TENANT_B, "hi B1")
    # Two Threads exist: one for tenant A (reused on the second call),
    # one for tenant B.
    assert len(client.threads) == 2
    thread_a = client.threads[0]
    thread_b = client.threads[1]
    # The three posted messages land on the right Threads.
    assert [(p.thread_id, p.content) for p in client.posted] == [
        (thread_a, f"[tenant:{_TENANT_A.hex}] hi A1"),
        (thread_a, f"[tenant:{_TENANT_A.hex}] hi A2"),
        (thread_b, f"[tenant:{_TENANT_B.hex}] hi B1"),
    ]


def test_openai_assistants_prefixes_each_user_message_with_the_tenant_token() -> None:
    # The substrate verifies the per-tenant prefix token is what fires at
    # Class 7; this test pins that the token is unmodified.
    client = _FakeAssistantsClient(script={"hello": ("ok", ())})
    agent = OpenAIAssistantsAgent(client, "asst_test")
    agent.run(_TENANT_A, "hello")
    assert client.posted[0].content == f"[tenant:{_TENANT_A.hex}] hello"


def test_openai_assistants_returns_the_final_assistant_text_and_tool_names() -> None:
    client = _FakeAssistantsClient(
        script={
            "look it up": ("done", ("search", "summarize")),
        }
    )
    agent = OpenAIAssistantsAgent(client, "asst_test")
    result = agent.run(_TENANT_A, "look it up")
    assert result.output == "done"
    assert result.tool_calls == ("search", "summarize")


def test_openai_assistants_handles_a_no_tool_use_run() -> None:
    client = _FakeAssistantsClient(script={"just chat": ("hi there", ())})
    agent = OpenAIAssistantsAgent(client, "asst_test")
    result = agent.run(_TENANT_A, "just chat")
    assert result.output == "hi there"
    assert result.tool_calls == ()


def test_openai_assistants_returns_empty_output_when_script_misses() -> None:
    # A stand-in with no script for the message returns the default
    # empty string + empty tool-call tuple; the adapter passes those
    # through verbatim rather than synthesising a fallback.
    agent = OpenAIAssistantsAgent(_FakeAssistantsClient(), "asst_test")
    result = agent.run(_TENANT_A, "anything")
    assert result.output == ""
    assert result.tool_calls == ()


def test_openai_assistants_wraps_run_failures_in_adapter_error() -> None:
    client = _FakeAssistantsClient(raise_on_run=RuntimeError("rate limited"))
    agent = OpenAIAssistantsAgent(client, "asst_test")
    with pytest.raises(AdapterError, match="openai assistants run failed"):
        agent.run(_TENANT_A, "anything")


def test_openai_assistants_wraps_thread_creation_failures_in_adapter_error() -> None:
    # A backend that raises on Thread creation must still surface a
    # typed AdapterError so the CLI exits 3 consistently.
    class _BrokenClient:
        def create_thread(self) -> str:
            raise RuntimeError("thread quota exceeded")

        def add_user_message(self, thread_id: str, content: str) -> None:
            raise AssertionError("unreachable")

        def run_until_complete(
            self, thread_id: str, assistant_id: str
        ) -> tuple[str, tuple[str, ...]]:
            raise AssertionError("unreachable")

    agent = OpenAIAssistantsAgent(_BrokenClient(), "asst_test")
    with pytest.raises(AdapterError, match="openai assistants run failed"):
        agent.run(_TENANT_A, "anything")


def test_openai_assistants_wraps_add_message_failures_in_adapter_error() -> None:
    class _BrokenAddMessage:
        def __init__(self) -> None:
            self.thread = "thread_x"

        def create_thread(self) -> str:
            return self.thread

        def add_user_message(self, thread_id: str, content: str) -> None:
            raise ConnectionError("api timeout")

        def run_until_complete(
            self, thread_id: str, assistant_id: str
        ) -> tuple[str, tuple[str, ...]]:
            return "", ()

    agent = OpenAIAssistantsAgent(_BrokenAddMessage(), "asst_test")
    with pytest.raises(AdapterError, match="openai assistants run failed"):
        agent.run(_TENANT_A, "anything")
