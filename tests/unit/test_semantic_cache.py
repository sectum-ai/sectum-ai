"""Tests for Class 4 - the semantic-cache-contamination probe."""

from sectum.adapters import FakeCache
from sectum.probes import SemanticCacheProbe, confirmed_findings
from sectum.runner import Runner
from sectum.substrate import build_substrate, default_scenario


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
