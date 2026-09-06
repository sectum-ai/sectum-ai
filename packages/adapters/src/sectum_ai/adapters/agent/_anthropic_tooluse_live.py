"""Live Anthropic Messages-API client backing the tool-use adapter.

Imported lazily by ``AnthropicToolUseAgent.connect``. The module imports
``anthropic`` at module load, so a downstream import of
``sectum_ai.adapters.agent.anthropic_tooluse`` does NOT pull the SDK —
only construction via ``connect`` does.

Implements the ``_AnthropicClient`` protocol the adapter consumes:

- ``run_turn`` — calls ``messages.create`` on the supplied conversation
  history; for each ``tool_use`` block in the response, executes the
  registered python callable, appends a ``tool_result`` user message,
  and repeats until ``stop_reason: end_turn``. Returns the final
  assistant text + the list of tool names that fired across the loop.

Tool execution: pass the python callable ITSELF as the tool, with its
schema attached as a ``__sectum_tool_spec__`` attribute. Both sidecars
are read off the tool object with ``getattr``, so a callable stored as a
KEY inside the spec dict is invisible to them (and makes the spec
unserializable for the API call). A tool whose target is not callable is
refused rather than skipped: a dropped tool answers every invocation with
an empty string, which grades the agent surface clean over a tool that
was never wired. The backend looks the callable up by the tool's ``name`` field.
"""

from __future__ import annotations

import json
from typing import Any

from sectum_ai.spec import AdapterError

_MAX_TOOL_USE_ITERATIONS = 16


class LiveAnthropicClient:
    """Live ``_AnthropicClient`` implementation backed by the Anthropic Python SDK.

    Holds a single ``anthropic.Anthropic`` client plus a registry of
    the python callables that back each registered tool by name.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        tools: list[Any],
        max_tokens: int,
        system: str,
    ) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as error:
            raise AdapterError(
                "anthropic-tooluse adapter requires the `anthropic` package; "
                "install sectum-ai-adapters[anthropic-tooluse] to enable it"
            ) from error
        self._anthropic = Anthropic(api_key=api_key) if api_key else Anthropic()
        self._model = model
        self._max_tokens = max_tokens
        self._system = system
        # The Anthropic tool spec is a dict carrying name / description /
        # input_schema. Strip the python-callable sidecar before passing
        # it to the SDK (the SDK rejects unknown keys on tool specs).
        self._tools: list[dict[str, Any]] = []
        self._tool_targets: dict[str, Any] = {}
        for tool in tools:
            spec = getattr(tool, "__sectum_tool_spec__", None) or tool
            if not isinstance(spec, dict) or "name" not in spec:
                raise AdapterError(
                    "each tool must be (or carry) an Anthropic tool-spec dict "
                    "with at least a `name` field; got "
                    f"{type(spec).__name__}"
                )
            self._tools.append(spec)
            name = spec.get("name")
            callable_target = getattr(tool, "__sectum_callable__", tool)
            if not callable(callable_target):
                raise AdapterError(
                    f"tool {name!r} has no python callable to execute: pass the callable "
                    "itself as the tool (carrying its schema as a `__sectum_tool_spec__` "
                    "attribute), not a spec dict with the callable under a key - `getattr` "
                    "cannot see a dict key, and a tool that is silently dropped answers "
                    "every invocation with an empty string"
                )
            if isinstance(name, str) and name:
                self._tool_targets[name] = callable_target

    def run_turn(self, messages: list[dict[str, Any]]) -> tuple[str, tuple[str, ...]]:
        """Drive the tool-use loop to completion; return (final_text, tool_names)."""
        tool_names: list[str] = []
        loop_messages = list(messages)
        for _ in range(_MAX_TOOL_USE_ITERATIONS):
            response = self._anthropic.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system,
                tools=self._tools,
                messages=loop_messages,
            )
            content_blocks = getattr(response, "content", []) or []
            tool_uses = [
                block for block in content_blocks if getattr(block, "type", None) == "tool_use"
            ]
            if not tool_uses:
                # No more tool calls; collect the final assistant text and stop.
                final_text = _collect_text(content_blocks)
                return final_text, tuple(tool_names)

            # Append the assistant's tool_use turn to the loop history so the
            # next messages.create call has the context.
            loop_messages.append(
                {
                    "role": "assistant",
                    "content": [_block_to_dict(block) for block in content_blocks],
                }
            )

            # Execute each tool_use block and build the matching
            # tool_result user message.
            tool_results: list[dict[str, Any]] = []
            for block in tool_uses:
                name = getattr(block, "name", None)
                if not isinstance(name, str) or not name:
                    continue
                tool_names.append(name)
                tool_use_id = getattr(block, "id", "")
                arguments = getattr(block, "input", None)
                if not isinstance(arguments, dict):
                    arguments = {}
                target = self._tool_targets.get(name)
                if target is None:
                    result = ""
                else:
                    try:
                        result = target(**arguments)
                    except Exception as error:
                        result = f"tool {name} raised {type(error).__name__}: {error}"
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": str(result),
                    }
                )
            loop_messages.append({"role": "user", "content": tool_results})

        raise AdapterError(
            f"anthropic tool-use loop exceeded {_MAX_TOOL_USE_ITERATIONS} iterations"
        )


def _collect_text(content_blocks: list[Any]) -> str:
    """Concatenate every ``text`` block's text into a single string."""
    parts: list[str] = []
    for block in content_blocks:
        if getattr(block, "type", None) != "text":
            continue
        text = getattr(block, "text", "")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _block_to_dict(block: Any) -> dict[str, Any]:
    """Convert an SDK content-block object back to its dict form.

    Anthropic's SDK returns typed block objects on responses but expects
    dict-shaped blocks when echoing them back as assistant history; the
    serialisation has to round-trip without losing the type tag.
    """
    block_type = getattr(block, "type", None)
    if block_type == "text":
        return {"type": "text", "text": getattr(block, "text", "")}
    if block_type == "tool_use":
        input_value = getattr(block, "input", None)
        if isinstance(input_value, str):
            try:
                input_value = json.loads(input_value)
            except json.JSONDecodeError:
                input_value = {}
        if not isinstance(input_value, dict):
            input_value = {}
        return {
            "type": "tool_use",
            "id": getattr(block, "id", ""),
            "name": getattr(block, "name", ""),
            "input": input_value,
        }
    # Unknown block type; fall back to a string projection so the loop
    # does not crash on a future SDK addition.
    return {"type": block_type or "unknown", "text": str(block)}
