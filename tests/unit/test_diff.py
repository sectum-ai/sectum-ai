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


def test_appeared_confirmed_excludes_unverified() -> None:
    diff = diff_findings([], [_finding("u", status=FindingStatus.UNVERIFIED)])
    assert [f.finding_id for f in diff.appeared] == ["u"]
    assert diff.appeared_confirmed == ()


def test_run_diff_flags_a_swapped_confirmed_finding_metrics_miss() -> None:
    # One confirmed leak resolves while a different one appears: the confirmed
    # count is unchanged (no metric regression) yet a new leak exists, so the
    # finding-level check must flag the regression.
    metrics = RunMetrics(confirmed_findings=1, per_probe_findings={"rag-entity-bleed": 1})
    earlier = _run(_finding("old"), metrics=metrics)
    later = _run(_finding("new"), metrics=metrics)
    result = diff_runs(earlier, later)
    assert not result.metrics.regressed
    assert result.regressed
    assert [f.finding_id for f in result.findings.appeared_confirmed] == ["new"]


def test_run_diff_no_change_is_not_a_regression() -> None:
    run = _run(_finding("a"), metrics=RunMetrics(confirmed_findings=1))
    result = diff_runs(run, run)
    assert not result.regressed
    assert result.findings.appeared == ()
    assert result.findings.resolved == ()


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
    assert payload["findings"]["appeared_confirmed_count"] == 1


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
