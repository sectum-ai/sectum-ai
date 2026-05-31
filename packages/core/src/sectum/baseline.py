"""Regression baselines: save a run's metrics and compare later runs to it.

A baseline is a saved snapshot of a run's headline metrics. Comparing a later
run to the baseline flags regressions - a metric that moved in the worse
(higher-leakage) direction, for example a higher Retrieval-Pivot Rate or more
confirmed findings after an embedding-model or prompt change (the engineering
spec, sections 10 and 14).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from sectum.spec import Finding, FindingStatus, RunMetrics, RunResult


@dataclass(frozen=True)
class MetricDelta:
    """One headline metric compared between a baseline run and a later run."""

    name: str
    baseline: float
    current: float

    @property
    def regressed(self) -> bool:
        """True when the metric moved in the worse, higher-leakage direction.

        Compared with a small tolerance so floating-point round-trip noise (a
        metric serialized to JSON and back) never reads as a regression; real
        leakage changes are far larger than the epsilon.
        """
        return self.current > self.baseline + 1e-9


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
    per-model Retrieval-Pivot Rate, the per-probe finding counts, the per-surface
    erasure residue, and the per-pair side-channel effect sizes are compared key
    by key. A Retrieval-Pivot Rate that was not measured, or a key absent on one
    side, counts as ``0.0``.

    The per-model RPR and per-probe counts matter because an aggregate can hide a
    regression: swapping one embedding model can spike that model's RPR (the
    canonical Phase-5 check, the engineering spec section 14) while the overall
    rate is unchanged, and one probe can start leaking as another stops with no
    change to the total confirmed count.
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
        _dict_deltas(
            "retrieval_pivot_rate_by_model",
            baseline.retrieval_pivot_rate_by_model,
            current.retrieval_pivot_rate_by_model,
        )
    )
    deltas.extend(
        _dict_deltas(
            "per_probe_findings",
            {key: float(value) for key, value in baseline.per_probe_findings.items()},
            {key: float(value) for key, value in current.per_probe_findings.items()},
        )
    )
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


@dataclass(frozen=True)
class FindingDiff:
    """Finding-level delta between two runs, keyed by stable ``finding_id``.

    ``appeared`` are findings in the later run but not the earlier one (a new
    leak); ``resolved`` are in the earlier run but gone from the later one (a
    fixed leak); ``persisting`` are in both (the later copy). Each list follows
    its source run's own deterministic finding order.
    """

    appeared: tuple[Finding, ...]
    resolved: tuple[Finding, ...]
    persisting: tuple[Finding, ...]
    # Findings confirmed in the later run whose id was not already confirmed in
    # the earlier run -- the regression signal. Broader than "confirmed and
    # newly appeared by id": it also catches a finding that persisted by id but
    # was upgraded unverified -> confirmed between the runs. An unverified
    # candidate never appears here (the false-positive control, the engineering
    # spec section 6.4), so it cannot flip a diff to a regression on its own.
    newly_confirmed: tuple[Finding, ...]


@dataclass(frozen=True)
class RunDiff:
    """A full comparison of two runs: metric deltas plus the finding-level diff."""

    metrics: BaselineComparison
    findings: FindingDiff

    @property
    def regressed(self) -> bool:
        """True when the later run is worse than the earlier one.

        A regression is any worsened metric (the baseline rule) *or* a newly
        confirmed finding. The finding check catches what the metric counts
        miss: a confirmed leak that is new -- by a fresh id, or by an in-place
        unverified -> confirmed upgrade -- can leave ``confirmed_findings``
        unchanged when another confirmed leak resolves in the same run, yet it
        is still a new leak.
        """
        return self.metrics.regressed or bool(self.findings.newly_confirmed)


def diff_findings(earlier: Sequence[Finding], later: Sequence[Finding]) -> FindingDiff:
    """Diff two finding sequences by ``finding_id`` into the four diff buckets.

    ``appeared``/``resolved``/``persisting`` partition by ``finding_id``;
    ``newly_confirmed`` is every finding confirmed in ``later`` whose id was not
    already confirmed in ``earlier`` (a fresh id, or an in-place upgrade). Each
    side is de-duplicated by ``finding_id`` (first occurrence wins) so a repeated
    id never lists a finding twice. Runs are de-duplicated upstream; this only
    guards a hand-built input.
    """
    earlier_ids = {finding.finding_id for finding in earlier}
    later_ids = {finding.finding_id for finding in later}
    earlier_confirmed_ids = {
        finding.finding_id for finding in earlier if finding.status is FindingStatus.CONFIRMED
    }

    def _select(findings: Sequence[Finding], keep: Callable[[str], bool]) -> tuple[Finding, ...]:
        seen: set[str] = set()
        chosen: list[Finding] = []
        for finding in findings:
            if finding.finding_id in seen or not keep(finding.finding_id):
                continue
            seen.add(finding.finding_id)
            chosen.append(finding)
        return tuple(chosen)

    newly_confirmed = _select(
        [finding for finding in later if finding.status is FindingStatus.CONFIRMED],
        lambda fid: fid not in earlier_confirmed_ids,
    )
    return FindingDiff(
        appeared=_select(later, lambda fid: fid not in earlier_ids),
        resolved=_select(earlier, lambda fid: fid not in later_ids),
        persisting=_select(later, lambda fid: fid in earlier_ids),
        newly_confirmed=newly_confirmed,
    )


def diff_runs(earlier: RunResult, later: RunResult) -> RunDiff:
    """Compare two runs: metric deltas (:func:`compare_metrics`) and a finding diff.

    ``earlier`` is the reference (an older run or a pre-change baseline) and
    ``later`` is the run under scrutiny, matching the argument order of
    :func:`compare_metrics`.
    """
    return RunDiff(
        metrics=compare_metrics(earlier.metrics, later.metrics),
        findings=diff_findings(earlier.findings, later.findings),
    )
