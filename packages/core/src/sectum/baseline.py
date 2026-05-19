"""Regression baselines: save a run's metrics and compare later runs to it.

A baseline is a saved snapshot of a run's headline metrics. Comparing a later
run to the baseline flags regressions - a metric that moved in the worse
(higher-leakage) direction, for example a higher Retrieval-Pivot Rate or more
confirmed findings after an embedding-model or prompt change (the engineering
spec, sections 10 and 14).
"""

from dataclasses import dataclass

from sectum.spec import RunMetrics


@dataclass(frozen=True)
class MetricDelta:
    """One headline metric compared between a baseline run and a later run."""

    name: str
    baseline: float
    current: float

    @property
    def regressed(self) -> bool:
        """True when the metric moved in the worse, higher-leakage direction."""
        return self.current > self.baseline


@dataclass(frozen=True)
class BaselineComparison:
    """The outcome of comparing a run's metrics against a saved baseline."""

    deltas: tuple[MetricDelta, ...]

    @property
    def regressed(self) -> bool:
        """True when any compared metric regressed."""
        return any(delta.regressed for delta in self.deltas)


def compare_metrics(baseline: RunMetrics, current: RunMetrics) -> BaselineComparison:
    """Compare a later run's metrics to a baseline; flag every metric that worsened.

    For each headline metric, higher means more leakage, so an increase is a
    regression. A Retrieval-Pivot Rate that was not measured counts as ``0.0``.
    """
    deltas = (
        MetricDelta(
            name="confirmed_findings",
            baseline=float(baseline.confirmed_findings),
            current=float(current.confirmed_findings),
        ),
        MetricDelta(
            name="retrieval_pivot_rate",
            baseline=baseline.retrieval_pivot_rate or 0.0,
            current=current.retrieval_pivot_rate or 0.0,
        ),
    )
    return BaselineComparison(deltas=deltas)
