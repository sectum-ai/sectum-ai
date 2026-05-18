"""Tests for the ``sectum`` evidence-pipeline CLI commands."""

import json
from pathlib import Path

from typer.testing import CliRunner

from sectum.cli.app import app

_runner = CliRunner()


def _seed_and_probe(workdir: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(workdir)])
    _runner.invoke(app, ["probe", "--workdir", str(workdir)])


def test_seed_writes_a_substrate(tmp_path: Path) -> None:
    result = _runner.invoke(app, ["seed", "--workdir", str(tmp_path), "--seed", "2026"])
    assert result.exit_code == 0
    substrate = json.loads((tmp_path / "substrate.json").read_text())
    assert substrate["tenants"]
    assert substrate["documents"]


def test_probe_records_a_run_and_exits_two_on_confirmed_leaks(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    # the built-in demo stack is intentionally leaky: confirmed findings -> exit 2
    assert result.exit_code == 2
    run = json.loads((tmp_path / "run.json").read_text())
    assert run["metrics"]["confirmed_findings"] > 0
    assert run["metrics"]["retrieval_pivot_rate"] is not None


def test_probe_without_a_seeded_substrate_fails_cleanly(tmp_path: Path) -> None:
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code == 3


def test_report_builds_an_evidence_pack_and_pdf(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    result = _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "evidence.json").exists()
    assert (tmp_path / "audit-pack.pdf").read_bytes().startswith(b"%PDF")


def test_verify_passes_for_a_freshly_built_pack(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["verify", str(tmp_path / "evidence.json")])
    assert result.exit_code == 0
    assert "VERIFIED" in result.output


def test_verify_fails_on_a_tampered_pack(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    evidence_path = tmp_path / "evidence.json"
    pack = json.loads(evidence_path.read_text())
    pack["run_result"]["run_id"] = "tampered"
    evidence_path.write_text(json.dumps(pack))
    result = _runner.invoke(app, ["verify", str(evidence_path)])
    assert result.exit_code == 4
