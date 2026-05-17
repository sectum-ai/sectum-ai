"""Entry point for the ``sectum`` command-line interface.

This is a Phase 0 skeleton. The full command set (init, seed, probe, report,
verify, erasure, baseline, adapters) is specified in the engineering spec, section 10 and
lands in Phase 3.
"""

from typing import Annotated

import typer

__version__ = "0.0.0"

app = typer.Typer(
    name="sectum",
    help="Sectum AI - multi-tenant AI verification.",
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Print the CLI version and exit when ``--version`` is passed."""
    if value:
        typer.echo(f"sectum {__version__}")
        raise typer.Exit


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
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
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


if __name__ == "__main__":  # pragma: no cover
    app()
