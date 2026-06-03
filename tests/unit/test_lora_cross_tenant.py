"""Tests for Class 9 - the LoRA / adapter cross-tenant influence probe."""

from uuid import UUID

from sectum_ai.adapters import FakeModel
from sectum_ai.probes import LoraCrossTenantProbe, confirmed_findings
from sectum_ai.runner import Runner
from sectum_ai.spec import (
    FindingStatus,
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


def _users_substrate() -> Substrate:
    scenario = Scenario(
        scenario_id="lora-users",
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


def test_weight_bleed_surfaces_a_foreign_canary() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    model = FakeModel(adapter_bleed=True)
    findings = confirmed_findings(Runner(substrate, model=model).run(LoraCrossTenantProbe()))
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)


def test_isolated_adapters_have_no_cross_tenant_influence() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    model = FakeModel(adapter_bleed=False)
    findings = Runner(substrate, model=model).run(LoraCrossTenantProbe())
    assert confirmed_findings(findings) == []


def test_weight_bleed_also_raises_a_routing_finding() -> None:
    # Under adapter bleed a foreign tenant's adapter serves the request, so the
    # probe raises an explicit Class 9 routing finding (served_by != requester)
    # alongside the canary weight-bleed finding.
    substrate = build_substrate(default_scenario(seed=2026))
    findings = Runner(substrate, model=FakeModel(adapter_bleed=True)).run(LoraCrossTenantProbe())
    routing = [f for f in findings if f.finding_id.startswith("routing-")]
    assert routing
    for finding in routing:
        assert finding.status is FindingStatus.CONFIRMED
        assert finding.owner_tenant_id != finding.observed_in_tenant_id
        assert "mis-routed" in finding.evidence_span


def test_isolated_adapters_raise_no_routing_finding() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    findings = Runner(substrate, model=FakeModel(adapter_bleed=False)).run(LoraCrossTenantProbe())
    assert not [f for f in findings if f.finding_id.startswith("routing-")]


def test_served_by_attributes_a_foreign_serving_tenant_under_bleed() -> None:
    owner, requester = UUID(int=0x1), UUID(int=0x2)
    bleed = FakeModel(adapter_bleed=True)
    bleed.train_adapter(owner, ["memorized alpha fact"])
    # the foreign owner's adapter matches and serves the request -> mis-routed
    assert bleed.served_by(requester, "recall the alpha fact") == owner
    isolated = FakeModel(adapter_bleed=False)
    isolated.train_adapter(owner, ["memorized alpha fact"])
    # without bleed only the caller's own adapter is ever in scope
    assert isolated.served_by(requester, "recall the alpha fact") == requester


def test_probe_plans_train_then_infer_steps() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = LoraCrossTenantProbe().plan(substrate)
    assert steps
    assert {step.action for step in steps} == {"model.train", "model.infer"}


def test_tenant_scoped_adapters_leak_across_users() -> None:
    # One tenant, two users: a model scoping adapters by tenant alone recalls a
    # sibling user's memorized canary, so the principal-aware probe confirms a
    # cross-user bleed (ADR-0006 default-deny).
    substrate = _users_substrate()
    model = FakeModel(user_scoped=False)
    findings = confirmed_findings(Runner(substrate, model=model).run(LoraCrossTenantProbe()))
    assert findings
    assert all(
        finding.owner_user_id is not None and finding.owner_user_id != finding.observed_in_user_id
        for finding in findings
    )


def test_user_scoped_adapters_have_no_cross_user_influence() -> None:
    # A user-scoped model recalls only the caller's own adapter, so a sibling
    # user's inference surfaces nothing end to end.
    substrate = _users_substrate()
    model = FakeModel(user_scoped=True)
    findings = Runner(substrate, model=model).run(LoraCrossTenantProbe())
    assert confirmed_findings(findings) == []
