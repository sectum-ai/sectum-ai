"""Tests for Class 5 - the KV-cache timing side-channel probe."""

from uuid import UUID

from sectum.adapters import FakeModel
from sectum.probes import KvCacheTimingProbe, confirmed_findings
from sectum.spec import Scenario, SharedEntity, Surface, SyntheticTenantSpec
from sectum.substrate import build_substrate, default_scenario


def test_shared_prefix_cache_is_a_timing_side_channel() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    model = FakeModel(prefix_cache=True)
    report = KvCacheTimingProbe(substrate, model=model).run()
    findings = confirmed_findings(report.findings)
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)
    assert all(f.surface is Surface.KV_CACHE for f in findings)
    assert all(signal.effect_size > 1.0 for signal in report.signals)


def test_no_prefix_cache_has_no_timing_side_channel() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    model = FakeModel(prefix_cache=False)
    report = KvCacheTimingProbe(substrate, model=model).run()
    assert report.findings == ()
    # without a shared cache the timing gap stays inside the noise floor
    assert all(abs(signal.effect_size) < 0.8 for signal in report.signals)


def test_report_exposes_per_pair_effect_sizes() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    model = FakeModel(prefix_cache=True)
    report = KvCacheTimingProbe(substrate, model=model).run()
    # four tenants yield twelve ordered (owner, observer) pairs
    assert len(report.effect_sizes) == 12
    assert all(value > 1.0 for value in report.effect_sizes.values())


def test_two_low_valued_tenants_yield_distinct_finding_ids() -> None:
    # UUID(int=0xA) and UUID(int=0xC) share their first 8 hex chars ("00000000"),
    # so a truncated finding id would collide and dedupe_findings would merge two
    # distinct cross-tenant timing leaks into one. Full hex keeps them distinct.
    scenario = Scenario(
        scenario_id="kv-low-ids",
        seed=1,
        tenants=(
            SyntheticTenantSpec(
                tenant_id=UUID(int=0xA), display_name="Acme", industry="robotics", corpus_size=24
            ),
            SyntheticTenantSpec(
                tenant_id=UUID(int=0xC), display_name="Globex", industry="finance", corpus_size=24
            ),
        ),
        shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
    )
    substrate = build_substrate(scenario)
    report = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=True)).run()
    finding_ids = [finding.finding_id for finding in report.findings]
    # both ordered pairs (A->C, C->A) are detected, and their ids do not collide
    assert len(finding_ids) >= 2
    assert len(set(finding_ids)) == len(finding_ids)
