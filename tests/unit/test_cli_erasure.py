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


def test_erasure_with_a_config_uses_its_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "from-config"
    config_path = tmp_path / "sectum.yaml"
    config_path.write_text(f"workdir: {workdir}\n")
    _runner.invoke(app, ["seed", "--workdir", str(workdir)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path)])
    assert result.exit_code == 0
    assert (workdir / "erasure-evidence.json").exists()


def test_erasure_uses_the_configs_soft_delete_setting(tmp_path: Path) -> None:
    """A config with soft-delete fakes drives the erasure failure (exit 2)."""
    config_path = tmp_path / "sectum.yaml"
    config_path.write_text(
        f"workdir: {tmp_path}\n"
        "adapters:\n"
        "  vector_store: {kind: fake, soft_delete: true}\n"
        "  observability: {kind: fake, soft_delete: true}\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path)])
    assert result.exit_code == 2
    assert "ERASURE FAILED" in result.output


def test_erasure_honors_only_observability_soft_delete_from_config(tmp_path: Path) -> None:
    """Asymmetric soft-delete: vector hard-deletes; only observability leaves residue."""
    config_path = tmp_path / "sectum.yaml"
    config_path.write_text(
        f"workdir: {tmp_path}\n"
        "adapters:\n"
        "  vector_store: {kind: fake, soft_delete: false}\n"
        "  observability: {kind: fake, soft_delete: true}\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path)])
    # the observability soft-delete drives the failure (the vector surface erased fine)
    assert result.exit_code == 2
    assert "ERASURE FAILED" in result.output


def test_erasure_warns_when_soft_delete_is_combined_with_config(tmp_path: Path) -> None:
    """--soft-delete is ignored when --config is given; a warning is emitted."""
    config_path = tmp_path / "sectum.yaml"
    config_path.write_text(f"workdir: {tmp_path}\n")
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path), "--soft-delete"])
    # --soft-delete is dropped, so the run uses the config's default (hard-delete fake)
    # and exits 0; the warning tells the user the flag was ignored
    assert result.exit_code == 0
    assert "--soft-delete is ignored" in result.output
