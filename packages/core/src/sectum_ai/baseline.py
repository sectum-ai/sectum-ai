"""Regression baselines: save a run's metrics and compare later runs to it.

A baseline is a saved snapshot of a run's headline metrics. Comparing a later
run to the baseline flags regressions - a metric that moved in the worse
(higher-leakage) direction, for example a higher Retrieval-Pivot Rate or more
confirmed findings after an embedding-model or prompt change (the engineering
spec, sections 10 and 14).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from sectum_ai.spec import (
    Finding,
    FindingStatus,
    RunMetrics,
    RunResult,
    Severity,
    SurfaceProvenance,
)


@dataclass(frozen=True)
class MetricDelta:
    """One headline metric compared between a baseline run and a later run."""

    name: str
    baseline: float
    current: float
    # An informational metric is reported for visibility but never counts as a
    # regression: an erasure *caveat* (a backend with no per-tenant erasure API,
    # Class 11 hiding place #8) is a coverage limitation, not an isolation
    # failure. It is kept distinct from erasure *residue*, which is a real
    # failure and does regress.
    informational: bool = False

    @property
    def regressed(self) -> bool:
        """True when the metric moved in the worse, higher-leakage direction.

        Always ``False`` for an informational metric. Compared with a small
        tolerance so floating-point round-trip noise (a metric serialized to
        JSON and back) never reads as a regression; real leakage changes are far
        larger than the epsilon.
        """
        if self.informational:
            return False
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
    label: str,
    baseline: Mapping[str, float],
    current: Mapping[str, float],
    *,
    informational: bool = False,
) -> list[MetricDelta]:
    """A MetricDelta per key across both mappings; a key absent on a side is 0.0."""
    return [
        MetricDelta(
            name=f"{label}[{key}]",
            baseline=float(baseline.get(key, 0.0)),
            current=float(current.get(key, 0.0)),
            informational=informational,
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

    Per-surface erasure *caveats* are also reported, but as informational deltas
    that never count as a regression: a caveat is a coverage limitation of the
    backend (Class 11 hiding place #8), not an isolation failure like residue.
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
        # Class 3/6/10 headline rates: higher means more cross-tenant leakage, so
        # an increase regresses exactly like the retrieval-pivot rate above.
        MetricDelta(
            name="poisoning_bleed_delta",
            baseline=baseline.poisoning_bleed_delta or 0.0,
            current=current.poisoning_bleed_delta or 0.0,
        ),
        MetricDelta(
            name="inversion_reconstruction_rate",
            baseline=baseline.inversion_reconstruction_rate or 0.0,
            current=current.inversion_reconstruction_rate or 0.0,
        ),
        MetricDelta(
            name="extraction_efficiency",
            baseline=baseline.extraction_efficiency or 0.0,
            current=current.extraction_efficiency or 0.0,
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
    deltas.extend(
        _dict_deltas(
            "erasure_caveats",
            baseline.erasure_caveats,
            current.erasure_caveats,
            informational=True,
        )
    )
    return BaselineComparison(deltas=tuple(deltas))


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


@dataclass(frozen=True)
class FindingChange:
    """A finding present in both runs (same ``finding_id``) that changed in place.

    ``previous`` is its earlier-run copy and ``current`` its later-run copy. A
    change is a difference in status (e.g. unverified -> confirmed) or severity
    (e.g. low -> critical) for what is, by id, the same leak.
    """

    previous: Finding
    current: Finding

    @property
    def status_changed(self) -> bool:
        """True when the finding's status differs between the runs."""
        return self.previous.status is not self.current.status

    @property
    def severity_changed(self) -> bool:
        """True when the finding's severity differs between the runs."""
        return self.previous.severity is not self.current.severity

    @property
    def severity_escalated(self) -> bool:
        """True when the severity rose (a worse posture), not fell."""
        return _SEVERITY_RANK[self.current.severity] > _SEVERITY_RANK[self.previous.severity]


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
    # Findings present in both runs whose status or severity changed in place
    # (matched by id), for visibility. The subset that gates a regression is
    # ``severity_escalations``.
    changed: tuple[FindingChange, ...]

    @property
    def severity_escalations(self) -> tuple[FindingChange, ...]:
        """Persisting findings, confirmed in both runs, whose severity rose.

        A leak that was already a confirmed cross-tenant finding becoming more
        severe (e.g. low -> critical) is a worse isolation posture between the
        runs, so it gates as a regression. Requiring confirmed-in-both keeps this
        disjoint from ``newly_confirmed`` (which covers unverified -> confirmed)
        and clear of the false-positive control.
        """
        return tuple(
            change
            for change in self.changed
            if change.severity_escalated
            and change.previous.status is FindingStatus.CONFIRMED
            and change.current.status is FindingStatus.CONFIRMED
        )


@dataclass(frozen=True)
class RunDiff:
    """A full comparison of two runs: metric deltas plus the finding-level diff."""

    metrics: BaselineComparison
    findings: FindingDiff
    # Probes the earlier run exercised that the later one did not. Not a leakage
    # regression - nothing got worse - but the guarantee the baseline established
    # is no longer being checked, and every metric those probes fed reads as an
    # improvement to zero.
    coverage_lost: tuple[str, ...] = ()
    # Surfaces the earlier run exercised against a live backend that the later
    # run exercised against the built-in fake, or not at all. Not a leak - but
    # every verdict on them now describes the fake, so a run whose config quietly
    # fell back to the demo stack read as "no regression" (or as an improvement,
    # when the fake "resolved" every leak).
    scope_lost: tuple[str, ...] = ()

    @property
    def regressed(self) -> bool:
        """True when the later run is worse than the earlier one.

        A regression is any worsened metric (the baseline rule), a newly
        confirmed finding, *or* an in-place severity escalation of a finding
        confirmed in both runs. The finding checks catch what the metric counts
        miss: a confirmed leak that is new -- by a fresh id, or by an in-place
        unverified -> confirmed upgrade -- can leave ``confirmed_findings``
        unchanged when another confirmed leak resolves in the same run; and a
        known leak growing more severe (low -> critical) is a worse posture the
        counts do not see at all.

        A probe the baseline exercised and this run did not also fails the gate.
        Nothing got worse, but every metric that probe fed reads as an improvement
        to zero - ``per_probe_findings[rag-poisoning]: 24 -> 0`` - so a gate that
        passed here would report "no regression" for a run that quietly stopped
        testing whole attack classes, via a narrowed ``--suite`` or a probe skipped
        for a missing adapter. Re-baseline deliberately to change what is covered.
        """
        return (
            self.metrics.regressed
            or bool(self.findings.newly_confirmed)
            or bool(self.findings.severity_escalations)
            or bool(self.coverage_lost)
            or bool(self.scope_lost)
        )


def diff_findings(earlier: Sequence[Finding], later: Sequence[Finding]) -> FindingDiff:
    """Diff two finding sequences by ``finding_id`` into the diff buckets.

    ``appeared``/``resolved``/``persisting`` partition by ``finding_id``;
    ``newly_confirmed`` is every finding confirmed in ``later`` whose id was not
    already confirmed in ``earlier`` (a fresh id, or an in-place upgrade);
    ``changed`` is every persisting finding whose status or severity differs
    between the runs. Each side is de-duplicated by ``finding_id`` (first
    occurrence wins) so a repeated id never lists a finding twice. Runs are
    de-duplicated upstream; this only guards a hand-built input.
    """
    earlier_ids = {finding.finding_id for finding in earlier}
    later_ids = {finding.finding_id for finding in later}
    earlier_confirmed_ids = {
        finding.finding_id for finding in earlier if finding.status is FindingStatus.CONFIRMED
    }
    earlier_by_id: dict[str, Finding] = {}
    for finding in earlier:
        earlier_by_id.setdefault(finding.finding_id, finding)

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
    changed: list[FindingChange] = []
    changed_seen: set[str] = set()
    for finding in later:
        fid = finding.finding_id
        if fid in changed_seen or fid not in earlier_by_id:
            continue
        changed_seen.add(fid)
        previous = earlier_by_id[fid]
        if previous.status is not finding.status or previous.severity is not finding.severity:
            changed.append(FindingChange(previous=previous, current=finding))
    return FindingDiff(
        appeared=_select(later, lambda fid: fid not in earlier_ids),
        resolved=_select(earlier, lambda fid: fid not in later_ids),
        persisting=_select(later, lambda fid: fid in earlier_ids),
        newly_confirmed=newly_confirmed,
        changed=tuple(changed),
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
        coverage_lost=_coverage_lost(earlier, later),
        scope_lost=_scope_lost(earlier, later),
    )


def _scope_lost(earlier: RunResult, later: RunResult) -> tuple[str, ...]:
    """Surfaces live in the earlier run and not live in the later one."""
    live = SurfaceProvenance.LIVE.value
    return tuple(
        sorted(
            surface
            for surface, provenance in earlier.surface_provenance.items()
            if provenance == live and later.surface_provenance.get(surface) != live
        )
    )


def _exercised_probes(run: RunResult) -> set[str]:
    """The probe ids a run demonstrably exercised.

    ``probe_versions`` is the record's own bookkeeping; a finding is independent
    proof its probe ran, so a record whose bookkeeping is missing still reports the
    coverage its findings demonstrate.

    ANY finding counts, not just a confirmed one. ``score._confirmed_probe_ids``
    takes confirmed-only because it asks a different question - "did this probe
    prove a leak?" - whereas coverage asks "did this probe run?", and an unverified
    candidate answers that just as well. Confirmed-only would read a leak downgraded
    confirmed -> unverified (an improvement) as the probe disappearing.

    ``per_probe_findings`` is NOT usable here: it counts findings, so a probe that
    ran and found nothing is absent from it, and absence there would read as "did
    not run" on every clean run.
    """
    return set(run.probe_versions) | {finding.probe_id for finding in run.findings}


def _coverage_lost(earlier: RunResult, later: RunResult) -> tuple[str, ...]:
    """Probes the baseline exercised that the later run did not."""
    return tuple(sorted(_exercised_probes(earlier) - _exercised_probes(later)))
