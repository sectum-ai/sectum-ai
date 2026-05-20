"""Tests for the ``sectum`` command-line interface."""

import pytest
import typer
from typer.testing import CliRunner

from sectum.cli.app import _handle_typed_errors, app
from sectum.spec import AdapterError, ConfigError, EvidenceError

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
