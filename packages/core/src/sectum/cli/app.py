"""Entry point for the ``sectum`` command-line interface (the engineering spec, section 10).

Implemented: ``--version``, ``adapters``, ``seed``, and ``probe``. The remaining
commands (init, report, verify, erasure, baseline) follow.
"""

from datetime import UTC, datetime
from pathlib import Path
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
from sectum.probes import (
    Probe,
    RagEntityBleedProbe,
    SemanticCacheProbe,
    TenantBoundaryProbe,
    confirmed_findings,
)
from sectum.runner import Runner, StepResult, retrieval_pivot_rate
from sectum.spec import Finding, RunMetrics, RunResult, Substrate, canonical_hash
from sectum.substrate import build_substrate, default_scenario

__version__ = "0.0.0"

_DEFAULT_WORKDIR = Path(".sectum")
_SUITE: tuple[Probe, ...] = (TenantBoundaryProbe(), RagEntityBleedProbe(), SemanticCacheProbe())

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
            help="Show the Sectum AI CLI version and exit.",
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


def _load_substrate(workdir: Path) -> Substrate:
    """Load the seeded substrate from ``workdir``, or exit with a config error."""
    path = workdir / "substrate.json"
    if not path.exists():
        typer.echo(f"no substrate at {path}; run 'sectum seed' first", err=True)
        raise typer.Exit(code=3)
    return Substrate.model_validate_json(path.read_text())


def _per_probe_counts(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.probe_id] = counts.get(finding.probe_id, 0) + 1
    return counts


@app.command()
def seed(
    scenario_seed: Annotated[int, typer.Option("--seed", help="Scenario seed.")] = 2026,
    workdir: Annotated[Path, typer.Option(help="Directory for run artifacts.")] = _DEFAULT_WORKDIR,
) -> None:
    """Provision synthetic tenants, generate corpora, and plant canary markers."""
    substrate = build_substrate(default_scenario(seed=scenario_seed))
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / "substrate.json"
    path.write_text(substrate.model_dump_json(indent=2))
    typer.echo(
        f"seeded {len(substrate.tenants)} tenants and "
        f"{len(substrate.documents)} documents -> {path}"
    )


@app.command()
def probe(
    workdir: Annotated[
        Path, typer.Option(help="Directory holding the seeded substrate.")
    ] = _DEFAULT_WORKDIR,
) -> None:
    """Run the probe suite against the seeded demo stack and record the findings."""
    substrate = _load_substrate(workdir)
    vector = FakeVectorStore(shared_index=True)
    cache = FakeCache(tenant_scoped=False)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        vector.upsert(tenant.tenant_id, documents)
    runner = Runner(substrate, vector=vector, cache=cache)

    started = datetime.now(UTC)
    step_results: list[StepResult] = []
    for probe_instance in _SUITE:
        step_results.extend(runner.run_per_step(probe_instance))
    finished = datetime.now(UTC)

    findings = tuple(finding for _, group in step_results for finding in group)
    confirmed = confirmed_findings(findings)
    bleed_steps = [
        result for result in step_results if result[0].probe_id == RagEntityBleedProbe.id
    ]
    run = RunResult(
        run_id=f"run-{substrate.scenario.scenario_id}",
        scenario_hash=canonical_hash(substrate.scenario),
        manifest_hash=canonical_hash(substrate.manifest),
        started_at=started,
        finished_at=finished,
        probe_versions={instance.id: __version__ for instance in _SUITE},
        findings=findings,
        metrics=RunMetrics(
            confirmed_findings=len(confirmed),
            retrieval_pivot_rate=retrieval_pivot_rate(bleed_steps),
            per_probe_findings=_per_probe_counts(confirmed),
        ),
    )
    path = workdir / "run.json"
    path.write_text(run.model_dump_json(indent=2))
    typer.echo(f"ran {len(_SUITE)} probes: {len(confirmed)} confirmed cross-tenant findings")
    if run.metrics.retrieval_pivot_rate is not None:
        typer.echo(f"retrieval-pivot rate: {run.metrics.retrieval_pivot_rate:.0%}")
    typer.echo(f"run recorded -> {path}")
    if confirmed:
        raise typer.Exit(code=2)


if __name__ == "__main__":  # pragma: no cover
    app()
