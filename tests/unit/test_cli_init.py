"""Tests for the ``sectum init`` CLI command."""

from pathlib import Path

from typer.testing import CliRunner

from sectum.cli.app import app

_runner = CliRunner()


def test_init_writes_a_config(tmp_path: Path) -> None:
    config = tmp_path / "sectum.yaml"
    result = _runner.invoke(app, ["init", "--output", str(config)])
    assert result.exit_code == 0
    text = config.read_text()
    assert "scenario:" in text
    assert "adapters:" in text
    assert "evidence:" in text


def test_init_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    config = tmp_path / "sectum.yaml"
    config.write_text("existing")
    result = _runner.invoke(app, ["init", "--output", str(config)])
    assert result.exit_code == 3
    assert config.read_text() == "existing"


def test_init_overwrites_with_force(tmp_path: Path) -> None:
    config = tmp_path / "sectum.yaml"
    config.write_text("existing")
    result = _runner.invoke(app, ["init", "--output", str(config), "--force"])
    assert result.exit_code == 0
    assert "scenario:" in config.read_text()
