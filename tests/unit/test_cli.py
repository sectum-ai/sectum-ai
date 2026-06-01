"""Tests for the ``sectum`` command-line interface."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from sectum.cli.app import _handle_typed_errors, _load_run, _load_substrate, app
from sectum.spec import AdapterError, ConfigError, EvidenceError, RunMetrics, RunResult

_runner = CliRunner()


def test_version_flag_prints_the_version() -> None:
    result = _runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "sectum" in result.output


def test_adapters_command_lists_every_family() -> None:
    result = _runner.invoke(app, ["adapters"])
    assert result.exit_code == 0
    for name in (
        "fake-vector",
        "fake-rag",
        "fake-observability",
        "fake-agent",
        "fake-mcp",
        "fake-cache",
    ):
        assert name in result.output
    assert "per_tenant_namespace" in result.output


def test_bare_invocation_shows_help_listing_commands() -> None:
    result = _runner.invoke(app, [])
    assert "adapters" in result.output


def test_handle_typed_errors_passes_a_successful_call_through() -> None:
    @_handle_typed_errors
    def succeeds() -> str:
        return "ok"

    assert succeeds() == "ok"


def test_handle_typed_errors_maps_adapter_error_to_exit_3() -> None:
    @_handle_typed_errors
    def fails() -> None:
        raise AdapterError("boom")

    with pytest.raises(typer.Exit) as info:
        fails()
    assert info.value.exit_code == 3


def test_handle_typed_errors_maps_config_error_to_exit_3() -> None:
    @_handle_typed_errors
    def fails() -> None:
        raise ConfigError("bad config")

    with pytest.raises(typer.Exit) as info:
        fails()
    assert info.value.exit_code == 3


def test_handle_typed_errors_maps_evidence_error_to_exit_4() -> None:
    @_handle_typed_errors
    def fails() -> None:
        raise EvidenceError("bad pack")

    with pytest.raises(typer.Exit) as info:
        fails()
    assert info.value.exit_code == 4


def test_load_substrate_rejects_a_corrupt_substrate_file(tmp_path: Path) -> None:
    # A present-but-corrupt substrate.json must exit 3 (config error), not crash
    # with an unhandled pydantic ValidationError (which Typer reports as exit 1).
    (tmp_path / "substrate.json").write_text("{ not valid json")
    with pytest.raises(typer.Exit) as info:
        _load_substrate(tmp_path)
    assert info.value.exit_code == 3


def test_load_run_rejects_a_corrupt_run_file(tmp_path: Path) -> None:
    (tmp_path / "run.json").write_text("not json at all")
    with pytest.raises(typer.Exit) as info:
        _load_run(tmp_path)
    assert info.value.exit_code == 3


def test_baseline_compare_rejects_a_corrupt_baseline_file(tmp_path: Path) -> None:
    # A valid run plus a corrupt baseline.json must exit 3, not crash. (Covers the
    # third unguarded model_validate_json on the CLI load path.)
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    run = RunResult(
        run_id="r-1",
        scenario_hash="s",
        manifest_hash="m",
        started_at=moment,
        finished_at=moment,
        findings=(),
        metrics=RunMetrics(),
    )
    (tmp_path / "run.json").write_text(run.model_dump_json())
    (tmp_path / "baseline.json").write_text("{ not valid json")
    result = _runner.invoke(app, ["baseline", "--workdir", str(tmp_path), "--compare"])
    assert result.exit_code == 3
