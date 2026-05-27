"""Live LangGraph agent adapter: an agent backed by a compiled LangGraph graph.

LangGraph drives an agent as a ``StateGraph`` compiled to a runnable; each
invocation is scoped by a ``thread_id`` carried in the runtime config
(``{"configurable": {"thread_id": ...}}``). This adapter maps each tenant to its
own thread by setting ``thread_id`` to the tenant's hex id, so a per-thread
checkpoint or memory cannot bleed across tenants - the tenant-isolation
mechanism the substrate verifies (the engineering spec, section 7, Class 7).

``run`` invokes the compiled graph with a ``HumanMessage(task)`` input and the
tenant-scoped config, then extracts the final assistant text plus the **names
of every tool the graph called during the run** by walking the messages in the
returned state. Tool-call records are surfaced on every run - not just the
final state - so the Class 7 (agent tool-call hijack) probes can see which
tools fired (the engineering spec, section 7).

The ``langgraph`` package is imported only on the live ``connect`` path, so the
adapter and its mock-backed contract test need no extra dependency. The live
path requires the ``langgraph`` optional dependency:
``pip install sectum-ai-adapters[langgraph]``.
"""

from collections.abc import Iterable
from typing import Any, Self
from uuid import UUID

from sectum.adapters.base import AgentAdapter, AgentResult, Capability
from sectum.spec import AdapterError


class LangGraphAgent(AgentAdapter):
    """An agent backed by a compiled LangGraph graph.

    Construct it with an open compiled graph object (anything implementing
    ``invoke(input, config) -> mapping``) so the adapter can be tested against
    an in-memory stand-in without the ``langgraph`` package. Use :meth:`connect`
    to build the prebuilt ReAct agent (``langgraph.prebuilt.create_react_agent``)
    from a model and tools.

    Scopes by tenant: every ``run`` passes ``configurable.thread_id`` equal to
    the tenant's hex id (matching the substrate's per-tenant scoping convention).
    A graph wired to a per-thread checkpointer therefore keeps each tenant's
    state in its own checkpoint namespace.
    """

    def __init__(
        self,
        graph: Any,
        *,
        name: str = "langgraph",
        recursion_limit: int = 25,
    ) -> None:
        super().__init__(name, frozenset({Capability.TOOL_INVOCATION}))
        self._graph = graph
        self._recursion_limit = recursion_limit

    @classmethod
    def connect(
        cls,
        model: Any,
        tools: Iterable[Any],
        *,
        name: str = "langgraph",
        recursion_limit: int = 25,
    ) -> Self:
        """Build a prebuilt LangGraph ReAct agent and return the adapter.

        The ``langgraph`` package is imported here, on the live path only, so
        the adapter module and its mock-backed test do not require it.
        """
        from langgraph.prebuilt import create_react_agent

        graph = create_react_agent(model, list(tools))
        return cls(graph, name=name, recursion_limit=recursion_limit)

    def run(self, tenant: UUID, task: str) -> AgentResult:
        config = {
            "configurable": {"thread_id": tenant.hex},
            "recursion_limit": self._recursion_limit,
        }
        # Import lazily so the adapter module type-checks and unit-tests without
        # the live package; the mock-backed test passes a plain mapping input.
        try:
            from langchain_core.messages import HumanMessage

            input_payload: dict[str, Any] = {"messages": [HumanMessage(content=task)]}
        except ImportError:  # pragma: no cover - exercised only when langgraph is absent
            # Fallback for stand-ins that accept a plain ``role``/``content`` dict.
            input_payload = {"messages": [{"role": "user", "content": task}]}

        try:
            state = self._graph.invoke(input_payload, config=config)
        except Exception as error:
            raise AdapterError(f"langgraph invoke failed: {error}") from error

        if not isinstance(state, dict):
            raise AdapterError(f"langgraph state must be a mapping, got {type(state).__name__}")
        messages = state.get("messages", [])
        if not isinstance(messages, list):
            raise AdapterError(
                f"langgraph state['messages'] must be a list, got {type(messages).__name__}"
            )
        return AgentResult(output=_final_text(messages), tool_calls=_tool_calls(messages))


def _content_to_text(content: Any) -> str:
    """Flatten a LangChain message ``content`` to a plain string.

    LangChain v0.3+ messages carry ``content`` as either a string or a list of
    content blocks (each typically ``{"type": "text", "text": str}``); read
    defensively so a stand-in that returns either shape parses without crashing.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content) if content is not None else ""


def _is_assistant(message: Any) -> bool:
    """Return whether ``message`` is an assistant / AI message.

    A LangChain ``AIMessage`` carries ``type == "ai"``; a plain mapping
    stand-in may instead carry ``role == "assistant"``. Read both so the
    adapter is portable across the message object and the dict-shaped stub
    used in the mock-backed test.
    """
    if hasattr(message, "type"):
        return getattr(message, "type", None) == "ai"
    if isinstance(message, dict):
        return message.get("role") == "assistant" or message.get("type") == "ai"
    return False


def _final_text(messages: list[Any]) -> str:
    """Return the text of the last assistant message, or empty string."""
    for message in reversed(messages):
        if not _is_assistant(message):
            continue
        if isinstance(message, dict):
            return _content_to_text(message.get("content", ""))
        return _content_to_text(getattr(message, "content", ""))
    return ""


def _tool_call_name(call: Any) -> str | None:
    """Extract a tool-call name from one ``AIMessage.tool_calls`` entry."""
    if isinstance(call, dict):
        name = call.get("name")
        if isinstance(name, str) and name:
            return name
        return None
    name = getattr(call, "name", None)
    if isinstance(name, str) and name:
        return name
    return None


def _tool_calls(messages: list[Any]) -> tuple[str, ...]:
    """Walk every message and surface each tool call's name in order."""
    names: list[str] = []
    for message in messages:
        if isinstance(message, dict):
            raw = message.get("tool_calls", ())
        else:
            raw = getattr(message, "tool_calls", ()) or ()
        for call in raw:
            name = _tool_call_name(call)
            if name is not None:
                names.append(name)
    return tuple(names)
