"""Regression baselines: save a run's metrics and compare later runs to it.

A baseline is a saved snapshot of a run's headline metrics. Comparing a later
run to the baseline flags regressions - a metric that moved in the worse
(higher-leakage) direction, for example a higher Retrieval-Pivot Rate or more
confirmed findings after an embedding-model or prompt change (the engineering
spec, sections 10 and 14).
"""

from collections.abc import Mapping
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


def _dict_deltas(
    label: str, baseline: Mapping[str, float], current: Mapping[str, float]
) -> list[MetricDelta]:
    """A MetricDelta per key across both mappings; a key absent on a side is 0.0."""
    return [
        MetricDelta(
            name=f"{label}[{key}]",
            baseline=float(baseline.get(key, 0.0)),
            current=float(current.get(key, 0.0)),
        )
        for key in sorted(set(baseline) | set(current))
    ]


def compare_metrics(baseline: RunMetrics, current: RunMetrics) -> BaselineComparison:
    """Compare a later run's metrics to a baseline; flag every metric that worsened.

    Higher means more leakage for every metric, so an increase is a regression.
    Confirmed findings and the Retrieval-Pivot Rate are compared directly; the
    per-surface erasure residue and the per-pair side-channel effect sizes are
    compared key by key. A Retrieval-Pivot Rate that was not measured, or a key
    absent on one side, counts as ``0.0``.
    """
    deltas: list[MetricDelta] = [
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
    ]
    deltas.extend(
        _dict_deltas("erasure_residue", baseline.erasure_residue, current.erasure_residue)
    )
    deltas.extend(
        _dict_deltas(
            "side_channel_effect_sizes",
            baseline.side_channel_effect_sizes,
            current.side_channel_effect_sizes,
        )
    )
    return BaselineComparison(deltas=tuple(deltas))
