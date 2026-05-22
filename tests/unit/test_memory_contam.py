"""Tests for Class 8 - the persistent memory contamination probe."""

from uuid import UUID

from sectum.adapters import FakeMemory
from sectum.probes import MemoryContamProbe, confirmed_findings
from sectum.runner import Runner
from sectum.spec import Scenario, SharedEntity, Substrate, SyntheticTenantSpec, SyntheticUserSpec
from sectum.substrate import build_substrate, default_scenario

_TENANT = UUID(int=1)
_USER_A = UUID(int=0xA)
_USER_B = UUID(int=0xB)


def _users_substrate() -> Substrate:
    scenario = Scenario(
        scenario_id="memory-users",
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


def test_user_scoped_memory_has_no_cross_user_contamination() -> None:
    # One tenant, two users: a user-scoped memory store recalls only the
    # caller's own notes, so a sibling user never surfaces the owner's canary -
    # no leak end to end (plan -> runner threads the actor user -> detect).
    substrate = _users_substrate()
    memory = FakeMemory(user_scoped=True)
    findings = Runner(substrate, memory=memory).run(MemoryContamProbe())
    assert confirmed_findings(findings) == []


def test_tenant_only_memory_leaks_across_users() -> None:
    # The same store scoped by tenant alone recalls every note in the tenant, so
    # a sibling user surfaces the owner's canary - the cross-user leak.
    substrate = _users_substrate()
    memory = FakeMemory(user_scoped=False)
    findings = confirmed_findings(Runner(substrate, memory=memory).run(MemoryContamProbe()))
    assert findings
    assert all(
        finding.owner_user_id is not None and finding.owner_user_id != finding.observed_in_user_id
        for finding in findings
    )
