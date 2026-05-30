"""Tests for Class 5 - the KV-cache timing side-channel probe."""

from uuid import UUID

from sectum.adapters import FakeModel
from sectum.probes import KvCacheTimingProbe, confirmed_findings
from sectum.spec import Scenario, Severity, SharedEntity, Surface, SyntheticTenantSpec
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


# --- Statistical-rigor tests (spec §7 Class 5: t-test, p-value, CI) ----------

from sectum.probes.kv_cache_timing.probe import (  # noqa: E402
    _student_t_sf,
    _t_critical,
    _welch,
)


def test_student_t_survival_matches_t_table_references() -> None:
    # Two-sided tail probabilities against standard t-table critical values.
    assert _student_t_sf(0.0, 10) == 1.0
    assert abs(_student_t_sf(2.228, 10) - 0.05) < 0.005
    assert abs(_student_t_sf(3.169, 10) - 0.01) < 0.002
    # Large df approaches the normal: |t|=1.96 -> ~0.05.
    assert abs(_student_t_sf(1.96, 1_000_000) - 0.05) < 0.005


def test_t_critical_inverts_the_survival_function() -> None:
    assert abs(_t_critical(10, 0.95) - 2.228) < 0.01
    assert abs(_t_critical(10, 0.99) - 3.169) < 0.01


def test_welch_matches_a_textbook_two_sample_case() -> None:
    # Mean diff -5, equal spreads, n=5 each -> t=-5.0, df=8.0; p ~ 0.00105.
    t_stat, df, _ = _welch([1.0, 2.0, 3.0, 4.0, 5.0], [6.0, 7.0, 8.0, 9.0, 10.0])
    assert abs(t_stat - (-5.0)) < 1e-9
    assert abs(df - 8.0) < 1e-9
    assert abs(_student_t_sf(t_stat, df) - 0.00105) < 0.0005


def test_a_confirmed_finding_carries_p_value_and_confidence_interval() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    report = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=True)).run()
    findings = confirmed_findings(report.findings)
    assert findings
    for signal in report.signals:
        # Every detected pair is statistically significant, practically large,
        # and directional (primed faster -> positive gap).
        assert signal.p_value < 0.01
        assert signal.effect_size >= 0.8
        assert signal.mean_gap_ms > 0.0
        # The confidence interval on the gap excludes zero.
        assert signal.ci_low_ms > 0.0
        assert signal.ci_low_ms <= signal.mean_gap_ms <= signal.ci_high_ms
    # The evidence span an auditor reads cites the test, p-value, and CI.
    span = findings[0].evidence_span
    assert "p=" in span
    assert "CI" in span
    assert "Welch t=" in span


def test_no_cache_signals_are_not_statistically_significant() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    report = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=False)).run()
    assert report.findings == ()
    # No shared cache: the gap is noise, so nothing is significant and the
    # probe does not over-claim (spec §7 Class 5).
    for signal in report.signals:
        assert not signal.significant
        assert signal.p_value > 0.05


def test_timing_statistics_are_deterministic() -> None:
    # The fake model is deterministic, so two runs produce identical p-values
    # and confidence intervals - the reproducibility contract (spec §6.5).
    substrate = build_substrate(default_scenario(seed=2026))
    first = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=True)).run()
    second = KvCacheTimingProbe(substrate, model=FakeModel(prefix_cache=True)).run()
    assert [s.p_value for s in first.signals] == [s.p_value for s in second.signals]
    assert [s.ci_low_ms for s in first.signals] == [s.ci_low_ms for s in second.signals]


# --- Gate-arm and degenerate-input coverage (the avoid-over-claiming logic) ---

from sectum.probes.kv_cache_timing.probe import TimingSignal  # noqa: E402


def _signal(*, p_value: float, effect_size: float, mean_gap_ms: float) -> TimingSignal:
    """A TimingSignal with only the gate-relevant fields varied."""
    return TimingSignal(
        owner_tenant_id=UUID(int=1),
        observed_in_tenant_id=UUID(int=2),
        primed_mean_ms=40.0,
        control_mean_ms=40.0 + mean_gap_ms,
        mean_gap_ms=mean_gap_ms,
        effect_size=effect_size,
        t_statistic=0.0,
        degrees_of_freedom=46.0,
        p_value=p_value,
        ci_low_ms=mean_gap_ms - 1.0,
        ci_high_ms=mean_gap_ms + 1.0,
    )


def test_significant_requires_all_three_arms() -> None:
    # The avoid-over-claiming gate is significant AND large AND directional.
    assert _signal(p_value=0.001, effect_size=9.0, mean_gap_ms=5.0).significant
    # significant + large but WRONG direction (primed slower) -> not a finding.
    assert not _signal(p_value=0.001, effect_size=9.0, mean_gap_ms=-5.0).significant
    # significant + directional but SMALL effect -> not a finding.
    assert not _signal(p_value=0.001, effect_size=0.5, mean_gap_ms=5.0).significant
    # large + directional but NOT significant -> not a finding.
    assert not _signal(p_value=0.20, effect_size=9.0, mean_gap_ms=5.0).significant
    # p exactly at alpha (0.01) is not significant (strict <).
    assert not _signal(p_value=0.01, effect_size=9.0, mean_gap_ms=5.0).significant


def test_finding_severity_scales_with_effect_size() -> None:
    # _LARGE_EFFECT boundary (5.0): below is MEDIUM, at/above is HIGH.
    probe = KvCacheTimingProbe(
        build_substrate(default_scenario(seed=2026)), model=FakeModel(prefix_cache=True)
    )
    medium = probe._finding(_signal(p_value=0.001, effect_size=4.9, mean_gap_ms=5.0))
    high = probe._finding(_signal(p_value=0.001, effect_size=5.1, mean_gap_ms=5.0))
    assert medium.severity is Severity.MEDIUM
    assert high.severity is Severity.HIGH


def test_welch_handles_zero_variance_samples() -> None:
    # A constant-latency backend yields zero within-group spread. The Welch test
    # must not crash or claim a side channel: identical samples -> t=0, df=0;
    # different-but-constant means -> infinite t but df=0 (conservatively p=1.0).
    import math

    from sectum.probes.kv_cache_timing.probe import _student_t_sf

    t_eq, df_eq, se_eq = _welch([5.0, 5.0, 5.0, 5.0], [5.0, 5.0, 5.0, 5.0])
    assert (t_eq, df_eq, se_eq) == (0.0, 0.0, 0.0)
    assert _student_t_sf(t_eq, df_eq) == 1.0

    t_ne, df_ne, se_ne = _welch([7.0, 7.0, 7.0, 7.0], [5.0, 5.0, 5.0, 5.0])
    assert math.isinf(t_ne)
    assert df_ne == 0.0 and se_ne == 0.0
    # df <= 0 is conservatively non-significant, never a crash or false positive.
    assert _student_t_sf(t_ne, df_ne) == 1.0
