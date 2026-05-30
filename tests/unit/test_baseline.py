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


def test_a_removed_per_probe_key_is_not_a_regression() -> None:
    # A probe that stops leaking (its key drops out of current) is an
    # improvement, not a regression: the key-union treats the absent side as 0.0.
    base = RunMetrics(per_probe_findings={"rag-entity-bleed": 3})
    current = RunMetrics(per_probe_findings={})
    assert not compare_metrics(base, current).regressed


def test_per_model_rpr_epsilon_boundary() -> None:
    # A change below the 1e-9 tolerance is noise; a change above it is a real
    # regression. Pin both sides so the constant is a conscious choice.
    base = RunMetrics(retrieval_pivot_rate_by_model={"m": 0.5})
    within = RunMetrics(retrieval_pivot_rate_by_model={"m": 0.5 + 1e-10})
    beyond = RunMetrics(retrieval_pivot_rate_by_model={"m": 0.5 + 2e-9})
    assert not compare_metrics(base, within).regressed
    assert compare_metrics(base, beyond).regressed
