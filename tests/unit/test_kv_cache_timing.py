"""Tests for Class 5 - the KV-cache timing side-channel probe."""

from sectum.adapters import FakeModel
from sectum.probes import KvCacheTimingProbe, confirmed_findings
from sectum.spec import Surface
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
