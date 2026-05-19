"""Tests for Class 8 - the persistent memory contamination probe."""

from sectum.adapters import FakeMemory
from sectum.probes import MemoryContamProbe, confirmed_findings
from sectum.runner import Runner
from sectum.substrate import build_substrate, default_scenario


def test_shared_memory_surfaces_a_foreign_canary() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    memory = FakeMemory(shared_memory=True)
    findings = confirmed_findings(Runner(substrate, memory=memory).run(MemoryContamProbe()))
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)


def test_isolated_memory_has_no_cross_tenant_contamination() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    memory = FakeMemory(shared_memory=False)
    findings = Runner(substrate, memory=memory).run(MemoryContamProbe())
    assert confirmed_findings(findings) == []


def test_probe_plans_write_then_recall_steps() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = MemoryContamProbe().plan(substrate)
    assert steps
    assert {step.action for step in steps} == {"memory.write", "memory.recall"}
