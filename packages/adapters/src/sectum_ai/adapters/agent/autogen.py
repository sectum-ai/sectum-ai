"""Live AutoGen agent adapter: an agent backed by an AutoGen ``AssistantAgent``.

Microsoft AutoGen drives an agent as a turn-by-turn conversation between a
``ConversableAgent`` (typically an ``AssistantAgent`` with tools and an LLM
config) and a ``UserProxyAgent`` that issues the user message and executes the
assistant's tool calls. ``UserProxyAgent.initiate_chat(assistant, message=...)``
runs one conversation to termination and returns a ``ChatResult`` whose
``chat_history`` carries every message exchanged - including assistant messages
with ``tool_calls`` describing each tool invocation.

This adapter scopes per tenant by prefixing the user-proxy message with a
``[tenant:<hex>]`` token so a tool with tenant-aware routing can read the
tenant id from the call arguments the assistant forwards. The substrate verifies
agent-level isolation (the engineering spec, section 7, Class 7): a tool call
in tenant Y's session that resolves a resource in tenant X's scope is a
confused-deputy leak, and the cross-tenant agent tool-call hijack probes need
to see *which* tool was invoked in each tenant's session - which is what
``run()`` surfaces in ``AgentResult.tool_calls``.

The ``autogen-agentchat`` / ``autogen-core`` package is imported only on the
live ``connect`` path, so the adapter and its mock-backed contract test need no
extra dependency. The live path requires the ``autogen`` optional dependency:
``pip install sectum-ai-adapters[autogen]``.
"""

from collections.abc import Iterable
from typing import Any, Self
from uuid import UUID

from sectum_ai.adapters.base import AgentAdapter, AgentResult, Capability
from sectum_ai.spec import AdapterError


class AutoGenAgent(AgentAdapter):
    """An agent backed by an AutoGen ``AssistantAgent`` + ``UserProxyAgent`` pair.

    Construct it with two open AutoGen agent objects: an assistant (anything
    with a ``name`` attribute that participates in a conversation) and a
    user proxy (anything implementing
    ``initiate_chat(recipient, message=...) -> chat_result``) so the adapter
    can be tested against in-memory stand-ins without the ``autogen`` package.
    Use :meth:`connect` to build the assistant and user proxy from a model
    config and a list of tools.

    Scopes by tenant: every ``run`` prefixes the user message with
    ``[tenant:<tenant.hex>]`` so a tool wired with tenant-aware routing can
    read the tenant identity from the call arguments. The conversation result's
    ``chat_history`` is walked to surface every tool call the assistant made
    during the run - not just the final state - so the Class 7 probes can see
    which tool fired in each tenant's session.
    """

    def __init__(
        self,
        assistant: Any,
        user_proxy: Any,
        *,
        name: str = "autogen",
        max_turns: int | None = None,
    ) -> None:
        super().__init__(name, frozenset({Capability.TOOL_INVOCATION}))
        self._assistant = assistant
        self._user_proxy = user_proxy
        self._max_turns = max_turns

    @classmethod
    def connect(
        cls,
        model: Any,
        tools: Iterable[Any],
        *,
        name: str = "autogen",
        assistant_name: str = "sectum-assistant",
        user_proxy_name: str = "sectum-user-proxy",
        system_message: str | None = None,
        max_turns: int | None = None,
    ) -> Self:
        """Build an AutoGen ``AssistantAgent`` + ``UserProxyAgent`` pair and return the adapter.

        The ``autogen`` package is imported here, on the live path only, so the
        adapter module and its mock-backed test do not require it. ``model``
        is forwarded into the assistant's ``llm_config`` so the caller controls
        the model provider, key resolution, and any provider-specific knobs.

        The default ``system_message`` instructs the assistant to forward the
        per-tenant prefix token into any tool call it makes - the wiring the
        Class 7 probe relies on to detect cross-tenant tool-call hijack.
        """
        from autogen import AssistantAgent, UserProxyAgent

        if system_message is None:
            system_message = (
                "You are a helpful assistant. Each user message begins with a "
                "[tenant:<hex>] token identifying the tenant context. When you "
                "invoke a tool, forward the tenant token verbatim in a "
                "'tenant' argument so the tool can scope its lookup."
            )
        llm_config = model if isinstance(model, dict) else {"model": model}
        assistant = AssistantAgent(
            name=assistant_name,
            llm_config=llm_config,
            system_message=system_message,
        )
        for tool in tools:
            assistant.register_for_llm()(tool)
        user_proxy = UserProxyAgent(
            name=user_proxy_name,
            human_input_mode="NEVER",
            code_execution_config=False,
        )
        for tool in tools:
            user_proxy.register_for_execution()(tool)
        return cls(assistant, user_proxy, name=name, max_turns=max_turns)

    def run(self, tenant: UUID, task: str) -> AgentResult:
        """Drive one AutoGen conversation as ``tenant`` and return the result.

        The task is prefixed with ``[tenant:<tenant.hex>]`` so a tool aware of
        the convention reads the tenant scope from its arguments. Any exception
        from the underlying conversation is wrapped in ``AdapterError`` so the
        caller sees a consistent failure mode across every live agent adapter.
        """
        message = f"[tenant:{tenant.hex}] {task}"
        kwargs: dict[str, Any] = {"message": message}
        if self._max_turns is not None:
            kwargs["max_turns"] = self._max_turns
        try:
            chat_result = self._user_proxy.initiate_chat(self._assistant, **kwargs)
        except Exception as error:
            raise AdapterError(f"autogen initiate_chat failed: {error}") from error

        history = _chat_history(chat_result, self._assistant)
        if not isinstance(history, list):
            raise AdapterError(f"autogen chat history must be a list, got {type(history).__name__}")
        return AgentResult(output=_final_text(history), tool_calls=_tool_calls(history))


def _chat_history(chat_result: Any, assistant: Any) -> Any:
    """Return the conversation message list from an AutoGen ``ChatResult``.

    The v0.2 legacy ``ConversableAgent.initiate_chat`` returns a ``ChatResult``
    with ``chat_history`` (a list of ``{"content": ..., "role": ..., ...}``
    dicts). Some flavours of the v0.4+ stack instead carry a
    ``chat_messages`` dict keyed on the participating agents; read both so the
    adapter is portable across the API surfaces and the dict-shaped stub used
    in the mock-backed test.
    """
    if hasattr(chat_result, "chat_history"):
        return chat_result.chat_history
    if hasattr(chat_result, "chat_messages"):
        messages = chat_result.chat_messages
        if isinstance(messages, dict):
            assistant_name = getattr(assistant, "name", None)
            if assistant_name is not None and assistant_name in messages:
                return messages[assistant_name]
            # Fall back to the first agent's transcript when the assistant
            # name does not appear as a key (some stand-ins key on the proxy).
            for value in messages.values():
                if isinstance(value, list):
                    return value
        return messages
    if isinstance(chat_result, list):
        return chat_result
    if isinstance(chat_result, dict) and "chat_history" in chat_result:
        return chat_result["chat_history"]
    shape = type(chat_result).__name__
    raise AdapterError(
        f"autogen chat result must expose chat_history or chat_messages, got {shape}"
    )


def _content_to_text(content: Any) -> str:
    """Flatten an AutoGen message ``content`` to a plain string.

    A standard AutoGen message carries ``content`` as a string; the v0.4+
    multimodal path may instead carry a list of content blocks
    (each typically ``{"type": "text", "text": str}``). Read both defensively
    so a stand-in that returns either shape parses without crashing.
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
    """Return whether ``message`` is an assistant message.

    An AutoGen assistant message carries ``role == "assistant"``; a v0.4+
    object form may instead expose a ``role`` attribute. Read both so the
    adapter is portable across the object and dict shapes.
    """
    if isinstance(message, dict):
        return message.get("role") == "assistant"
    return getattr(message, "role", None) == "assistant"


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
    """Extract a tool-call name from one AutoGen ``tool_calls`` entry.

    A standard tool call carries ``{"function": {"name": ..., "arguments": ...}}``
    (OpenAI tool-calling shape) but a v0.4+ flattened or stand-in form may
    instead carry ``{"name": ...}`` directly. Read both.
    """
    if isinstance(call, dict):
        function = call.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str) and name:
                return name
        name = call.get("name")
        if isinstance(name, str) and name:
            return name
        return None
    function = getattr(call, "function", None)
    if function is not None:
        name = getattr(function, "name", None)
        if isinstance(name, str) and name:
            return name
    name = getattr(call, "name", None)
    if isinstance(name, str) and name:
        return name
    return None


def _function_call_name(message: Any) -> str | None:
    """Extract a legacy ``function_call`` name from one AutoGen message.

    The v0.2 line emits a single ``function_call: {"name": ..., "arguments": ...}``
    on a message that triggered one function. Read it so a stand-in or a
    legacy live conversation surfaces the call alongside the modern
    ``tool_calls`` array.
    """
    if isinstance(message, dict):
        call = message.get("function_call")
    else:
        call = getattr(message, "function_call", None)
    if call is None:
        return None
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
    """Walk every message and surface each tool call's name in order.

    Surfaces both modern ``tool_calls`` entries (OpenAI tool-calling shape, one
    message may carry several) and the legacy single ``function_call`` entry,
    so a Class 7 probe sees every tool that fired regardless of the AutoGen
    version on the live path.
    """
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
        legacy = _function_call_name(message)
        if legacy is not None:
            names.append(legacy)
    return tuple(names)
