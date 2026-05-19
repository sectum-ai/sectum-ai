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
