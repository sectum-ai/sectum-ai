"""Tests for the regression-baseline engine."""

from datetime import UTC, datetime
from pathlib import Path

from sectum_ai.baseline import compare_metrics, diff_runs
from sectum_ai.spec import RunMetrics, RunResult


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


def test_higher_class_3_6_10_rates_are_regressions() -> None:
    """A rise in poisoning bleed, inversion reconstruction, or extraction
    efficiency is more cross-tenant leakage, so each regresses like the RPR."""
    for name in ("poisoning_bleed_delta", "inversion_reconstruction_rate", "extraction_efficiency"):
        baseline = RunMetrics(**{name: 0.1})
        current = RunMetrics(**{name: 0.6})
        comparison = compare_metrics(baseline, current)
        assert comparison.regressed, name
        delta = next(d for d in comparison.deltas if d.name == name)
        assert delta.regressed


def test_unmeasured_class_3_6_10_rates_count_as_zero() -> None:
    """``None`` (the probe did not run) never reads as a regression."""
    metrics = RunMetrics(poisoning_bleed_delta=None)
    assert not compare_metrics(metrics, metrics).regressed


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


def test_erasure_caveats_are_informational_not_a_regression() -> None:
    # A caveat is a backend coverage limitation (Class 11 hiding place #8), not
    # an isolation failure: it is reported but never counts as a regression.
    base = RunMetrics(erasure_caveats={"backup": 0})
    current = RunMetrics(erasure_caveats={"backup": 3})
    comparison = compare_metrics(base, current)
    assert not comparison.regressed
    delta = next(d for d in comparison.deltas if d.name == "erasure_caveats[backup]")
    assert delta.informational
    assert not delta.regressed
    assert delta.current == 3.0


def test_erasure_residue_regresses_while_a_caveat_does_not() -> None:
    # The deliberate distinction (task #78): residue is a failure and gates;
    # a caveat on another surface, even rising, does not flip the verdict.
    base = RunMetrics(erasure_residue={"vector_db": 0}, erasure_caveats={"backup": 0})
    current = RunMetrics(erasure_residue={"vector_db": 2}, erasure_caveats={"backup": 9})
    comparison = compare_metrics(base, current)
    assert comparison.regressed  # driven by residue, not the caveat
    caveat = next(d for d in comparison.deltas if d.name == "erasure_caveats[backup]")
    residue = next(d for d in comparison.deltas if d.name == "erasure_residue[vector_db]")
    assert not caveat.regressed and caveat.informational
    assert residue.regressed and not residue.informational


def test_severity_rank_covers_every_severity() -> None:
    # Guard against a future Severity member being added without a rank entry,
    # which would KeyError in FindingChange.severity_escalated at runtime.
    from sectum_ai.baseline import _SEVERITY_RANK
    from sectum_ai.spec import Severity

    assert set(_SEVERITY_RANK) == set(Severity)


def _run_for(probes: dict[str, str], *, poisoning: float | None = None) -> RunResult:
    moment = datetime(2026, 5, 18, 12, 30, tzinfo=UTC)
    return RunResult(
        run_id="run-1",
        scenario_hash="s",
        manifest_hash="m",
        started_at=moment,
        finished_at=moment,
        metrics=RunMetrics(
            per_probe_findings={"rag-poisoning": 24} if poisoning else {},
            poisoning_bleed_delta=poisoning,
        ),
        probe_versions=probes,
    )


def test_a_probe_the_baseline_covered_but_this_run_skipped_fails_the_gate() -> None:
    # A narrowed --suite (or a probe skipped for a missing adapter) drops every
    # metric that probe fed to zero, which read as an improvement: the gate printed
    # `[ok] per_probe_findings[rag-poisoning]: 24 -> 0` and "no regression", exit 0,
    # for a run that simply stopped testing Class 3. Nothing got worse - but the
    # guarantee the baseline established is no longer being checked.
    baseline = _run_for({"rag-poisoning": "0.7.1", "tenant-boundary-fetch": "0.7.1"}, poisoning=1.0)
    narrowed = _run_for({"tenant-boundary-fetch": "0.7.1"})
    result = diff_runs(baseline, narrowed)
    assert result.coverage_lost == ("rag-poisoning",)
    assert result.regressed  # the gate must not go green
    # ...and it is NOT reported as a leakage regression, because nothing worsened.
    assert not result.metrics.regressed


def test_re_running_the_same_probes_is_not_a_coverage_loss() -> None:
    # The complement: an identical run must still pass cleanly, or the gate is
    # useless. Coverage is compared by probe id, not by finding counts.
    baseline = _run_for({"rag-poisoning": "0.7.1"}, poisoning=1.0)
    again = _run_for({"rag-poisoning": "0.7.1"}, poisoning=1.0)
    result = diff_runs(baseline, again)
    assert result.coverage_lost == ()
    assert not result.regressed


def test_a_probe_that_ran_and_found_nothing_is_not_a_coverage_loss() -> None:
    # per_probe_findings counts FINDINGS, so a probe that ran clean is absent from
    # it. Keying coverage on that dict would have called every clean run a coverage
    # loss; coverage comes from probe_versions.
    baseline = _run_for({"rag-poisoning": "0.7.1"}, poisoning=1.0)
    clean = _run_for({"rag-poisoning": "0.7.1"})
    assert clean.metrics.per_probe_findings == {}
    assert diff_runs(baseline, clean).coverage_lost == ()


def test_baseline_compare_refuses_a_saved_record_from_another_schema_line(tmp_path: "Path") -> None:
    # The refusal lived in `diff`'s loader only, so `baseline --compare` read a
    # 0.6.x baseline (which recorded every adapter slot) and flagged [SCOPE LOST]
    # for surfaces that baseline never exercised - while the CHANGELOG said both
    # commands refused it.
    import json
    from pathlib import Path as _Path

    from typer.testing import CliRunner

    assert isinstance(tmp_path, _Path)

    from sectum_ai.cli.app import app

    runner = CliRunner()
    runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    runner.invoke(app, ["baseline", "--workdir", str(tmp_path), "--save"])
    saved = tmp_path / "baseline.json"
    record = json.loads(saved.read_text())
    record["schema_version"] = "0.6.0"
    saved.write_text(json.dumps(record))
    result = runner.invoke(app, ["baseline", "--workdir", str(tmp_path), "--compare"])
    assert result.exit_code == 3, result.output
    assert "schema '0.6.0'" in result.output
