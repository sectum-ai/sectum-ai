"""Tests for Class 9 - the LoRA / adapter cross-tenant influence probe."""

from sectum.adapters import FakeModel
from sectum.probes import LoraCrossTenantProbe, confirmed_findings
from sectum.runner import Runner
from sectum.substrate import build_substrate, default_scenario


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


def test_probe_plans_train_then_infer_steps() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = LoraCrossTenantProbe().plan(substrate)
    assert steps
    assert {step.action for step in steps} == {"model.train", "model.infer"}
