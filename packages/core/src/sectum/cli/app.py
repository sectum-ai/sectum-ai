"""Entry point for the ``sectum`` command-line interface.

Implemented so far: ``--version`` and ``adapters``. The remaining commands
(init, seed, probe, report, verify, erasure, baseline) are specified in the
engineering spec, section 10.
"""

from typing import Annotated

import typer

from sectum.adapters import (
    AdapterRegistry,
    FakeAgent,
    FakeCache,
    FakeMCP,
    FakeObservability,
    FakeRAGPipeline,
    FakeVectorStore,
)

__version__ = "0.0.0"

app = typer.Typer(
    name="sectum",
    help="Sectum AI - multi-tenant AI verification.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Print the CLI version and exit when ``--version`` is passed."""
    if value:
        typer.echo(f"sectum {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the Sectum CLI version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Sectum AI - multi-tenant AI verification."""


@app.command(name="adapters")
def list_adapters() -> None:
    """List the installed adapters and their capabilities."""
    registry = AdapterRegistry()
    for fake in (
        FakeVectorStore(),
        FakeRAGPipeline(),
        FakeObservability(),
        FakeAgent(),
        FakeMCP(),
        FakeCache(),
    ):
        registry.register(fake)
    typer.echo(f"{'ADAPTER':<22}{'FAMILY':<18}CAPABILITIES")
    for adapter in registry.all():
        capabilities = ", ".join(sorted(c.value for c in adapter.capabilities)) or "(none)"
        typer.echo(f"{adapter.name:<22}{adapter.family.value:<18}{capabilities}")


if __name__ == "__main__":  # pragma: no cover
    app()
