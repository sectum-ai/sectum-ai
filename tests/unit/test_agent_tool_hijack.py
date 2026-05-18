"""Tests for Class 7 - cross-tenant agent tool-call hijacking via MCP."""

from sectum.adapters import FakeMCP
from sectum.probes import AgentToolHijackProbe, confirmed_findings
from sectum.runner import Runner
from sectum.spec import MarkerType, Substrate
from sectum.substrate import build_substrate, default_scenario


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
