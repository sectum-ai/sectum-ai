"""Tests for Class 1 - the direct tenant-boundary-fetch probe."""

from uuid import UUID

from sectum.adapters import FakeVectorStore
from sectum.probes import TenantBoundaryProbe, confirmed_findings
from sectum.runner import Runner
from sectum.spec import (
    Scenario,
    SharedEntity,
    Substrate,
    SyntheticTenantSpec,
    SyntheticUserSpec,
)
from sectum.substrate import build_substrate, default_scenario

_TENANT = UUID(int=1)
_USER_A = UUID(int=0xA)
_USER_B = UUID(int=0xB)


def _seeded_store(substrate: Substrate, *, shared_index: bool) -> FakeVectorStore:
    store = FakeVectorStore(shared_index=shared_index)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        store.upsert(tenant.tenant_id, documents)
    return store


def _users_substrate() -> Substrate:
    scenario = Scenario(
        scenario_id="tb-users",
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


def _user_seeded_store(substrate: Substrate, *, user_scoped: bool) -> FakeVectorStore:
    store = FakeVectorStore(user_scoped=user_scoped)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        store.upsert(tenant.tenant_id, documents)
    return store


def test_shared_index_leaks_across_the_tenant_boundary() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=True)
    findings = confirmed_findings(Runner(substrate, vector=store).run(TenantBoundaryProbe()))
    assert findings
    assert all(finding.owner_tenant_id != finding.observed_in_tenant_id for finding in findings)


def test_isolated_index_has_no_tenant_boundary_leak() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, shared_index=False)
    findings = Runner(substrate, vector=store).run(TenantBoundaryProbe())
    assert confirmed_findings(findings) == []


def test_probe_plans_only_cross_tenant_fetch_steps() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = TenantBoundaryProbe().plan(substrate)
    assert steps
    tenant_ids = {tenant.tenant_id for tenant in substrate.tenants}
    for step in steps:
        assert step.action == "vector.fetch"
        assert step.actor_tenant_id in tenant_ids
        assert "doc_id" in step.payload


def test_user_scoped_store_has_no_cross_user_boundary_leak() -> None:
    # One tenant, two users: a user-scoped store denies each user the other's
    # hard-canary document, so the principal-aware Class 1 probe finds no leak
    # end to end (plan -> runner threads the actor user -> detect). ADR-0006/0008.
    substrate = _users_substrate()
    store = _user_seeded_store(substrate, user_scoped=True)
    findings = Runner(substrate, vector=store).run(TenantBoundaryProbe())
    assert confirmed_findings(findings) == []


def test_tenant_scoped_store_leaks_across_users() -> None:
    # The same store scoping by tenant alone ignores the fetch's user, so it
    # serves one user another user's document - the cross-user leak the
    # principal-aware probe now exercises end to end (ADR-0006 default-deny).
    substrate = _users_substrate()
    store = _user_seeded_store(substrate, user_scoped=False)
    findings = confirmed_findings(Runner(substrate, vector=store).run(TenantBoundaryProbe()))
    assert findings
    assert all(
        finding.owner_user_id is not None and finding.owner_user_id != finding.observed_in_user_id
        for finding in findings
    )
