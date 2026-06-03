"""Live CrewAI agent adapter: an agent backed by a CrewAI ``Crew``.

CrewAI runs a workflow as a ``Crew`` of ``Agent`` objects collaborating on a
list of ``Task`` objects. ``crew.kickoff(inputs={...})`` runs the crew to
termination with named input variables that templated task descriptions
interpolate; the return is a ``CrewOutput`` carrying the final raw string and
a per-task ``tasks_output`` list. Each ``TaskOutput`` exposes the tool calls
the agent made while completing that task.

This adapter scopes per tenant by passing ``tenant_id=tenant.hex`` and
``task=<task>`` in the kickoff inputs. Task descriptions templated with
``{tenant_id}`` and ``{task}`` interpolate the values, and tools wired with
tenant-aware routing read the id from their call arguments. The substrate
verifies agent-level isolation (the engineering spec, section 7, Class 7): a
tool call in tenant Y's session that resolves a resource in tenant X's scope
is a confused-deputy leak, and the cross-tenant agent tool-call hijack probes
need to see *which* tool was invoked in each tenant's session - which is what
``run()`` surfaces in ``AgentResult.tool_calls``.

The ``crewai`` package is imported only on the live ``connect`` path, so the
adapter and its mock-backed contract test need no extra dependency. The live
path requires the ``crewai`` optional dependency:
``pip install sectum-ai-adapters[crewai]``.
"""

from collections.abc import Iterable
from typing import Any, Self
from uuid import UUID

from sectum_ai.adapters.base import AgentAdapter, AgentResult, Capability
from sectum_ai.spec import AdapterError


class CrewAIAgent(AgentAdapter):
    """An agent backed by a CrewAI ``Crew``.

    Construct it with an open CrewAI ``Crew`` object (anything implementing
    ``kickoff(inputs: dict) -> output``) so the adapter can be tested against
    an in-memory stand-in without the ``crewai`` package. Use :meth:`connect`
    to build a ``Crew`` from a list of agents and tasks.

    Scopes by tenant: every ``run`` passes ``tenant_id=tenant.hex`` into the
    crew's kickoff inputs, alongside the ``task`` string. Task descriptions
    templated with ``{tenant_id}`` interpolate the value, and tools with
    tenant-aware routing read it from their call arguments. The crew's
    ``tasks_output`` is walked to surface every tool call the agents made
    during the run - not just the final state - so the Class 7 probes can
    see which tool fired in each tenant's session.
    """

    def __init__(
        self,
        crew: Any,
        *,
        name: str = "crewai",
        input_key: str = "task",
        tenant_key: str = "tenant_id",
    ) -> None:
        super().__init__(name, frozenset({Capability.TOOL_INVOCATION}))
        self._crew = crew
        self._input_key = input_key
        self._tenant_key = tenant_key

    @classmethod
    def connect(
        cls,
        agents: Iterable[Any],
        tasks: Iterable[Any],
        *,
        name: str = "crewai",
        input_key: str = "task",
        tenant_key: str = "tenant_id",
        **crew_kwargs: Any,
    ) -> Self:
        """Build a CrewAI ``Crew`` and return the adapter.

        The ``crewai`` package is imported here, on the live path only, so the
        adapter module and its mock-backed test do not require it. ``agents``
        and ``tasks`` are the CrewAI primitives the caller has already
        constructed; ``crew_kwargs`` forwards any additional ``Crew``
        constructor knobs (``process``, ``verbose``, ``manager_llm``, etc.).

        The task descriptions the caller supplies are expected to interpolate
        ``{tenant_id}`` and ``{task}`` where the tenant context and the input
        should appear - the Class 7 probe relies on the tenant token making
        it into tool-call arguments.
        """
        from crewai import Crew

        crew = Crew(agents=list(agents), tasks=list(tasks), **crew_kwargs)
        return cls(crew, name=name, input_key=input_key, tenant_key=tenant_key)

    def run(self, tenant: UUID, task: str) -> AgentResult:
        """Drive one CrewAI kickoff as ``tenant`` and return the result.

        The crew receives ``{tenant_id: tenant.hex, task: <task>}`` in its
        kickoff inputs so a templated task description can interpolate both,
        and tools aware of the convention read the tenant scope from their
        arguments. Any exception from the underlying kickoff is wrapped in
        ``AdapterError`` so the caller sees a consistent failure mode across
        every live agent adapter.
        """
        inputs = {self._tenant_key: tenant.hex, self._input_key: task}
        try:
            output = self._crew.kickoff(inputs=inputs)
        except Exception as error:
            raise AdapterError(f"crewai kickoff failed: {error}") from error

        tasks_output = _tasks_output(output)
        return AgentResult(
            output=_final_text(output, tasks_output),
            tool_calls=_tool_calls(tasks_output),
        )


def _tasks_output(output: Any) -> list[Any]:
    """Return the per-task output list from a CrewAI ``CrewOutput``.

    A standard ``CrewOutput`` exposes ``tasks_output`` as a list of
    ``TaskOutput`` objects (each carrying ``raw``, ``description``, ``agent``,
    and on recent versions ``tools_calls`` / ``tool_calls``). A bare-list or
    dict-shaped stand-in is read defensively so the mock-backed test does not
    require the real ``CrewOutput`` class.
    """
    if hasattr(output, "tasks_output"):
        value = output.tasks_output
        if isinstance(value, list):
            return value
        if value is None:
            return []
    if isinstance(output, list):
        return output
    if isinstance(output, dict):
        value = output.get("tasks_output")
        if isinstance(value, list):
            return value
    return []


def _final_text(output: Any, tasks_output: list[Any]) -> str:
    """Return the final text from a CrewAI ``CrewOutput``.

    CrewAI's modern ``CrewOutput`` exposes ``raw`` as the final string and
    falls back to ``str(output)`` for older shapes. When neither is present
    (a stand-in that returned only ``tasks_output``), the last task's ``raw``
    is the closest equivalent.
    """
    raw = getattr(output, "raw", None)
    if isinstance(raw, str) and raw:
        return raw
    if isinstance(output, dict):
        raw = output.get("raw")
        if isinstance(raw, str) and raw:
            return raw
    if tasks_output:
        last = tasks_output[-1]
        last_raw = getattr(last, "raw", None)
        if isinstance(last_raw, str) and last_raw:
            return last_raw
        if isinstance(last, dict):
            last_raw = last.get("raw")
            if isinstance(last_raw, str) and last_raw:
                return last_raw
    if isinstance(output, str):
        return output
    return str(output) if output is not None else ""


def _tool_call_name(call: Any) -> str | None:
    """Extract a tool-call name from one CrewAI tool-use record.

    CrewAI's records vary by version: some carry ``{"tool": "...", "input": ...}``,
    others ``{"name": "...", "arguments": ...}``, others a flat
    ``{"tool_name": "..."}``. Read all three shapes so a stand-in or any live
    version surfaces the call name.
    """
    if isinstance(call, dict):
        for key in ("tool", "name", "tool_name"):
            value = call.get(key)
            if isinstance(value, str) and value:
                return value
        function = call.get("function")
        if isinstance(function, dict):
            value = function.get("name")
            if isinstance(value, str) and value:
                return value
        return None
    for attr in ("tool", "name", "tool_name"):
        value = getattr(call, attr, None)
        if isinstance(value, str) and value:
            return value
    function = getattr(call, "function", None)
    if function is not None:
        value = getattr(function, "name", None)
        if isinstance(value, str) and value:
            return value
    return None


def _task_tool_calls(task_output: Any) -> Iterable[Any]:
    """Yield every tool-call record from one CrewAI ``TaskOutput``.

    Different CrewAI versions expose the per-task tool-use trace under
    different attributes - ``tools_calls`` (note the trailing 's', a quirk of
    early CrewAI), ``tool_calls`` (the corrected modern name), and
    ``tool_results`` (a higher-level wrapper carrying name + observation).
    Yield from each that exists.
    """
    for attr in ("tools_calls", "tool_calls", "tool_results"):
        if isinstance(task_output, dict):
            calls = task_output.get(attr)
        else:
            calls = getattr(task_output, attr, None)
        if calls is None:
            continue
        if isinstance(calls, list | tuple):
            yield from calls


def _tool_calls(tasks_output: list[Any]) -> tuple[str, ...]:
    """Walk every task's tool-use trace and surface each tool call's name.

    Returns the names in task order so a Class 7 probe sees which tool fired
    on which task. A task with no tool use contributes nothing; a task with
    several tool calls contributes one entry per call.
    """
    names: list[str] = []
    for task_output in tasks_output:
        for call in _task_tool_calls(task_output):
            name = _tool_call_name(call)
            if name is not None:
                names.append(name)
    return tuple(names)
