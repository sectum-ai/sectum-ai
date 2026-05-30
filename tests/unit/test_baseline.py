"""Tests for the regression-baseline engine."""

from sectum.baseline import compare_metrics
from sectum.spec import RunMetrics


def test_no_regression_when_metrics_are_unchanged() -> None:
    metrics = RunMetrics(confirmed_findings=10, retrieval_pivot_rate=0.5)
    comparison = compare_metrics(metrics, metrics)
    assert not comparison.regressed
    assert all(not delta.regressed for delta in comparison.deltas)


def test_more_confirmed_findings_is_a_regression() -> None:
    baseline = RunMetrics(confirmed_findings=10, retrieval_pivot_rate=0.5)
    current = RunMetrics(confirmed_findings=14, retrieval_pivot_rate=0.5)
    comparison = compare_metrics(baseline, current)
    assert comparison.regressed
    findings = next(delta for delta in comparison.deltas if delta.name == "confirmed_findings")
    assert findings.regressed


def test_a_higher_retrieval_pivot_rate_is_a_regression() -> None:
    baseline = RunMetrics(confirmed_findings=10, retrieval_pivot_rate=0.40)
    current = RunMetrics(confirmed_findings=10, retrieval_pivot_rate=0.95)
    assert compare_metrics(baseline, current).regressed


def test_fewer_findings_is_not_a_regression() -> None:
    baseline = RunMetrics(confirmed_findings=20, retrieval_pivot_rate=0.9)
    current = RunMetrics(confirmed_findings=5, retrieval_pivot_rate=0.1)
    assert not compare_metrics(baseline, current).regressed


def test_an_unmeasured_retrieval_pivot_rate_counts_as_zero() -> None:
    baseline = RunMetrics(confirmed_findings=1, retrieval_pivot_rate=None)
    current = RunMetrics(confirmed_findings=1, retrieval_pivot_rate=None)
    assert not compare_metrics(baseline, current).regressed


def test_a_higher_side_channel_effect_size_is_a_regression() -> None:
    baseline = RunMetrics(side_channel_effect_sizes={"acme->globex": 0.2})
    current = RunMetrics(side_channel_effect_sizes={"acme->globex": 9.4})
    comparison = compare_metrics(baseline, current)
    assert comparison.regressed
    delta = next(
        d for d in comparison.deltas if d.name == "side_channel_effect_sizes[acme->globex]"
    )
    assert delta.regressed


def test_new_erasure_residue_is_a_regression() -> None:
    baseline = RunMetrics(erasure_residue={"vector_db": 0})
    current = RunMetrics(erasure_residue={"vector_db": 3})
    assert compare_metrics(baseline, current).regressed


def test_unchanged_leakage_metrics_are_not_a_regression() -> None:
    metrics = RunMetrics(
        confirmed_findings=4,
        erasure_residue={"vector_db": 2},
        side_channel_effect_sizes={"acme->globex": 9.4},
    )
    assert not compare_metrics(metrics, metrics).regressed


def test_per_model_rpr_regression_is_flagged_when_the_aggregate_is_unchanged() -> None:
    # The canonical Phase-5 check: swapping one embedding model spikes that
    # model's Retrieval-Pivot Rate while the overall rate and confirmed count
    # stay put. compare_metrics must still flag it.
    base = RunMetrics(
        confirmed_findings=2,
        retrieval_pivot_rate=0.5,
        retrieval_pivot_rate_by_model={"MiniLM": 0.5, "mpnet": 0.5},
    )
    worse = RunMetrics(
        confirmed_findings=2,
        retrieval_pivot_rate=0.5,
        retrieval_pivot_rate_by_model={"MiniLM": 0.5, "mpnet": 0.95},
    )
    comparison = compare_metrics(base, worse)
    assert comparison.regressed
    assert [d.name for d in comparison.deltas if d.regressed] == [
        "retrieval_pivot_rate_by_model[mpnet]"
    ]


def test_per_probe_findings_increase_is_flagged_when_the_total_is_unchanged() -> None:
    # One probe starts leaking as another stops; the net confirmed count is
    # unchanged but a real regression occurred on the first probe.
    base = RunMetrics(confirmed_findings=2, per_probe_findings={"a": 2, "b": 0})
    worse = RunMetrics(confirmed_findings=2, per_probe_findings={"a": 0, "b": 2})
    comparison = compare_metrics(base, worse)
    assert comparison.regressed
    assert "per_probe_findings[b]" in [d.name for d in comparison.deltas if d.regressed]


def test_a_per_model_rpr_improvement_is_not_a_regression() -> None:
    base = RunMetrics(retrieval_pivot_rate_by_model={"mpnet": 0.9})
    better = RunMetrics(retrieval_pivot_rate_by_model={"mpnet": 0.2})
    assert not compare_metrics(base, better).regressed


def test_a_removed_per_probe_key_is_not_a_regression() -> None:
    # A probe that stops leaking (its key drops out of current) is an
    # improvement, not a regression: the key-union treats the absent side as 0.0.
    base = RunMetrics(per_probe_findings={"rag-entity-bleed": 3})
    current = RunMetrics(per_probe_findings={})
    assert not compare_metrics(base, current).regressed


def test_float_round_trip_noise_is_not_a_regression() -> None:
    # A metric serialized to JSON and back must not read as a regression on
    # floating-point noise below the comparison epsilon.
    base = RunMetrics(retrieval_pivot_rate=0.3)
    noisy = RunMetrics(retrieval_pivot_rate=0.3 + 1e-12)
    assert not compare_metrics(base, noisy).regressed


def test_per_model_rpr_epsilon_boundary() -> None:
    # Pin the 1e-9 tolerance from both sides so a future change is conscious.
    base = RunMetrics(retrieval_pivot_rate_by_model={"m": 0.5})
    within = RunMetrics(retrieval_pivot_rate_by_model={"m": 0.5 + 1e-10})
    beyond = RunMetrics(retrieval_pivot_rate_by_model={"m": 0.5 + 2e-9})
    assert not compare_metrics(base, within).regressed
    assert compare_metrics(base, beyond).regressed
