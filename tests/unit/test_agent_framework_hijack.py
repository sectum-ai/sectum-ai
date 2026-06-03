"""Tests for the Class 7 expansion - direct agent-framework tool-call hijack."""

from uuid import UUID

from sectum_ai.adapters import FakeAgent
from sectum_ai.probes import AgentFrameworkHijackProbe, confirmed_findings
from sectum_ai.runner import Runner
from sectum_ai.spec import (
    MarkerType,
    Scenario,
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


def test_tenant_scoped_agent_still_surfaces_cross_user_via_tenant_scope() -> None:
    # A FakeAgent that scopes only by tenant (no user-scope knob, by design) resolves
    # *any* same-tenant marker for a sibling-user caller - so a probe whose
    # foreign principals include the sibling user records cross-user findings
    # even when the confused-deputy / token-passthrough knobs are off.
    # (The MCP variant of Class 7 owns the user-scope test.)
    substrate = _users_substrate()
    agent = _seeded_agent(substrate)
    findings = confirmed_findings(Runner(substrate, agent=agent).run(AgentFrameworkHijackProbe()))
    assert findings
    assert all(
        finding.owner_user_id is not None and finding.owner_user_id != finding.observed_in_user_id
        for finding in findings
    )


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
