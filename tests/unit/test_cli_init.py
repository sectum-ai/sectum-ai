"""Tests for the ``sectum-ai init`` CLI command."""

from pathlib import Path

from typer.testing import CliRunner

from sectum_ai.cli.app import app
from sectum_ai.config import load_config

_runner = CliRunner()


def test_init_writes_a_config(tmp_path: Path) -> None:
    config = tmp_path / "sectum-ai.yaml"
    result = _runner.invoke(app, ["init", "--output", str(config)])
    assert result.exit_code == 0
    text = config.read_text()
    assert "scenario:" in text
    assert "adapters:" in text
    assert "evidence:" in text


def test_generated_config_round_trips_through_load_config(tmp_path: Path) -> None:
    # Regression: the documented `sectum-ai init` -> `--config` onboarding must work.
    # A comment-only `security:` block previously parsed to None and load_config
    # rejected it, so `sectum-ai seed --config <generated>` exited 3.
    config = tmp_path / "sectum-ai.yaml"
    assert _runner.invoke(app, ["init", "--output", str(config)]).exit_code == 0
    loaded = load_config(config)
    assert loaded.scenario.seed == 2026
    assert loaded.security.manifest_key_env is None  # default applied, not rejected


def test_init_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    config = tmp_path / "sectum-ai.yaml"
    config.write_text("existing")
    result = _runner.invoke(app, ["init", "--output", str(config)])
    assert result.exit_code == 3
    assert config.read_text() == "existing"


def test_init_overwrites_with_force(tmp_path: Path) -> None:
    config = tmp_path / "sectum-ai.yaml"
    config.write_text("existing")
    result = _runner.invoke(app, ["init", "--output", str(config), "--force"])
    assert result.exit_code == 0
    assert "scenario:" in config.read_text()
