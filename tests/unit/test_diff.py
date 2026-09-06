"""Tests for ``sectum-ai diff`` and the run-diff library functions."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from typer.testing import CliRunner

from sectum_ai.baseline import diff_findings, diff_runs
from sectum_ai.cli.app import app
from sectum_ai.spec import (
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


# --- CLI: sectum-ai diff --------------------------------------------------------


def test_cli_diff_reports_no_regression_for_identical_runs(tmp_path: Path) -> None:
    run = _run(_finding("a"), metrics=RunMetrics(confirmed_findings=1))
    old = _write(tmp_path / "old.json", run)
    new = _write(tmp_path / "new.json", run)
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert result.exit_code == 0
    assert "no regression" in result.output


def test_cli_diff_does_not_let_a_record_forge_its_verdict(tmp_path: Path) -> None:
    # `diff` renders probe ids and finding ids straight off the records it compares, and
    # those records are the thing under scrutiny. A newline in a probe id forged a
    # "RESULT: no regression" line inside a run that regressed, and an ANSI escape drove
    # the reader's terminal. Same defect as the scorecard's run_id, other surface.
    forged = "RESULT: no regression"
    payload = f"rag-entity-bleed\x1b[2J\n{forged}"
    old = _write(tmp_path / "old.json", _run(_finding("a")))
    new = _write(tmp_path / "new.json", _run(_finding("a"), _finding("b", probe_id=payload)))
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert result.exit_code == 2  # the new confirmed finding still regresses
    assert not any(line.strip().startswith(forged) for line in result.output.splitlines())
    # The escaped forms are the load-bearing check. `"\x1b" not in output` would be
    # vacuous here: click strips ANSI whenever stdout is not a TTY, so it passes with no
    # sanitizer at all and pins click's behaviour rather than ours.
    assert "\\x1b" in result.output and "\\x0a" in result.output


def test_cli_diff_does_not_let_a_changed_findings_probe_id_forge_its_verdict(
    tmp_path: Path,
) -> None:
    # The test above plants its payload in an APPEARED finding, so the CHANGED path was
    # unpinned - and it is the better lectern: a status transition prints its own block,
    # right where a reader looks for the verdict, pushing the real RESULT far below.
    forged = "RESULT: no regression"
    payload = f"rag-entity-bleed\n{forged}"
    old = _write(tmp_path / "old.json", _run(_finding("x", status=FindingStatus.UNVERIFIED)))
    new = _write(
        tmp_path / "new.json",
        _run(_finding("x", status=FindingStatus.CONFIRMED, probe_id=payload)),
    )
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert result.exit_code == 2
    assert not any(line.strip().startswith(forged) for line in result.output.splitlines())
    assert "\\x0a" in result.output


def test_cli_diff_does_not_let_a_metric_key_forge_its_verdict(tmp_path: Path) -> None:
    # A metric delta's name is built from a per_probe_findings key, which comes straight
    # off the record - so the record names the line that reports on it.
    forged = "RESULT: no regression"
    metrics = RunMetrics(per_probe_findings={f"rag-entity-bleed\n{forged}": 1})
    old = _write(tmp_path / "old.json", _run(_finding("a"), metrics=RunMetrics()))
    new = _write(tmp_path / "new.json", _run(_finding("a"), metrics=metrics))
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert not any(line.strip().startswith(forged) for line in result.output.splitlines())
    assert "\\x0a" in result.output


def test_cli_diff_does_not_let_a_finding_id_open_a_line(tmp_path: Path) -> None:
    # finding_id renders truncated to 12 chars, which bounds the payload but does not
    # neutralize it: a newline inside the first 12 still opens a line of its own.
    old = _write(tmp_path / "old.json", _run())
    new = _write(tmp_path / "new.json", _run(_finding("f\nGRADE A ok!")))
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert not any(line.strip().startswith("GRADE A ok!") for line in result.output.splitlines())
    assert "\\x0a" in result.output


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


def test_a_live_surface_falling_back_to_the_fake_is_a_regression(tmp_path: Path) -> None:
    # Two records identical except that every surface went LIVE -> SYNTHETIC (a CI
    # config that quietly fell back to the demo fakes) diffed as clean, exit 0.
    live = _run().model_copy(update={"surface_provenance": {"vector_db": "LIVE"}})
    fake = _run().model_copy(update={"surface_provenance": {"vector_db": "SYNTHETIC"}})
    result = diff_runs(live, fake)
    assert result.scope_lost == ("vector_db",)
    assert result.regressed
    assert diff_runs(fake, live).scope_lost == ()
    earlier, later = _write(tmp_path / "e.json", live), _write(tmp_path / "l.json", fake)
    cli = CliRunner().invoke(app, ["diff", str(earlier), str(later)])
    assert cli.exit_code == 2, cli.output
    assert "[SCOPE LOST] vector_db" in cli.output


def test_losing_one_of_a_metrics_feeding_probes_is_not_measured(tmp_path: Path) -> None:
    # Losing one of the two bleed probes changes the Retrieval-Pivot Rate's
    # denominator; the line still read "[ok]" (an improvement).
    earlier = _run(metrics=RunMetrics(retrieval_pivot_rate=0.5)).model_copy(
        update={"probe_versions": {"rag-entity-bleed": "1", "rag-pipeline-bleed": "1"}}
    )
    later = _run(metrics=RunMetrics(retrieval_pivot_rate=0.1)).model_copy(
        update={"probe_versions": {"rag-entity-bleed": "1"}}
    )
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "e.json", earlier)),
            str(_write(tmp_path / "l.json", later)),
        ],
    )
    assert "[not measured] retrieval_pivot_rate" in cli.output, cli.output


def test_a_probe_that_stopped_running_user_steps_is_a_regression(tmp_path: Path) -> None:
    earlier = _run()
    later = _run(metrics=RunMetrics(user_steps_dropped={"agent-tool-hijack": 48}))
    result = diff_runs(earlier, later)
    assert result.boundary_lost == ("agent-tool-hijack",)
    assert result.regressed
    assert diff_runs(later, later).boundary_lost == ()
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "e.json", earlier)),
            str(_write(tmp_path / "l.json", later)),
        ],
    )
    assert cli.exit_code == 2
    assert "[BOUNDARY LOST] agent-tool-hijack" in cli.output


def test_a_scenario_change_is_flagged_and_gates(tmp_path: Path) -> None:
    # Finding ids embed markers and principals, so across a re-seed every finding
    # "resolves": a later run with no users read every cross-user leak as fixed
    # (+0 appeared, -213 resolved, RESULT: no regression).
    earlier = _run(_finding("f-1"))
    later = _run().model_copy(update={"scenario_hash": "another"})
    result = diff_runs(earlier, later)
    assert result.scenario_changed and result.regressed
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "e.json", earlier)),
            str(_write(tmp_path / "l.json", later)),
        ],
    )
    assert cli.exit_code == 2
    assert "[SCENARIO CHANGED]" in cli.output


def test_a_record_from_another_schema_line_is_refused(tmp_path: Path) -> None:
    # A 0.6.x run recorded every adapter slot, so a diff against it flagged
    # surfaces the baseline never exercised as lost.
    old = _run().model_dump()
    old["schema_version"] = "0.6.0"
    old["surface_provenance"] = {"tracing": "LIVE"}
    path = tmp_path / "old.json"
    path.write_text(json.dumps(old, default=str))
    cli = CliRunner().invoke(app, ["diff", str(path), str(_write(tmp_path / "l.json", _run()))])
    assert cli.exit_code == 3, cli.output
    assert "schema '0.6.0'" in cli.output


def test_a_metric_is_not_measured_when_its_boundary_was_lost(tmp_path: Path) -> None:
    # `[ok] confirmed_findings: 1 -> 0` printed directly above `[BOUNDARY LOST]`,
    # asserting a fix the later run never re-measured.
    earlier = _run(_finding("f-1"))
    later = _run().model_copy(
        update={"metrics": RunMetrics(user_steps_dropped={"rag-entity-bleed": 12})}
    )
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "e.json", earlier)),
            str(_write(tmp_path / "l.json", later)),
        ],
    )
    assert "[BOUNDARY LOST] rag-entity-bleed" in cli.output
    assert "[ok] confirmed_findings" not in cli.output, cli.output
    assert "[not measured] confirmed_findings" in cli.output


def test_a_count_that_rose_under_a_loss_is_still_a_regression(tmp_path: Path) -> None:
    # Blanking the pooled count in both directions said "we didn't check" about a
    # number the run measured and tripled.
    earlier = _run(_finding("f-1"))
    later = _run(_finding("f-1"), _finding("f-2"), _finding("f-3")).model_copy(
        update={"metrics": RunMetrics(confirmed_findings=3, user_steps_dropped={"p": 4})}
    )
    earlier = earlier.model_copy(update={"metrics": RunMetrics(confirmed_findings=1)})
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "e.json", earlier)),
            str(_write(tmp_path / "l.json", later)),
        ],
    )
    assert "[REGRESSED] confirmed_findings: 1 -> 3" in cli.output, cli.output
    assert cli.exit_code == 2


def test_a_two_surface_probes_metric_is_not_measured_when_its_live_surface_falls_back(
    tmp_path: Path,
) -> None:
    # PROBE_SURFACES lists ALTERNATIVES and a run drives one of them, so requiring
    # every surface to be lost could never fire for the six two-surface probes -
    # the ones feeding three of the four headline rates - and a vector store that
    # fell back to the fake still printed `[ok] poisoning_bleed_delta: 1 -> 0`.
    earlier = _run(metrics=RunMetrics(poisoning_bleed_delta=1.0)).model_copy(
        update={
            "surface_provenance": {"vector_db": "LIVE"},
            "probe_versions": {"rag-poisoning": "1"},
        }
    )
    later = _run(metrics=RunMetrics(poisoning_bleed_delta=0.0)).model_copy(
        update={
            "surface_provenance": {"vector_db": "SYNTHETIC"},
            "probe_versions": {"rag-poisoning": "1"},
        }
    )
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "e.json", earlier)),
            str(_write(tmp_path / "l.json", later)),
        ],
    )
    assert "[SCOPE LOST] vector_db" in cli.output
    assert "[not measured] poisoning_bleed_delta" in cli.output, cli.output
    assert "[ok] poisoning_bleed_delta" not in cli.output


def test_an_erasure_surface_that_was_not_rescanned_is_not_a_fixed_leak(tmp_path: Path) -> None:
    # A Class 11 run whose own CLI printed ERASURE INCONCLUSIVE and exited 3
    # carries no residue count for that surface. `diff` read the missing count as
    # a drop to zero: two confirmed residual findings "resolved", every delta
    # `[ok]`, `RESULT: no regression`, exit 0 - on the wedge SKU's own diff. The
    # same shape as a lost probe or a lost live surface, on the fourth signal.
    earlier = _run(metrics=RunMetrics(erasure_residue={"vector_db": 2}))
    later = _run(metrics=RunMetrics(erasure_residue={}))
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "e.json", earlier)),
            str(_write(tmp_path / "l.json", later)),
        ],
    )
    assert "[ERASURE NOT RESCANNED] vector_db" in cli.output, cli.output
    assert "[not measured] erasure_residue[vector_db]" in cli.output, cli.output
    assert "[ok] erasure_residue[vector_db]" not in cli.output
    assert "RESULT: REGRESSION" in cli.output
    assert cli.exit_code == 2


def test_the_json_diff_carries_the_qualifier_the_text_diff_refuses_to_omit(
    tmp_path: Path,
) -> None:
    # The JSON carried `regressed` and `informational` but not the verdict, so a
    # machine reading it saw as fact the delta the human output declines to call
    # `[ok]`. And both CI-facing commands were silent about a run describing the
    # built-in fakes, where every other command discloses it.
    earlier = _run(metrics=RunMetrics(erasure_residue={"vector_db": 2}))
    later = _run(metrics=RunMetrics(erasure_residue={}))
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "e.json", earlier)),
            str(_write(tmp_path / "l.json", later)),
            "--output",
            "json",
        ],
    )
    payload = json.loads(cli.output[cli.output.index("{") :])
    residue = next(m for m in payload["metrics"] if m["name"] == "erasure_residue[vector_db]")
    assert residue["verdict"] == "not measured", payload["metrics"]
    assert payload["erasure_lost"] == ["vector_db"]


def test_a_side_channel_the_later_run_could_not_measure_is_not_a_closed_channel(
    tmp_path: Path,
) -> None:
    # `side_channel_effect_sizes` is keyed by tenant PAIR, so it matches no probe
    # id, no surface and no headline-metric name: none of the three lost-coverage
    # signals could reach it, and a dropped key became 0.0 in the diff. Keeping an
    # unmeasured pair out of the signed record was only half the fix - the diff
    # still read the absence as a drop to zero, and BOTH CI gates passed at exit 0
    # on a side channel the later run could not measure.
    pair = "a" * 32 + "->" + "b" * 32
    earlier = _run(metrics=RunMetrics(side_channel_effect_sizes={pair: 9.0}))
    later = _run(metrics=RunMetrics(side_channel_effect_sizes={}))
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "e.json", earlier)),
            str(_write(tmp_path / "l.json", later)),
        ],
    )
    assert f"[SIDE CHANNEL NOT REMEASURED] {pair}" in cli.output, cli.output
    assert f"[not measured] side_channel_effect_sizes[{pair}]" in cli.output
    assert "[ok] side_channel_effect_sizes" not in cli.output
    assert "RESULT: REGRESSION" in cli.output
    assert cli.exit_code == 2


def test_an_erasure_surface_that_fell_back_to_the_fake_is_not_a_cleared_residual(
    tmp_path: Path,
) -> None:
    # `scope_lost` is surface-keyed, but the verdict converted it into probe ids
    # via PROBE_SURFACES and matched those against the metric name - discarding
    # the surface key that `erasure_residue[<surface>]` needs. Every headline
    # metric on the same run read `[not measured]`; the erasure line was the lone
    # outlier, asserting the residual data was gone on the strength of a scan
    # against the built-in fake.
    earlier = _run(metrics=RunMetrics(erasure_residue={"vector_db": 2})).model_copy(
        update={"surface_provenance": {"vector_db": "LIVE"}}
    )
    later = _run(metrics=RunMetrics(erasure_residue={"vector_db": 0})).model_copy(
        update={"surface_provenance": {"vector_db": "SYNTHETIC"}}
    )
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "e.json", earlier)),
            str(_write(tmp_path / "l.json", later)),
        ],
    )
    assert "[not measured] erasure_residue[vector_db]" in cli.output, cli.output
    assert "[ok] erasure_residue[vector_db]" not in cli.output


def test_every_expanded_metric_map_treats_a_lost_key_as_unmeasured(tmp_path: Path) -> None:
    # Each of these maps is keyed by something the probe-id lookup cannot reach -
    # a surface, a tenant pair, an embedding model - and each had to be wired up
    # separately as it was noticed, three times over three cycles. The flag is set
    # where the 0.0 is filled in now, so this sweep covers the next map too.
    # `per_probe_findings` is deliberately NOT here: it counts findings, so a
    # probe that RAN and found nothing is absent from it, and the flag labelled
    # that clean result "not measured". See the two tests below - its genuine
    # coverage loss is caught by the stricter probe-id signal instead.
    cases = {
        "retrieval_pivot_rate_by_model": RunMetrics(retrieval_pivot_rate_by_model={"st:x": 0.9}),
        "erasure_residue": RunMetrics(erasure_residue={"vector_db": 2}),
        "side_channel_effect_sizes": RunMetrics(side_channel_effect_sizes={"a->b": 9.0}),
        "erasure_caveats": RunMetrics(erasure_caveats={"backup": 3}),
    }
    for name, metrics in cases.items():
        cli = CliRunner().invoke(
            app,
            [
                "diff",
                str(_write(tmp_path / f"{name}-e.json", _run(metrics=metrics))),
                str(_write(tmp_path / f"{name}-l.json", _run(metrics=RunMetrics()))),
            ],
        )
        line = next(x for x in cli.output.splitlines() if name in x and "[" in x)
        assert line.strip().startswith("[not measured]"), line


def test_a_probe_that_ran_and_found_nothing_does_not_read_not_measured(tmp_path: Path) -> None:
    # `per_probe_findings` counts FINDINGS, so a probe that ran and found nothing
    # is absent from it - `_exercised_probes` says exactly that. Marking its key
    # lost printed `[not measured] per_probe_findings[rag-entity-bleed]: 5 -> 0`
    # directly under `[ok] confirmed_findings: 5 -> 0`, for the same five
    # findings, with nothing lost at all. A label that fires on a clean result
    # teaches the reader to ignore it on a real one.
    earlier = _run(
        metrics=RunMetrics(confirmed_findings=5, per_probe_findings={"rag-x": 5})
    ).model_copy(update={"probe_versions": {"rag-x": "1"}})
    later = _run(metrics=RunMetrics()).model_copy(update={"probe_versions": {"rag-x": "1"}})
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "clean-e.json", earlier)),
            str(_write(tmp_path / "clean-l.json", later)),
        ],
    )
    assert "[ok] per_probe_findings[rag-x]: 5 -> 0" in cli.output, cli.output
    assert "[not measured] per_probe_findings" not in cli.output, cli.output


def test_a_probe_that_did_not_run_still_reads_not_measured(tmp_path: Path) -> None:
    # The other half: the same vanished key, but the later run never exercised the
    # probe. `coverage_lost` reaches it through the probe id in the key - the
    # stricter of the two signals, and the reason exempting this map is safe.
    earlier = _run(
        metrics=RunMetrics(confirmed_findings=5, per_probe_findings={"rag-x": 5})
    ).model_copy(update={"probe_versions": {"rag-x": "1"}})
    later = _run(metrics=RunMetrics()).model_copy(update={"probe_versions": {}})
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "lost-e.json", earlier)),
            str(_write(tmp_path / "lost-l.json", later)),
        ],
    )
    assert "[not measured] per_probe_findings[rag-x]: 5 -> 0" in cli.output, cli.output
    assert "[COVERAGE LOST] rag-x" in cli.output, cli.output


def test_a_headline_rate_the_later_run_never_measured_is_not_a_fixed_leak(tmp_path: Path) -> None:
    # The four scalar rates fill an absent measurement with 0.0 exactly as the
    # expanded maps do. `2c21f90` taught the MAPS that a filled 0.0 is not a
    # measurement and left the SCALARS relaying it - the incomplete-fix shape, one
    # commit later. Configuring a single live adapter leaves the other probes no
    # live step, so all four go None at once while `confirmed_findings` holds:
    # both gates then printed `[ok] 0.125 -> 0` four times and exited 0 on "no
    # regression", every leak rate "fixed" by not having been measured.
    measured = RunMetrics(
        confirmed_findings=229,
        retrieval_pivot_rate=0.125,
        poisoning_bleed_delta=1.0,
        inversion_reconstruction_rate=1.0,
        extraction_efficiency=0.18,
    )
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "measured.json", _run(metrics=measured))),
            str(
                _write(
                    tmp_path / "unmeasured.json", _run(metrics=RunMetrics(confirmed_findings=229))
                )
            ),
        ],
    )
    for name in (
        "retrieval_pivot_rate",
        "poisoning_bleed_delta",
        "inversion_reconstruction_rate",
        "extraction_efficiency",
    ):
        line = next(
            x
            for x in cli.output.splitlines()
            if x.strip().endswith(f" {name}: 0.125 -> 0") or (name in x and "[" in x and "->" in x)
        )
        assert line.strip().startswith("[not measured]"), line


def test_the_diff_recomputes_the_pivot_rate_from_the_records_own_counts(tmp_path: Path) -> None:
    # `score` and both PDF engines recompute this from k of n; `diff` relayed the
    # rate the record asserts about itself. A record whose counts say 95.4% while
    # its rate field says 0.0 therefore gated CI green at `[ok] 0 -> 0` and
    # printed 95.4% in the audit PDF bound to the same pack. Comparing a pack you
    # did not produce is this command's documented use.
    earlier = RunMetrics(retrieval_pivot_k=0, retrieval_pivot_n=350, retrieval_pivot_rate=0.0)
    later = RunMetrics(retrieval_pivot_k=334, retrieval_pivot_n=350, retrieval_pivot_rate=0.0)
    result = diff_runs(_run(metrics=earlier), _run(metrics=later))
    pivot = next(d for d in result.metrics.deltas if d.name == "retrieval_pivot_rate")
    assert pivot.baseline == 0.0
    assert abs(pivot.current - 334 / 350) < 1e-12
    assert pivot.regressed
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "rpr-e.json", _run(metrics=earlier))),
            str(_write(tmp_path / "rpr-l.json", _run(metrics=later))),
        ],
    )
    assert cli.exit_code == 2, cli.output
    assert "[REGRESSED] retrieval_pivot_rate" in cli.output, cli.output


def test_a_side_channel_pair_whose_surface_lost_its_backing_is_not_measured(tmp_path: Path) -> None:
    # `side_channel_effect_sizes` is keyed by tenant PAIR, so it names neither a
    # probe id nor a surface: a key that SURVIVES while the model surface behind
    # it falls back to the built-in fake matched no lookup, and read `[ok] 0.8 ->
    # 0` beside that surface's own `[SCOPE LOST]` line.
    pair = "00000000-0000-0000-0000-000000000001->00000000-0000-0000-0000-000000000002"
    live = _run(metrics=RunMetrics(side_channel_effect_sizes={pair: 0.8})).model_copy(
        update={"surface_provenance": {"model_adapter": "LIVE"}}
    )
    fake = _run(metrics=RunMetrics(side_channel_effect_sizes={pair: 0.0})).model_copy(
        update={"surface_provenance": {"model_adapter": "SYNTHETIC"}}
    )
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "sc-e.json", live)),
            str(_write(tmp_path / "sc-l.json", fake)),
        ],
    )
    line = next(x for x in cli.output.splitlines() if "side_channel_effect_sizes[" in x)
    assert line.strip().startswith("[not measured]"), line
    assert "[SCOPE LOST] model_adapter" in cli.output, cli.output


def test_a_baseline_that_never_measured_is_not_rendered_as_a_clean_one(tmp_path: Path) -> None:
    # The mirror of the lost-key fix, on the other side of the arrow. `baseline`
    # fills an absent value with 0.0 exactly as `current` does, so
    # `[REGRESSED] poisoning_bleed_delta: 0 -> 0.9` told the reader the earlier
    # run measured zero - a clean run that has since broken - when it measured
    # nothing at all. The same fill reaches every expanded map: a surface the
    # earlier run never scanned read `erasure_residue[backup]: 0 -> 2`.
    #
    # The REGRESSION itself stands. Dropping it would let a doctored earlier
    # record suppress the signal by omitting the metric - the "record chooses to
    # be believed" shape - so this is a rendering fix, and the exit code is
    # asserted below precisely so a later change cannot quietly weaken it.
    earlier = _run(metrics=RunMetrics(erasure_residue={"vector_db": 1}))
    later = _run(
        metrics=RunMetrics(poisoning_bleed_delta=0.9, erasure_residue={"vector_db": 1, "backup": 2})
    )
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "absent-e.json", earlier)),
            str(_write(tmp_path / "absent-l.json", later)),
        ],
    )
    assert cli.exit_code == 2, cli.output
    assert "[REGRESSED] poisoning_bleed_delta: (not measured) -> 0.9" in cli.output, cli.output
    assert "[REGRESSED] erasure_residue[backup]: (not measured) -> 2" in cli.output, cli.output
    # A side that WAS measured still prints its number, on both sides.
    assert "[ok] erasure_residue[vector_db]: 1 -> 1" in cli.output, cli.output


def test_the_json_diff_says_which_side_of_a_metric_was_measured(tmp_path: Path) -> None:
    # The text renderer refuses to state a fill as a value; the JSON stated a bare
    # `0` for both sides and a consumer read it as a measurement. Same qualifier,
    # both renderers - the rule this file has had to re-learn once per cycle.
    earlier = _run(metrics=RunMetrics(retrieval_pivot_rate=0.4))
    later = _run(metrics=RunMetrics(poisoning_bleed_delta=0.9))
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "js-e.json", earlier)),
            str(_write(tmp_path / "js-l.json", later)),
            "--output",
            "json",
        ],
    )
    metrics = {m["name"]: m for m in json.loads(cli.output)["metrics"]}
    # measured earlier, not measured later
    assert metrics["retrieval_pivot_rate"]["baseline_measured"] is True
    assert metrics["retrieval_pivot_rate"]["current_measured"] is False
    # not measured earlier, measured later
    assert metrics["poisoning_bleed_delta"]["baseline_measured"] is False
    assert metrics["poisoning_bleed_delta"]["current_measured"] is True
    # measured on NEITHER side: both are fills, so neither is a claim, and the
    # line reads `[not measured] ... (not measured) -> (not measured)` rather
    # than `[ok] ... 0 -> 0`, which asserted two runs had measured zero.
    assert metrics["extraction_efficiency"]["baseline_measured"] is False
    assert metrics["extraction_efficiency"]["current_measured"] is False
    assert metrics["extraction_efficiency"]["verdict"] == "not measured"


def test_an_unmeasured_headline_rate_fails_the_gate(tmp_path: Path) -> None:
    # The label was fixed and the gate was not: `diff` printed `[not measured]`
    # four times and exited 0 - saying plainly it could not compare, then
    # greenlighting the pipeline. Configuring one live adapter leaves the other
    # probes no live step, so all four go at once while `probe_versions` still
    # lists every probe, and no other loss signal can fire.
    measured = RunMetrics(
        retrieval_pivot_rate=0.125,
        poisoning_bleed_delta=0.125,
        inversion_reconstruction_rate=0.125,
        extraction_efficiency=0.125,
    )
    probes = {"probe_versions": {"rag-entity-bleed": "1", "rag-poisoning": "1"}}
    earlier = _run(metrics=measured).model_copy(update=probes)
    later = _run(metrics=RunMetrics()).model_copy(update=probes)
    result = diff_runs(earlier, later)
    assert result.metrics.headline_unmeasured == (
        "retrieval_pivot_rate",
        "poisoning_bleed_delta",
        "inversion_reconstruction_rate",
        "extraction_efficiency",
    )
    assert result.regressed
    # No OTHER signal fires, so this one is load-bearing rather than incidental.
    assert result.coverage_lost == () and result.scope_lost == ()

    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "hu-e.json", earlier)),
            str(_write(tmp_path / "hu-l.json", later)),
        ],
    )
    assert cli.exit_code == 2, cli.output
    assert "[RATE NOT REMEASURED] retrieval_pivot_rate" in cli.output, cli.output
    assert "RESULT: REGRESSION" in cli.output, cli.output


def test_a_changed_embedding_model_list_does_not_fail_the_gate(tmp_path: Path) -> None:
    # The counter-case, and the reason the gate keys on the four SCALARS rather
    # than on `key_lost` everywhere: `retrieval_pivot_rate_by_model` is a modelled
    # sweep the record labels as not a measurement of the store, and it degrades
    # to `{}` whenever the sweep cannot run. Gating that would fail CI on an
    # ordinary config change. It still LABELS the loss - the line reads
    # `[not measured]` - it just does not gate.
    earlier = _run(metrics=RunMetrics(retrieval_pivot_rate_by_model={"st:old": 0.9}))
    later = _run(metrics=RunMetrics())
    result = diff_runs(earlier, later)
    assert result.metrics.headline_unmeasured == ()
    assert not result.regressed
    cli = CliRunner().invoke(
        app,
        [
            "diff",
            str(_write(tmp_path / "em-e.json", earlier)),
            str(_write(tmp_path / "em-l.json", later)),
        ],
    )
    assert cli.exit_code == 0, cli.output
    assert "[not measured] retrieval_pivot_rate_by_model[st:old]" in cli.output, cli.output
