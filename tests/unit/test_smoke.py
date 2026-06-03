"""Smoke test: every Sectum AI distribution imports under the shared namespace."""

import sectum_ai.adapters
import sectum_ai.cli.app
import sectum_ai.evidence
import sectum_ai.probes
import sectum_ai.spec


def test_namespace_packages_resolve() -> None:
    """All five distributions resolve under the shared ``sectum`` namespace."""
    for module in (
        sectum_ai.adapters,
        sectum_ai.cli,
        sectum_ai.evidence,
        sectum_ai.probes,
        sectum_ai.spec,
    ):
        assert module.__doc__, f"{module.__name__} is missing a module docstring"


def test_cli_app_is_constructed() -> None:
    """The Typer application is importable and named ``sectum-ai``."""
    assert sectum_ai.cli.app.app.info.name == "sectum-ai"
