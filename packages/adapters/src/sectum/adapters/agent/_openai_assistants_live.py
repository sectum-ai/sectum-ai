"""Live OpenAI Assistants client implementation.

Imported lazily by ``OpenAIAssistantsAgent.connect``. The module imports
``openai`` at module load, so a downstream import of
``sectum.adapters.agent.openai_assistants`` does NOT pull the SDK —
only construction via ``connect`` does.

Implements the ``_AssistantsClient`` protocol the adapter consumes:

- ``create_assistant`` — creates the persistent Assistant (model +
  instructions + tools); returns its id
- ``create_thread`` — creates a fresh conversation Thread; returns its
  id (the adapter caches one per tenant)
- ``add_user_message`` — posts a user message into the Thread
- ``run_until_complete`` — starts a Run and drives it through the
  tool-call resolution loop until ``completed`` (or a terminal
  failure); returns ``(final_assistant_text, tool_call_names)``

Tool execution: the live backend resolves each ``requires_action``
event by reading the tool name + arguments off the run, calling the
caller-supplied Python callable mapped under the same name, and
posting the result back via ``submit_tool_outputs``. The caller
attaches a python callable to each tool spec via the
``__sectum_callable__`` attribute so the backend can find it.
"""

from __future__ import annotations

import json
import time
from typing import Any

from sectum.adapters.agent.openai_assistants import _poll_delay_ms
from sectum.spec import AdapterError


class LiveAssistantsClient:
    """Live ``_AssistantsClient`` implementation backed by the OpenAI Python SDK.

    Holds a single ``openai.OpenAI`` client and a registry of the
    Python callables that back each tool name on the configured
    Assistant.
    """

    def __init__(self, api_key: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise AdapterError(
                "openai-assistants adapter requires the `openai` package; "
                "install sectum-ai-adapters[openai-assistants] to enable it"
            ) from error
        self._openai = OpenAI(api_key=api_key) if api_key else OpenAI()
        self._tools: dict[str, Any] = {}

    def create_assistant(
        self,
        model: str,
        tools: list[Any],
        *,
        name: str,
        instructions: str,
    ) -> str:
        """Create a persistent Assistant + register the tool callables locally."""
        tool_specs: list[dict[str, Any]] = []
        for tool in tools:
            spec = getattr(tool, "__sectum_tool_spec__", None) or tool
            if not isinstance(spec, dict) or "function" not in spec:
                raise AdapterError(
                    "each tool must carry a `__sectum_tool_spec__` dict with the "
                    "OpenAI function-tool schema, or be a tool-spec dict itself"
                )
            tool_specs.append(spec)
            function_name = spec.get("function", {}).get("name")
            callable_target = getattr(tool, "__sectum_callable__", tool)
            if function_name and callable(callable_target):
                self._tools[function_name] = callable_target
        assistant = self._openai.beta.assistants.create(
            model=model,
            name=name,
            instructions=instructions,
            tools=tool_specs,
        )
        return str(assistant.id)

    def create_thread(self) -> str:
        thread = self._openai.beta.threads.create()
        return str(thread.id)

    def add_user_message(self, thread_id: str, content: str) -> None:
        self._openai.beta.threads.messages.create(thread_id=thread_id, role="user", content=content)

    def run_until_complete(self, thread_id: str, assistant_id: str) -> tuple[str, tuple[str, ...]]:
        run = self._openai.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)
        tool_names: list[str] = []
        attempt = 0
        while True:
            run = self._openai.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            status = getattr(run, "status", None)
            if status == "completed":
                break
            if status in ("failed", "cancelled", "expired"):
                raise AdapterError(
                    f"openai assistants run terminated in {status!r}: "
                    f"{getattr(run, 'last_error', None)}"
                )
            if status == "requires_action":
                outputs = []
                required = getattr(run, "required_action", None)
                tool_calls = (
                    getattr(getattr(required, "submit_tool_outputs", None), "tool_calls", [])
                    if required is not None
                    else []
                )
                for call in tool_calls:
                    function = getattr(call, "function", None)
                    if function is None:
                        continue
                    name = getattr(function, "name", None)
                    if not isinstance(name, str) or not name:
                        continue
                    tool_names.append(name)
                    args_raw = getattr(function, "arguments", "") or "{}"
                    try:
                        args = json.loads(args_raw)
                    except json.JSONDecodeError:
                        args = {}
                    target = self._tools.get(name)
                    if target is None:
                        result: Any = ""
                    else:
                        result = target(**args)
                    outputs.append({"tool_call_id": getattr(call, "id", ""), "output": str(result)})
                self._openai.beta.threads.runs.submit_tool_outputs(
                    thread_id=thread_id, run_id=run.id, tool_outputs=outputs
                )
            time.sleep(_poll_delay_ms(attempt) / 1000.0)
            attempt += 1

        messages = self._openai.beta.threads.messages.list(thread_id=thread_id, order="desc")
        for message in messages.data:
            if getattr(message, "role", None) != "assistant":
                continue
            content_blocks = getattr(message, "content", []) or []
            for block in content_blocks:
                text = getattr(getattr(block, "text", None), "value", None)
                if isinstance(text, str) and text:
                    return text, tuple(tool_names)
        return "", tuple(tool_names)
