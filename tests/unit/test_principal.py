"""Tests for the principal isolation model (ADR-0006).

A principal is the isolation boundary Sectum verifies: a tenant, or a user
within a tenant. The substrate, detection, and surfaces are identical at
either granularity; only the boundary differs. This commit wires the spec
models and substrate; user-level detection/probing is a later phase.
"""

from collections import Counter
from uuid import UUID

from sectum.spec import (
    Principal,
    PrincipalKind,
    Scenario,
    SharedEntity,
    SyntheticTenantSpec,
    SyntheticUserSpec,
)
from sectum.substrate import build_substrate, default_scenario

_USER_A = UUID(int=0xA)
_USER_B = UUID(int=0xB)


def _scenario_with_users() -> Scenario:
    tenant = SyntheticTenantSpec(
        tenant_id=UUID(int=0x1),
        display_name="Acme Robotics",
        industry="robotics",
        corpus_size=24,
        users=(
            SyntheticUserSpec(user_id=_USER_A, display_name="Alice"),
            SyntheticUserSpec(user_id=_USER_B, display_name="Bob"),
        ),
    )
    return Scenario(
        scenario_id="users-demo",
        seed=7,
        tenants=(tenant,),
        shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
    )


def test_principal_kind_reflects_the_user_id() -> None:
    assert Principal(tenant_id=UUID(int=1)).kind is PrincipalKind.TENANT
    assert Principal(tenant_id=UUID(int=1), user_id=UUID(int=2)).kind is PrincipalKind.USER


def test_default_substrate_principals_are_all_tenant_level() -> None:
    substrate = build_substrate(default_scenario(seed=1))
    principals = substrate.principals()
    assert len(principals) == len(substrate.tenants)
    assert all(principal.kind is PrincipalKind.TENANT for principal in principals)


def test_substrate_principals_include_users_under_a_tenant() -> None:
    substrate = build_substrate(_scenario_with_users())
    principals = substrate.principals()
    # one tenant-level principal plus one per user
    assert sorted(principal.kind.value for principal in principals) == ["tenant", "user", "user"]
    assert {p.user_id for p in principals if p.user_id is not None} == {_USER_A, _USER_B}


def test_markers_are_distributed_across_users_round_robin() -> None:
    substrate = build_substrate(_scenario_with_users())
    counts = Counter(marker.owner_user_id for marker in substrate.manifest.markers)
    # six markers split evenly across the tenant's two users; none stay tenant-level
    assert counts[_USER_A] == 3
    assert counts[_USER_B] == 3
    assert None not in counts


def test_markers_without_users_stay_tenant_level() -> None:
    substrate = build_substrate(default_scenario(seed=1))
    assert all(marker.owner_user_id is None for marker in substrate.manifest.markers)


def test_markers_distribute_round_robin_with_a_remainder() -> None:
    tenant = SyntheticTenantSpec(
        tenant_id=UUID(int=0x1),
        display_name="Acme Robotics",
        industry="robotics",
        corpus_size=24,
        users=tuple(
            SyntheticUserSpec(user_id=UUID(int=0xC0 + i), display_name=f"User {i}")
            for i in range(4)
        ),
    )
    scenario = Scenario(
        scenario_id="uneven-users",
        seed=7,
        tenants=(tenant,),
        shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
    )
    substrate = build_substrate(scenario)
    counts = Counter(marker.owner_user_id for marker in substrate.manifest.markers)
    # six markers round-robin across four users -> two users get two, two get one
    assert sorted(counts.values(), reverse=True) == [2, 2, 1, 1]
    assert None not in counts


def test_principals_span_tenants_with_and_without_users() -> None:
    tenant_with_users = SyntheticTenantSpec(
        tenant_id=UUID(int=0x1),
        display_name="Acme Robotics",
        industry="robotics",
        corpus_size=24,
        users=(SyntheticUserSpec(user_id=_USER_A, display_name="Alice"),),
    )
    bare_tenant = SyntheticTenantSpec(
        tenant_id=UUID(int=0x2),
        display_name="Globex",
        industry="finance",
        corpus_size=24,
    )
    scenario = Scenario(
        scenario_id="mixed-users",
        seed=7,
        tenants=(tenant_with_users, bare_tenant),
        shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
    )
    substrate = build_substrate(scenario)
    # tenant A contributes itself plus its one user; the bare tenant contributes only itself
    assert [(p.tenant_id, p.user_id) for p in substrate.principals()] == [
        (UUID(int=0x1), None),
        (UUID(int=0x1), _USER_A),
        (UUID(int=0x2), None),
    ]
