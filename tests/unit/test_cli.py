"""Tests for the ``sectum`` command-line interface."""

from typer.testing import CliRunner

from sectum.cli.app import app

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
