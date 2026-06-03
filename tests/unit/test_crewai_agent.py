"""Mock-backed contract tests for the live CrewAI agent adapter.

CrewAI runs a workflow as a ``Crew`` of ``Agent`` objects collaborating on a
list of ``Task`` objects; ``crew.kickoff(inputs={...})`` runs the crew to
termination with named input variables that templated task descriptions
interpolate. The return is a ``CrewOutput`` carrying the final raw string
and a per-task ``tasks_output`` list - each ``TaskOutput`` exposes the tool
calls the agent made while completing that task. The adapter's logic is
verified here against an in-memory stand-in for the crew (the engineering
spec, sections 11 and 13: live SDK, mock-backed contract test plus opt-in
live). The live path is exercised by ``tests/integration/test_crewai.py``.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from sectum_ai.adapters.agent.crewai import CrewAIAgent
from sectum_ai.adapters.base import AgentAdapter, Capability
from sectum_ai.spec import AdapterError

_TENANT_A = UUID(int=0xA)
_TENANT_B = UUID(int=0xB)


@dataclass
class _Kickoff:
    """One recorded ``kickoff`` call (the inputs dict)."""

    inputs: dict[str, Any]


@dataclass
class _FakeTaskOutput:
    """A minimal stand-in for a CrewAI ``TaskOutput``.

    Carries the per-task ``raw`` text and the ``tools_calls`` list (note: the
    trailing 's' matches CrewAI's actual attribute name, which the adapter
    reads alongside the corrected ``tool_calls`` and the higher-level
    ``tool_results``).
    """

    raw: str = ""
    tools_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _FakeCrewOutput:
    """A minimal stand-in for a CrewAI ``CrewOutput``."""

    raw: str = ""
    tasks_output: list[_FakeTaskOutput] = field(default_factory=list)


@dataclass
class _FakeCrew:
    """A crew stand-in: records every kickoff call and replays a script.

    The ``script`` map keys on the kickoff input task string and returns the
    matching ``CrewOutput``, so a test can prove every ``run`` is invoked
    with the tenant-scoped inputs. The default fallback returns an empty
    output when no script entry matches.
    """

    script: dict[str, _FakeCrewOutput] = field(default_factory=dict)
    calls: list[_Kickoff] = field(default_factory=list)
    raise_on_kickoff: Exception | None = None

    def kickoff(self, inputs: dict[str, Any]) -> _FakeCrewOutput:
        if self.raise_on_kickoff is not None:
            raise self.raise_on_kickoff
        self.calls.append(_Kickoff(inputs=dict(inputs)))
        task = str(inputs.get("task", ""))
        return self.script.get(task, _FakeCrewOutput())


def _tool(name: str, **arguments: Any) -> dict[str, Any]:
    """One CrewAI-shaped tool-use record (the trailing-'s' tools_calls entry)."""
    return {"tool": name, "input": arguments}


def test_crewai_conforms_to_the_family_and_reports_tool_invocation() -> None:
    agent = CrewAIAgent(_FakeCrew())
    assert isinstance(agent, AgentAdapter)
    assert agent.supports(Capability.TOOL_INVOCATION)


def test_crewai_scopes_each_run_by_tenant_id_input() -> None:
    # Each tenant's hex id is passed in as the tenant_id kickoff input, so a
    # templated task description can interpolate it and a tenant-aware tool
    # reads the scope from its call arguments; the substrate verifies this
    # is what fires at Class 7.
    crew = _FakeCrew(
        script={
            "hi A": _FakeCrewOutput(raw="hello tenant A"),
            "hi B": _FakeCrewOutput(raw="hello tenant B"),
        }
    )
    agent = CrewAIAgent(crew)
    result_a = agent.run(_TENANT_A, "hi A")
    result_b = agent.run(_TENANT_B, "hi B")
    assert result_a.output == "hello tenant A"
    assert result_b.output == "hello tenant B"
    assert [call.inputs for call in crew.calls] == [
        {"tenant_id": _TENANT_A.hex, "task": "hi A"},
        {"tenant_id": _TENANT_B.hex, "task": "hi B"},
    ]


def test_crewai_surfaces_every_tool_call_across_tasks_in_order() -> None:
    # Class 7 (agent tool-call hijack) verifies which tools fire on every run -
    # not just the final state - so the adapter walks every task's tool-use
    # trace and surfaces each call in task order.
    crew = _FakeCrew(
        script={
            "research": _FakeCrewOutput(
                raw="report",
                tasks_output=[
                    _FakeTaskOutput(
                        raw="step 1",
                        tools_calls=[_tool("search", q="alpha"), _tool("fetch", url="...")],
                    ),
                    _FakeTaskOutput(raw="step 2", tools_calls=[_tool("summarize", text="...")]),
                ],
            )
        }
    )
    result = CrewAIAgent(crew).run(_TENANT_A, "research")
    assert result.output == "report"
    assert result.tool_calls == ("search", "fetch", "summarize")


def test_crewai_reads_modern_tool_calls_attribute_alongside_legacy_tools_calls() -> None:
    # Newer CrewAI versions corrected the typo and expose ``tool_calls``
    # (no trailing 's'); the adapter reads both attributes so it is portable.
    class _ModernTaskOutput:
        def __init__(self, raw: str, tool_calls: list[dict[str, Any]]) -> None:
            self.raw = raw
            self.tool_calls = tool_calls

    crew = _FakeCrew(
        script={
            "modern": _FakeCrewOutput(
                raw="done",
                tasks_output=[
                    _ModernTaskOutput("step", [{"name": "search", "arguments": {}}])  # type: ignore[list-item]
                ],
            )
        }
    )
    result = CrewAIAgent(crew).run(_TENANT_A, "modern")
    assert result.tool_calls == ("search",)


def test_crewai_reads_tool_results_records_with_a_flat_tool_name() -> None:
    # Some CrewAI versions expose a higher-level ``tool_results`` list whose
    # entries carry ``tool_name`` (flat) rather than ``tool`` or ``name``.
    class _ResultsTaskOutput:
        def __init__(self, raw: str, tool_results: list[dict[str, Any]]) -> None:
            self.raw = raw
            self.tool_results = tool_results

    crew = _FakeCrew(
        script={
            "results": _FakeCrewOutput(
                raw="ok",
                tasks_output=[
                    _ResultsTaskOutput(
                        "x",
                        [
                            {"tool_name": "lookup", "observation": "hit"},
                            {"tool_name": "verify", "observation": "ok"},
                        ],
                    )  # type: ignore[list-item]
                ],
            )
        }
    )
    result = CrewAIAgent(crew).run(_TENANT_A, "results")
    assert result.tool_calls == ("lookup", "verify")


def test_crewai_defaults_tool_calls_to_empty_and_skips_nameless_records() -> None:
    # A run with no tool use returns an empty tuple; a malformed record
    # without a usable name is skipped (the adapter never invents one).
    crew = _FakeCrew(
        script={
            "anything": _FakeCrewOutput(
                raw="just a reply",
                tasks_output=[
                    _FakeTaskOutput(raw="reply", tools_calls=[{"input": {}}]),
                ],
            )
        }
    )
    result = CrewAIAgent(crew).run(_TENANT_A, "anything")
    assert result.tool_calls == ()


def test_crewai_returns_the_crew_raw_text_as_output() -> None:
    crew = _FakeCrew(
        script={
            "ask": _FakeCrewOutput(
                raw="final crew answer",
                tasks_output=[_FakeTaskOutput(raw="task one"), _FakeTaskOutput(raw="task two")],
            )
        }
    )
    result = CrewAIAgent(crew).run(_TENANT_A, "ask")
    assert result.output == "final crew answer"


def test_crewai_falls_back_to_the_last_task_raw_when_crew_raw_is_missing() -> None:
    # An older CrewOutput shape (or a stand-in) may carry only tasks_output;
    # the adapter falls back to the last task's raw text rather than crashing.
    class _BareCrewOutput:
        def __init__(self, tasks_output: list[_FakeTaskOutput]) -> None:
            self.tasks_output = tasks_output

    class _BareCrew:
        def kickoff(self, inputs: dict[str, Any]) -> _BareCrewOutput:
            return _BareCrewOutput(
                [_FakeTaskOutput(raw="early"), _FakeTaskOutput(raw="last task answer")]
            )

    result = CrewAIAgent(_BareCrew()).run(_TENANT_A, "anything")
    assert result.output == "last task answer"


def test_crewai_reads_a_dict_shaped_crew_output() -> None:
    # A dict-shaped stand-in is read defensively so the adapter does not
    # require the real CrewOutput class.
    class _DictCrew:
        def kickoff(self, inputs: dict[str, Any]) -> dict[str, Any]:
            return {
                "raw": "from dict",
                "tasks_output": [
                    {"raw": "step", "tools_calls": [{"tool": "noop"}]},
                ],
            }

    result = CrewAIAgent(_DictCrew()).run(_TENANT_A, "anything")
    assert result.output == "from dict"
    assert result.tool_calls == ("noop",)


def test_crewai_handles_a_bare_string_kickoff_output() -> None:
    # The thinnest possible stand-in (or an older legacy shape) returns just
    # a string; the adapter passes it through and reports no tool calls.
    class _StringCrew:
        def kickoff(self, inputs: dict[str, Any]) -> str:
            return "raw string"

    result = CrewAIAgent(_StringCrew()).run(_TENANT_A, "anything")
    assert result.output == "raw string"
    assert result.tool_calls == ()


def test_crewai_raises_adapter_error_when_kickoff_fails() -> None:
    # Any exception from the underlying crew is wrapped in AdapterError so
    # the caller sees a consistent failure mode across every live agent adapter.
    crew = _FakeCrew(raise_on_kickoff=RuntimeError("model timeout"))
    with pytest.raises(AdapterError, match="crewai kickoff failed"):
        CrewAIAgent(crew).run(_TENANT_A, "anything")


def test_crewai_uses_custom_input_and_tenant_keys_when_configured() -> None:
    # An operator with a non-default task-description templating convention
    # can rename either input key; the adapter forwards them verbatim into the
    # crew's kickoff inputs.
    crew = _FakeCrew(script={})
    agent = CrewAIAgent(crew, input_key="query", tenant_key="customer")
    agent.run(_TENANT_A, "anything")
    assert crew.calls[0].inputs == {"customer": _TENANT_A.hex, "query": "anything"}


def test_crewai_returns_empty_output_when_kickoff_returns_none_like() -> None:
    # A crew that returns None (e.g., a stand-in that did nothing) does not
    # crash the adapter; the AgentResult carries an empty output.
    class _NoneCrew:
        def kickoff(self, inputs: dict[str, Any]) -> Any:
            return None

    result = CrewAIAgent(_NoneCrew()).run(_TENANT_A, "anything")
    assert result.output == ""
    assert result.tool_calls == ()
