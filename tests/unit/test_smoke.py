"""Smoke test: every Sectum AI distribution imports under the shared namespace."""

import sectum.adapters
import sectum.cli.app
import sectum.evidence
import sectum.probes
import sectum.spec


def test_namespace_packages_resolve() -> None:
    """All five distributions resolve under the shared ``sectum`` namespace."""
    for module in (
        sectum.adapters,
        sectum.cli,
        sectum.evidence,
        sectum.probes,
        sectum.spec,
    ):
        assert module.__doc__, f"{module.__name__} is missing a module docstring"


def test_cli_app_is_constructed() -> None:
    """The Typer application is importable and named ``sectum``."""
    assert sectum.cli.app.app.info.name == "sectum"
