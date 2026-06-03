"""Tests for Class 7 - cross-tenant agent tool-call hijacking via MCP."""

from uuid import UUID

from sectum_ai.adapters import FakeMCP
from sectum_ai.probes import AgentToolHijackProbe, confirmed_findings
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


def _seeded_mcp(
    substrate: Substrate, *, confused_deputy: bool = False, token_passthrough: bool = False
) -> FakeMCP:
    mcp = FakeMCP(confused_deputy=confused_deputy, token_passthrough=token_passthrough)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            mcp.provision(
                marker.owner_tenant_id,
                marker.marker_id,
                f"MCP resource. Reference: {marker.plaintext}",
            )
    return mcp


def _users_substrate() -> Substrate:
    scenario = Scenario(
        scenario_id="mcp-users",
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


def _seeded_mcp_users(substrate: Substrate, *, user_scoped: bool) -> FakeMCP:
    mcp = FakeMCP(user_scoped=user_scoped)
    for marker in substrate.manifest.markers:
        if marker.marker_type is MarkerType.HARD_CANARY:
            mcp.provision(
                marker.owner_tenant_id,
                marker.marker_id,
                f"MCP resource. Reference: {marker.plaintext}",
                user=marker.owner_user_id,
            )
    return mcp


def test_confused_deputy_mcp_leaks_across_tenants() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    mcp = _seeded_mcp(substrate, confused_deputy=True)
    findings = confirmed_findings(Runner(substrate, mcp=mcp).run(AgentToolHijackProbe()))
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)


def test_token_passthrough_mcp_leaks_across_tenants() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    mcp = _seeded_mcp(substrate, token_passthrough=True)
    findings = confirmed_findings(Runner(substrate, mcp=mcp).run(AgentToolHijackProbe()))
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)


def test_isolated_mcp_has_no_tool_call_hijack() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    mcp = _seeded_mcp(substrate)
    findings = Runner(substrate, mcp=mcp).run(AgentToolHijackProbe())
    assert confirmed_findings(findings) == []


def test_probe_plans_a_direct_and_a_token_lookup_per_pair() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = AgentToolHijackProbe().plan(substrate)
    assert steps
    assert all(step.action == "mcp.invoke" for step in steps)
    assert sum("token" in step.payload for step in steps) == len(steps) // 2


def test_tenant_scoped_mcp_leaks_across_users() -> None:
    # One tenant, two users: a server scoped by tenant alone resolves a sibling
    # user's resource, so the principal-aware probe confirms a cross-user leak
    # (ADR-0006 default-deny).
    substrate = _users_substrate()
    mcp = _seeded_mcp_users(substrate, user_scoped=False)
    findings = confirmed_findings(Runner(substrate, mcp=mcp).run(AgentToolHijackProbe()))
    assert findings
    assert all(
        finding.owner_user_id is not None and finding.owner_user_id != finding.observed_in_user_id
        for finding in findings
    )


def test_user_scoped_mcp_has_no_cross_user_hijack() -> None:
    # A user-scoped server resolves only the caller's own resources, so a sibling
    # user's lookup surfaces nothing end to end.
    substrate = _users_substrate()
    mcp = _seeded_mcp_users(substrate, user_scoped=True)
    findings = Runner(substrate, mcp=mcp).run(AgentToolHijackProbe())
    assert confirmed_findings(findings) == []
