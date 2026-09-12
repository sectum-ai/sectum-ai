"""Tests for the Class 7 expansion - direct agent-framework tool-call hijack."""

from uuid import UUID

from sectum_ai.adapters import FakeAgent
from sectum_ai.probes import AgentFrameworkHijackProbe, confirmed_findings
from sectum_ai.probes.detection import dedupe_findings
from sectum_ai.runner import Runner
from sectum_ai.spec import (
    FindingStatus,
    MarkerType,
    Scenario,
    Severity,
    SharedEntity,
    Substrate,
    SyntheticTenantSpec,
    SyntheticUserSpec,
)
from sectum_ai.substrate import build_substrate, default_scenario

_TENANT = UUID(int=1)
_USER_A = UUID(int=0xA)
_USER_B = UUID(int=0xB)


def _seeded_agent(
    substrate: Substrate,
    *,
    confused_deputy: bool = False,
    tool_call_passthrough: bool = False,
) -> FakeAgent:
    agent = FakeAgent(
        confused_deputy=confused_deputy,
        tool_call_passthrough=tool_call_passthrough,
    )
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            agent.provision(
                marker.owner_tenant_id,
                marker.marker_id,
                f"agent tool returned. Reference: {marker.plaintext}",
            )
    return agent


def _users_substrate() -> Substrate:
    scenario = Scenario(
        scenario_id="agent-framework-users",
        seed=7,
        tenants=(
            SyntheticTenantSpec(
                tenant_id=_TENANT,
                display_name="Acme",
                industry="robotics",
                corpus_size=24,
                users=(
                    SyntheticUserSpec(user_id=_USER_A, display_name="Alice"),
                    SyntheticUserSpec(user_id=_USER_B, display_name="Bob"),
                ),
            ),
        ),
        shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
    )
    return build_substrate(scenario)


def test_a_clean_agent_run_says_what_it_did_not_establish() -> None:
    # The fourth by-id read: `lookup <marker_id>` across a principal boundary is
    # one, and this class graded a bare PASS over exactly Class 1's evidence.
    #
    # Unconditional, unlike the three siblings' `AccessOutcome.EMPTY` gate. For
    # them a RETURNED-but-clean read is real evidence - the backend handed back a
    # DIFFERENT object, so it resolved the id in the caller's own scope. An agent
    # narrates a refusal, a miss and a tool error identically, so gating on the
    # outcome would have kept the caveat silent on every live agent framework -
    # the case it exists for. FakeAgent pads a miss into "tool returned: ", which
    # is itself a 200 with an empty body.
    substrate = build_substrate(default_scenario(seed=2026))
    runner = Runner(substrate, agent=_seeded_agent(substrate))
    probe = AgentFrameworkHijackProbe()
    findings = dedupe_findings([f for _, per_step in runner.run_per_step(probe) for f in per_step])

    assert findings, "a scoped agent must not pass in silence"
    assert {f.status for f in findings} == {FindingStatus.UNVERIFIED}, findings
    assert all(f.severity is Severity.INFO for f in findings), findings
    # The wording has to match what was observed: nothing was 200-empty here.
    assert "narrates a refusal" in findings[0].evidence_span, findings[0].evidence_span
    assert "200-empty" not in findings[0].evidence_span, findings[0].evidence_span

    # And it stays silent where the leak is proven - a caveat beside a confirmed
    # finding would say the probe could not establish what it just established.
    leaky = Runner(substrate, agent=_seeded_agent(substrate, confused_deputy=True))
    confirmed = dedupe_findings([f for _, per_step in leaky.run_per_step(probe) for f in per_step])
    assert {f.status for f in confirmed} == {FindingStatus.CONFIRMED}, confirmed


def test_confused_deputy_agent_leaks_across_tenants() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    agent = _seeded_agent(substrate, confused_deputy=True)
    findings = confirmed_findings(Runner(substrate, agent=agent).run(AgentFrameworkHijackProbe()))
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)


def test_tool_call_passthrough_agent_leaks_across_tenants() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    agent = _seeded_agent(substrate, tool_call_passthrough=True)
    findings = confirmed_findings(Runner(substrate, agent=agent).run(AgentFrameworkHijackProbe()))
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)


def test_isolated_agent_has_no_framework_hijack() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    agent = _seeded_agent(substrate)
    findings = Runner(substrate, agent=agent).run(AgentFrameworkHijackProbe())
    assert confirmed_findings(findings) == []


def test_probe_plans_a_direct_and_a_token_run_per_pair() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = AgentFrameworkHijackProbe().plan(substrate)
    assert steps
    assert all(step.action == "agent.run" for step in steps)
    assert sum("token=" in step.payload["task"] for step in steps) == len(steps) // 2


def test_probe_findings_carry_the_agent_framework_surface() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    agent = _seeded_agent(substrate, confused_deputy=True)
    findings = confirmed_findings(Runner(substrate, agent=agent).run(AgentFrameworkHijackProbe()))
    assert findings
    assert all(finding.surface.value == "agent_framework" for finding in findings)


def test_user_level_steps_are_dropped_and_counted_for_an_interface_with_no_user() -> None:
    # `AgentAdapter.run(tenant, task)` carries no user, so a user-level step would
    # run as the tenant and be judged as the user: on a tenant-isolated agent every
    # sibling user's marker in the tenant's own answer confirmed as a CRITICAL
    # cross-user leak - of a session that never existed. The probe used to avoid
    # that by not PLANNING those steps, which also meant the runner's drop path
    # never fired: `user_steps_dropped` stayed empty, the audit PDF's "user-level
    # steps not run" clause never printed, and `diff` never reported
    # `[BOUNDARY LOST]` - the three things `docs/attack-catalog/index.md` promises
    # for exactly this contract. They are planned and dropped now, so the pass says
    # the user boundary was not tested rather than saying nothing.
    substrate = _users_substrate()
    steps = AgentFrameworkHijackProbe().plan(substrate)
    assert any(step.actor_user_id is not None for step in steps), steps

    probe = AgentFrameworkHijackProbe()
    runner = Runner(substrate, agent=_seeded_agent(substrate))
    results = runner.run_per_step(probe)
    # No user step reaches the adapter, so the false positive stays prevented...
    assert all(step.actor_user_id is None for step, _ in results)
    assert confirmed_findings([f for _, findings in results for f in findings]) == []
    # ...and the run now says how many it could not test.
    assert runner.dropped_user_steps.get(probe.id, 0) > 0


def test_fake_agent_default_is_non_leaky() -> None:
    agent = FakeAgent()
    other = UUID(int=2)
    agent.provision(other, "key-a", "secret-a")
    result = agent.run(UUID(int=1), "lookup key-a")
    # Non-leaky: the caller is tenant 1, the resource belongs to tenant 2,
    # so the agent returns an empty value.
    assert "secret-a" not in result.output
    assert result.tool_calls == ("lookup",)


def test_fake_agent_passes_token_through_when_knob_is_on() -> None:
    agent = FakeAgent(tool_call_passthrough=True)
    other = UUID(int=2)
    agent.provision(other, "key-a", "secret-a")
    result = agent.run(UUID(int=1), f"lookup key-a token={other.hex}")
    assert "secret-a" in result.output


def test_fake_agent_non_lookup_task_records_a_noop_tool_call() -> None:
    agent = FakeAgent()
    result = agent.run(UUID(int=1), "summarize the backlog")
    assert result.tool_calls == ("noop",)
    assert "summarize the backlog" in result.output
