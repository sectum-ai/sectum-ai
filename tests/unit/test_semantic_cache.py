"""Tests for Class 4 - the semantic-cache-contamination probe."""

from uuid import UUID

from sectum.adapters import FakeCache
from sectum.probes import SemanticCacheProbe, confirmed_findings
from sectum.runner import Runner
from sectum.spec import Scenario, SharedEntity, Substrate, SyntheticTenantSpec, SyntheticUserSpec
from sectum.substrate import build_substrate, default_scenario

_TENANT = UUID(int=1)
_USER_A = UUID(int=0xA)
_USER_B = UUID(int=0xB)


def _users_substrate() -> Substrate:
    scenario = Scenario(
        scenario_id="cache-users",
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


def test_shared_cache_serves_one_tenants_answer_to_another() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    cache = FakeCache(tenant_scoped=False)
    findings = confirmed_findings(Runner(substrate, cache=cache).run(SemanticCacheProbe()))
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)


def test_tenant_scoped_cache_isolates_each_tenant() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    cache = FakeCache(tenant_scoped=True)
    findings = Runner(substrate, cache=cache).run(SemanticCacheProbe())
    assert confirmed_findings(findings) == []


def test_probe_primes_every_key_before_it_is_fetched() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = SemanticCacheProbe().plan(substrate)
    assert steps
    primed: set[str] = set()
    for step in steps:
        if step.action == "cache.set":
            primed.add(step.payload["key"])
        else:
            assert step.action == "cache.get"
            assert step.payload["key"] in primed


def test_user_scoped_cache_isolates_users_within_a_tenant() -> None:
    # A cache scoped by both tenant and user folds the user into the key, so a
    # sibling user is never served another user's primed entry: no cross-user
    # leak end to end (plan -> runner threads the actor user -> detect).
    substrate = _users_substrate()
    cache = FakeCache(tenant_scoped=True, user_scoped=True)
    findings = Runner(substrate, cache=cache).run(SemanticCacheProbe())
    assert confirmed_findings(findings) == []


def test_tenant_only_cache_leaks_across_users() -> None:
    # The same cache scoped by tenant alone collapses two users of one tenant
    # onto one entry, so a sibling user is served the owner's cached answer -
    # the cross-user leak (ADR-0006 default-deny).
    substrate = _users_substrate()
    cache = FakeCache(tenant_scoped=True, user_scoped=False)
    findings = confirmed_findings(Runner(substrate, cache=cache).run(SemanticCacheProbe()))
    assert findings
    assert all(
        finding.owner_user_id is not None and finding.owner_user_id != finding.observed_in_user_id
        for finding in findings
    )
