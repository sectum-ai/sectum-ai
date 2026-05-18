"""Tests for the ``sectum seed`` and ``sectum probe`` CLI commands."""

import json
from pathlib import Path

from typer.testing import CliRunner

from sectum.cli.app import app

_runner = CliRunner()


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
