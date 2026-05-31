"""Tests for ``sectum diff`` and the run-diff library functions."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from typer.testing import CliRunner

from sectum.baseline import diff_findings, diff_runs
from sectum.cli.app import app
from sectum.spec import (
    EvidencePack,
    Finding,
    FindingStatus,
    RunMetrics,
    RunResult,
    Severity,
    Surface,
)

runner = CliRunner()


def _finding(
    finding_id: str,
    *,
    status: FindingStatus = FindingStatus.CONFIRMED,
    probe_id: str = "rag-entity-bleed",
    severity: Severity = Severity.HIGH,
) -> Finding:
    """A minimal finding; only the diff-relevant fields are varied."""
    return Finding(
        finding_id=finding_id,
        probe_id=probe_id,
        severity=severity,
        confidence=1.0,
        status=status,
        owner_tenant_id=UUID(int=1),
        observed_in_tenant_id=UUID(int=2),
        surface=Surface.KV_CACHE,
    )


def _run(*findings: Finding, metrics: RunMetrics | None = None) -> RunResult:
    """A RunResult wrapping the given findings (metrics default to empty)."""
    return RunResult(
        run_id="run",
        scenario_hash="s",
        manifest_hash="m",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        findings=findings,
        metrics=metrics or RunMetrics(),
    )


def _write(path: Path, run: RunResult) -> Path:
    path.write_text(run.model_dump_json())
    return path


# --- library: diff_findings / diff_runs --------------------------------------


def test_diff_findings_partitions_appeared_resolved_persisting() -> None:
    earlier = [_finding("a"), _finding("b")]
    later = [_finding("b"), _finding("c")]
    diff = diff_findings(earlier, later)
    assert [f.finding_id for f in diff.appeared] == ["c"]
    assert [f.finding_id for f in diff.resolved] == ["a"]
    assert [f.finding_id for f in diff.persisting] == ["b"]


def test_diff_findings_deduplicates_repeated_ids() -> None:
    earlier: list[Finding] = []
    later = [_finding("a"), _finding("a")]
    diff = diff_findings(earlier, later)
    # The repeated id is listed once, not twice.
    assert [f.finding_id for f in diff.appeared] == ["a"]
    assert [f.finding_id for f in diff.newly_confirmed] == ["a"]


def test_newly_confirmed_excludes_unverified() -> None:
    diff = diff_findings([], [_finding("u", status=FindingStatus.UNVERIFIED)])
    assert [f.finding_id for f in diff.appeared] == ["u"]
    # An unverified candidate never counts as a newly confirmed leak.
    assert diff.newly_confirmed == ()


def test_run_diff_flags_a_swapped_confirmed_finding_metrics_miss() -> None:
    # One confirmed leak resolves while a different one (new id) appears: the
    # confirmed count is unchanged (no metric regression) yet a new leak exists,
    # so the finding-level check must flag the regression.
    metrics = RunMetrics(confirmed_findings=1, per_probe_findings={"rag-entity-bleed": 1})
    earlier = _run(_finding("old"), metrics=metrics)
    later = _run(_finding("new"), metrics=metrics)
    result = diff_runs(earlier, later)
    assert not result.metrics.regressed
    assert result.regressed
    assert [f.finding_id for f in result.findings.newly_confirmed] == ["new"]


def test_run_diff_flags_an_in_place_status_upgrade() -> None:
    # The subtle hole: a finding that PERSISTS by id but was upgraded
    # unverified -> confirmed, while a different confirmed leak resolves. The
    # confirmed count is unchanged on both sides, so no metric regresses, and
    # the upgraded finding is "persisting" (not "appeared") -- yet a leak that
    # was a mere candidate is now a confirmed cross-tenant leak. Must regress.
    metrics = RunMetrics(confirmed_findings=1, per_probe_findings={"rag-entity-bleed": 1})
    earlier = _run(
        _finding("x", status=FindingStatus.UNVERIFIED),
        _finding("y", status=FindingStatus.CONFIRMED),
        metrics=metrics,
    )
    later = _run(
        _finding("x", status=FindingStatus.CONFIRMED),
        _finding("y", status=FindingStatus.UNVERIFIED),
        metrics=metrics,
    )
    result = diff_runs(earlier, later)
    assert not result.metrics.regressed
    assert "x" in [f.finding_id for f in result.findings.persisting]
    assert [f.finding_id for f in result.findings.newly_confirmed] == ["x"]
    assert result.regressed


def test_in_place_severity_escalation_is_gated() -> None:
    # A finding confirmed in BOTH runs whose severity rises (low -> critical) is
    # a worse isolation posture between the runs, so it gates -- even though no
    # metric count moved and it is "persisting", not "appeared".
    metrics = RunMetrics(confirmed_findings=1, per_probe_findings={"rag-entity-bleed": 1})
    earlier = _run(_finding("x", severity=Severity.LOW), metrics=metrics)
    later = _run(_finding("x", severity=Severity.CRITICAL), metrics=metrics)
    result = diff_runs(earlier, later)
    assert not result.metrics.regressed
    assert result.findings.newly_confirmed == ()
    assert [c.current.finding_id for c in result.findings.changed] == ["x"]
    assert [c.current.finding_id for c in result.findings.severity_escalations] == ["x"]
    assert result.regressed


def test_severity_de_escalation_is_a_change_but_not_a_regression() -> None:
    # critical -> low on a confirmed finding is an improvement: shown as a
    # change, never a regression.
    metrics = RunMetrics(confirmed_findings=1, per_probe_findings={"rag-entity-bleed": 1})
    earlier = _run(_finding("x", severity=Severity.CRITICAL), metrics=metrics)
    later = _run(_finding("x", severity=Severity.LOW), metrics=metrics)
    result = diff_runs(earlier, later)
    assert [c.current.finding_id for c in result.findings.changed] == ["x"]
    assert result.findings.severity_escalations == ()
    assert not result.regressed


def test_status_downgrade_is_a_change_but_not_a_regression() -> None:
    # confirmed -> unverified is an improvement (the leak is now only a
    # candidate): shown as a change, never a regression.
    earlier = _run(_finding("x", status=FindingStatus.CONFIRMED))
    later = _run(_finding("x", status=FindingStatus.UNVERIFIED))
    result = diff_runs(earlier, later)
    assert [c.current.finding_id for c in result.findings.changed] == ["x"]
    assert result.findings.severity_escalations == ()
    assert not result.regressed


def test_severity_escalation_on_an_unverified_finding_is_not_gated() -> None:
    # Severity rising on a finding that is not confirmed in both runs does not
    # gate (the false-positive control): an unverified candidate's severity is
    # not a confirmed-leak posture. If it became confirmed, newly_confirmed
    # would cover it instead.
    earlier = _run(_finding("x", status=FindingStatus.UNVERIFIED, severity=Severity.LOW))
    later = _run(_finding("x", status=FindingStatus.UNVERIFIED, severity=Severity.CRITICAL))
    result = diff_runs(earlier, later)
    assert [c.current.finding_id for c in result.findings.changed] == ["x"]
    assert result.findings.severity_escalations == ()
    assert not result.regressed


def test_run_diff_no_change_is_not_a_regression() -> None:
    run = _run(_finding("a"), metrics=RunMetrics(confirmed_findings=1))
    result = diff_runs(run, run)
    assert not result.regressed
    assert result.findings.appeared == ()
    assert result.findings.resolved == ()
    assert result.findings.newly_confirmed == ()


def test_run_diff_flags_a_worsened_metric() -> None:
    earlier = _run(metrics=RunMetrics(retrieval_pivot_rate=0.2))
    later = _run(metrics=RunMetrics(retrieval_pivot_rate=0.5))
    result = diff_runs(earlier, later)
    assert result.metrics.regressed
    assert result.regressed


# --- CLI: sectum diff --------------------------------------------------------


def test_cli_diff_reports_no_regression_for_identical_runs(tmp_path: Path) -> None:
    run = _run(_finding("a"), metrics=RunMetrics(confirmed_findings=1))
    old = _write(tmp_path / "old.json", run)
    new = _write(tmp_path / "new.json", run)
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert result.exit_code == 0
    assert "no regression" in result.output


def test_cli_diff_exits_2_on_a_new_confirmed_finding(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.json", _run(_finding("a")))
    new = _write(tmp_path / "new.json", _run(_finding("a"), _finding("b")))
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert result.exit_code == 2
    assert "REGRESSION" in result.output


def test_cli_diff_resolved_finding_is_not_a_regression(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.json", _run(_finding("a"), _finding("b")))
    new = _write(tmp_path / "new.json", _run(_finding("a")))
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert result.exit_code == 0


def test_cli_diff_json_output_is_machine_parseable(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.json", _run(_finding("a")))
    new = _write(tmp_path / "new.json", _run(_finding("a"), _finding("b")))
    result = runner.invoke(app, ["diff", str(old), str(new), "--output", "json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["regressed"] is True
    assert [f["finding_id"] for f in payload["findings"]["appeared"]] == ["b"]
    assert [f["finding_id"] for f in payload["findings"]["newly_confirmed"]] == ["b"]
    # The user dimension is present (null here) so cross-user leaks stay distinct.
    assert payload["findings"]["appeared"][0]["owner_user_id"] is None


def test_cli_diff_accepts_evidence_packs(tmp_path: Path) -> None:
    old_run = _run(_finding("a"))
    new_run = _run(_finding("a"), _finding("b"))
    old_pack = EvidencePack(run_result=old_run, manifest_hash=old_run.manifest_hash)
    new_pack = EvidencePack(run_result=new_run, manifest_hash=new_run.manifest_hash)
    old = tmp_path / "old-evidence.json"
    new = tmp_path / "new-evidence.json"
    old.write_text(old_pack.model_dump_json())
    new.write_text(new_pack.model_dump_json())
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert result.exit_code == 2
    assert "REGRESSION" in result.output


def test_cli_diff_missing_file_exits_3(tmp_path: Path) -> None:
    existing = _write(tmp_path / "old.json", _run())
    result = runner.invoke(app, ["diff", str(existing), str(tmp_path / "absent.json")])
    assert result.exit_code == 3


def test_cli_diff_malformed_json_exits_3(tmp_path: Path) -> None:
    good = _write(tmp_path / "old.json", _run())
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    result = runner.invoke(app, ["diff", str(good), str(bad)])
    assert result.exit_code == 3


def test_cli_diff_wrong_shape_json_exits_3(tmp_path: Path) -> None:
    # Valid JSON that is neither a RunResult nor an EvidencePack (a bare array)
    # is a clean config error (exit 3), not an unhandled traceback.
    good = _write(tmp_path / "old.json", _run())
    wrong = tmp_path / "wrong.json"
    wrong.write_text("[]")
    result = runner.invoke(app, ["diff", str(good), str(wrong)])
    assert result.exit_code == 3


def test_cli_diff_changed_finding_in_json(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.json", _run(_finding("x", severity=Severity.LOW)))
    new = _write(tmp_path / "new.json", _run(_finding("x", severity=Severity.CRITICAL)))
    result = runner.invoke(app, ["diff", str(old), str(new), "--output", "json"])
    assert result.exit_code == 2
    payload = json.loads(result.output)
    changed = payload["findings"]["changed"]
    assert [c["finding_id"] for c in changed] == ["x"]
    assert changed[0]["previous_severity"] == "low"
    assert changed[0]["severity"] == "critical"
    assert payload["findings"]["severity_escalation_count"] == 1
    assert payload["regressed"] is True


def test_cli_diff_changed_section_in_text(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.json", _run(_finding("x", severity=Severity.LOW)))
    new = _write(tmp_path / "new.json", _run(_finding("x", severity=Severity.CRITICAL)))
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert result.exit_code == 2
    assert "changed:" in result.output
    assert "low -> " in result.output and "critical" in result.output


def test_cli_diff_caveat_increase_is_informational_not_a_regression(tmp_path: Path) -> None:
    # A new erasure caveat (a backend coverage limitation) is reported but does
    # not gate: exit 0, the delta is flagged informational, regressed stays False.
    old = _write(
        tmp_path / "old.json",
        _run(_finding("x"), metrics=RunMetrics(erasure_caveats={"backup": 0})),
    )
    new = _write(
        tmp_path / "new.json",
        _run(_finding("x"), metrics=RunMetrics(erasure_caveats={"backup": 3})),
    )
    result = runner.invoke(app, ["diff", str(old), str(new), "--output", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    delta = next(d for d in payload["metrics"] if d["name"] == "erasure_caveats[backup]")
    assert delta["informational"] is True
    assert delta["regressed"] is False
    assert payload["regressed"] is False


def test_cli_diff_caveat_verdict_label_in_text(tmp_path: Path) -> None:
    old = _write(tmp_path / "old.json", _run(metrics=RunMetrics(erasure_caveats={"backup": 0})))
    new = _write(tmp_path / "new.json", _run(metrics=RunMetrics(erasure_caveats={"backup": 3})))
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert result.exit_code == 0
    assert "[info] erasure_caveats[backup]" in result.output


def test_cli_diff_erasure_residue_still_regresses(tmp_path: Path) -> None:
    # Guard the contrast: residue (a real failure) must still gate, unlike a caveat.
    old = _write(tmp_path / "old.json", _run(metrics=RunMetrics(erasure_residue={"vector_db": 0})))
    new = _write(tmp_path / "new.json", _run(metrics=RunMetrics(erasure_residue={"vector_db": 3})))
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert result.exit_code == 2


def test_unverified_to_confirmed_with_severity_rise_is_newly_confirmed_not_escalation() -> None:
    # A finding upgraded unverified->confirmed that ALSO rises in severity is
    # gated via newly_confirmed, not severity_escalations (which requires
    # confirmed-in-both). The two gating sets stay disjoint by status.
    earlier = _run(_finding("x", status=FindingStatus.UNVERIFIED, severity=Severity.LOW))
    later = _run(_finding("x", status=FindingStatus.CONFIRMED, severity=Severity.CRITICAL))
    result = diff_runs(earlier, later)
    assert [f.finding_id for f in result.findings.newly_confirmed] == ["x"]
    assert result.findings.severity_escalations == ()
    # It is still reported as an in-place change for visibility.
    assert [c.current.finding_id for c in result.findings.changed] == ["x"]
    assert result.regressed
