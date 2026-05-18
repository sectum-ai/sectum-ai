"""Tests for the ``sectum erasure`` CLI command (Class 11, the wedge)."""

from pathlib import Path

from typer.testing import CliRunner

from sectum.cli.app import app

_runner = CliRunner()


def test_erasure_is_verified_against_a_hard_deleting_store(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    assert "ERASURE VERIFIED" in result.output
    assert (tmp_path / "erasure-evidence.json").exists()
    assert (tmp_path / "erasure-attestation.pdf").read_bytes().startswith(b"%PDF")


def test_erasure_fails_against_a_soft_deleting_store(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path), "--soft-delete"])
    assert result.exit_code == 2
    assert "ERASURE FAILED" in result.output


def test_erasure_attestation_verifies(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["erasure", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["verify", str(tmp_path / "erasure-evidence.json")])
    assert result.exit_code == 0
    assert "VERIFIED" in result.output


def test_erasure_rejects_an_unknown_tenant(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app, ["erasure", "--workdir", str(tmp_path), "--target-tenant", "Nonexistent"]
    )
    assert result.exit_code == 3
