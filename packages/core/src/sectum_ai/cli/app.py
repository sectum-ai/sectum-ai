"""Entry point for the ``sectum-ai`` command-line interface (the engineering spec, section 10).

Implemented: ``--version``, ``adapters``, ``seed``, ``probe``, ``report``,
``verify``, ``erasure``, ``init``, ``baseline``, ``calibrate``, and ``diff``.
"""

import functools
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
import yaml
from pydantic import ValidationError

from sectum_ai.adapters import (
    AdapterRegistry,
    FakeAgent,
    FakeBackup,
    FakeCache,
    FakeEvalSet,
    FakeMCP,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeRAGPipeline,
    FakeSearchIndex,
    FakeVectorStore,
    VectorStoreAdapter,
)
from sectum_ai.adapters import (
    version as _adapters_version,
)
from sectum_ai.baseline import FindingChange, MetricDelta, RunDiff, diff_runs
from sectum_ai.config import (
    AdapterBundle,
    AdapterConfig,
    EmbedderConfig,
    EvidenceConfig,
    SectumConfig,
    SecurityConfig,
    build_adapters,
    build_cache,
    build_detection_providers,
    build_embedder,
    build_memory,
    build_model,
    build_observability,
    build_search_index,
    build_vector_store,
    embedder_model_name,
    load_config,
)
from sectum_ai.crypto import load_key_from_env, seal_bytes, unseal_bytes
from sectum_ai.embeddings import EmbeddingModel, resolve_embedding_model, validate_embedding_spec
from sectum_ai.evidence import (
    PdfEngine,
    RekorTransparencyLog,
    Rfc3161Timestamper,
    Timestamper,
    TransparencyLog,
    build_bundle,
    build_dsse_envelope,
    build_evidence_pack,
    control_mappings,
    rekor_keyring,
    render_audit_pack_and_hash,
    run_to_oscal,
    run_to_sarif,
    to_in_toto_statement,
    verify_bundle,
    verify_dsse_envelope,
    verify_in_toto_statement,
    verify_pack,
)
from sectum_ai.jobs import build_job_runner
from sectum_ai.probes import (
    ERASURE_SURFACES,
    SUBJECT_FINGERPRINT_SURFACES,
    SUBJECT_VERIFIABLE_SURFACES,
    AgentFrameworkHijackProbe,
    AgentToolHijackProbe,
    CalibrationResult,
    DetectionProviders,
    EmbeddingInversionProbe,
    EmbeddingProvider,
    ErasureProbe,
    ErasureReport,
    FakeEmbeddingProvider,
    IkeaExtractionProbe,
    KvCacheTimingProbe,
    LoraCrossTenantProbe,
    MemoryContamProbe,
    Probe,
    RagEntityBleedProbe,
    RagPipelineBleedProbe,
    RagPoisoningProbe,
    SemanticCacheProbe,
    SubjectErasureProbe,
    SubjectManifest,
    TenantBoundaryProbe,
    calibrate_threshold,
    confirmed_findings,
    dedupe_findings,
)
from sectum_ai.runner import (
    Runner,
    StepResult,
    confirmed_finding_rate,
    retrieval_pivot_counts,
)
from sectum_ai.spec import (
    ConfigError,
    EvidenceError,
    EvidencePack,
    Finding,
    MarkerType,
    RunMetrics,
    RunResult,
    SectumError,
    Substrate,
    Surface,
    canonical_hash,
    configure_logging,
    wilson_interval,
)
from sectum_ai.substrate import build_substrate, default_scenario
from sectum_ai.suites import SUITES
from sectum_ai.sweep import embedding_model_sweep, embedding_provider_sweep

# Source the version from the installed package metadata so every evidence pack
# and audit PDF attests the real shipped version (it is stamped into
# RunResult.adapter_versions / probe_versions). A hard-coded literal silently
# drifts from the release and corrupts the tamper-evident artifact.
try:
    __version__ = version("sectum-ai")
except PackageNotFoundError:  # running from an uninstalled / editable tree
    __version__ = "0.0.0+unknown"

# Adapters live in their own distribution (sectum-ai-adapters); stamp adapter
# entries with that distribution's version so the pack attests the version of the
# code that actually drove each surface, not the core CLI's.
_ADAPTERS_VERSION = _adapters_version()

_DEFAULT_WORKDIR = Path(".sectum-ai")
_DEFAULT_CONFIG = Path("sectum-ai.yaml")


class OutputFormat(StrEnum):
    """Output rendering for commands that report run-level results to stdout.

    `text` is the default human-readable rendering. `json` emits a single
    machine-parseable JSON object so CI pipelines and scripts can read the
    summary off stdout without scraping prose. `sarif` emits a SARIF 2.1.0 log of
    the findings so GitHub code scanning (and SAST dashboards) can ingest them.
    `oscal` emits a NIST OSCAL 1.1.x assessment-results document so GRC platforms
    and auditors can ingest the run as a machine-readable, control-mapped
    assessment. Error messages stay on stderr in every mode, and exit codes are
    unchanged.
    """

    TEXT = "text"
    JSON = "json"
    SARIF = "sarif"
    OSCAL = "oscal"


def _build_suite(providers: DetectionProviders) -> tuple[Probe, ...]:
    """Construct the probe suite, threading the configured detection providers."""
    return (
        TenantBoundaryProbe(providers),
        RagEntityBleedProbe(providers),
        RagPipelineBleedProbe(providers),
        SemanticCacheProbe(providers),
        LoraCrossTenantProbe(providers),
        AgentToolHijackProbe(providers),
        AgentFrameworkHijackProbe(providers),
        MemoryContamProbe(providers),
        EmbeddingInversionProbe(providers),
        IkeaExtractionProbe(providers),
        RagPoisoningProbe(providers),
    )


def _skip_inapplicable(
    suite: tuple[Probe, ...], bundle: AdapterBundle
) -> tuple[tuple[Probe, ...], list[tuple[str, str]]]:
    """Drop probes the configured stack cannot satisfy by adapter capability.

    A probe may list alternative capabilities in ``requires_any_capability`` - it
    applies if any adapter it drives reports at least one of them. The LoRA probe,
    for instance, needs a model that trains per-tenant adapters in either posture
    (``per_tenant_adapter`` or ``shared_weights``); a serving-only model (vLLM)
    reports neither, so the probe is skipped rather than run into a mid-probe
    adapter error. Returns the runnable probes and the ``(probe id, missing
    capabilities)`` pairs that were skipped.
    """
    runnable: list[Probe] = []
    skipped: list[tuple[str, str]] = []
    for probe in suite:
        required_any = getattr(probe, "requires_any_capability", ())
        present = [
            adapter
            for slot in probe.requires_adapters
            if (adapter := getattr(bundle, slot, None)) is not None
        ]
        satisfied = not required_any or any(
            adapter.supports(cap) for adapter in present for cap in required_any
        )
        if satisfied:
            runnable.append(probe)
        else:
            skipped.append((probe.id, " or ".join(cap.value for cap in required_any)))
    return tuple(runnable), skipped


# The CLI's default for `sectum-ai probe`: every fake's leak knob is on, so the
# probe suite reproduces the cross-tenant findings the probes are built to
# catch. Override by passing `--config sectum-ai.yaml`.
_DEMO_CONFIG = SectumConfig(
    adapters={
        "vector_store": AdapterConfig(kind="fake", shared_index=True),
        "cache": AdapterConfig(kind="fake", tenant_scoped=False),
        "model": AdapterConfig(kind="fake", adapter_bleed=True, prefix_cache=True),
        "mcp": AdapterConfig(kind="fake", confused_deputy=True, token_passthrough=True),
        "memory": AdapterConfig(kind="fake", shared_memory=True),
        "rag": AdapterConfig(kind="fake", shared_index=True),
        "observability": AdapterConfig(kind="fake"),
        "agent": AdapterConfig(kind="fake", confused_deputy=True, tool_call_passthrough=True),
    }
)

_CONFIG_TEMPLATE = """\
# Sectum AI configuration - see https://docs.sectum.ai
# Generated by `sectum-ai init`. Edit it to point Sectum AI at the stack to verify.

# How the synthetic tenants and their corpora are generated.
scenario:
  seed: 2026
  corpus_profile: demo

# Where run artifacts are written (substrate, run, evidence pack, audit pack).
workdir: .sectum-ai

# Adapters connecting Sectum AI to the stack under test. The defaults are the
# in-memory fakes with their leak knobs turned on - so `sectum-ai probe` reproduces
# the cross-tenant findings the probes are built to catch. Turn the knobs off
# (or point at a live backend) to verify a tenant-isolated stack. Never inline
# credentials - reference them from the environment.
adapters:
  vector_store:
    kind: fake  # fake|pgvector|chroma|weaviate|pinecone|qdrant|milvus|opensearch|azure-search
    shared_index: true       # demo leak: one index serves every tenant
    # dsn_env: SECTUM_PGVECTOR_DSN
  cache:
    kind: fake               # fake | redis
    tenant_scoped: false     # demo leak: a shared key space across tenants
  model:
    kind: fake               # fake | huggingface | vllm | tgi
    adapter_bleed: true      # demo leak: one tenant's adapter influences others
    prefix_cache: true       # demo leak: a shared KV prefix cache leaks via timing
    # vllm and tgi are serving-only (Class 5 KV-cache timing); Class 9 is skipped.
    # base_url: http://localhost:8000/v1   # vllm: OpenAI-compatible endpoint
    # model: meta-llama/Llama-3.1-8B-Instruct
    # base_url: http://localhost:8080      # tgi: server URL (one model per endpoint)
  mcp:
    kind: fake               # fake | stdio | http
    confused_deputy: true    # demo leak: the MCP server lost tenant scope
    token_passthrough: true  # demo leak: the server trusts a caller-supplied token
  memory:
    kind: fake
    shared_memory: true      # demo leak: long-term memory crosses tenants
  rag:
    kind: fake               # fake | http | langchain
    # url: http://localhost:8080/rag
  observability:
    kind: fake               # fake | phoenix | langfuse | langsmith | otel | helicone | datadog
    # base_url: http://localhost:6007  # compose.yaml publishes Phoenix on 6007
  agent:
    # kinds: fake | http | langgraph | autogen | crewai | openai-assistants | anthropic-tooluse
    kind: fake
    # url: http://localhost:8080/agent

# Evidence-chain anchoring. The local timestamper is the development default;
# production configures an RFC 3161 TSA and, optionally, a Sigstore Rekor log.
evidence:
  timestamper: local    # local | rfc3161
  # tsa_url: https://freetsa.org/tsr
  rekor: false          # true: also record the attested digest in a Sigstore Rekor log
  # rekor_url: https://rekor.sigstore.dev

# At-rest protection for the seeded substrate (which holds the ground-truth
# manifest). Set manifest_key_env to the name of an environment variable holding
# a base64-encoded 32-byte key; `sectum-ai seed` then seals the substrate on disk.
# Generate a key: python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
# security:
#   manifest_key_env: SECTUM_MANIFEST_KEY

# Detection-pipeline providers. The defaults are deterministic offline fakes.
# Configure a real embedding model and judge to run production detection; API
# keys are referenced from the environment, never inlined.
detection:
  embedder:
    kind: fake             # fake | openai
    # model: text-embedding-3-small
    # api_key_env: OPENAI_API_KEY
  judge:
    kind: fake             # fake | openai | anthropic
    # model: gpt-4o-mini
    # api_key_env: OPENAI_API_KEY
  # The semantic gate. A number is used as-is; "auto" resolves to the calibrated
  # per-model preset for the embedder above (run `sectum-ai calibrate` to derive
  # one for your model). Raise it once a real embedding model is configured.
  semantic_threshold: 0.62  # 0.62 | <float> | auto
  # Deployment mode. "local" is the BYOC "no data leaves the box" guarantee: it
  # fails fast if any embedder/judge above would call a hosted AI API (use `fake`,
  # or set a local `base_url`). "hosted" (default) places no egress restriction.
  mode: hosted             # hosted | local
"""

app = typer.Typer(
    name="sectum-ai",
    help="Sectum AI - multi-tenant AI verification.",
    no_args_is_help=True,
    add_completion=False,
)

# The Class-2 probes whose steps feed the headline Retrieval-Pivot Rate: the
# vector-store entity-bleed and the RAG-pipeline-end bleed. Counting only the
# former understates the rate when a leak manifests solely at the pipeline
# surface (it would read 0%).
BLEED_PROBE_IDS = frozenset({RagEntityBleedProbe.id, RagPipelineBleedProbe.id})


def _handle_typed_errors[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Translate a ``SectumError`` raised inside a command into the section-10 exit code.

    An ``EvidenceError`` exits with code 4 (evidence verification failure); any
    other ``SectumError`` exits with code 3 (config/adapter error). Other
    exceptions propagate unchanged.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except EvidenceError as error:
            typer.echo(f"{type(error).__name__}: {error}", err=True)
            raise typer.Exit(code=4) from error
        except SectumError as error:
            typer.echo(f"{type(error).__name__}: {error}", err=True)
            raise typer.Exit(code=3) from error

    return wrapper


def _version_callback(value: bool) -> None:
    """Print the CLI version and exit when ``--version`` is passed."""
    if value:
        typer.echo(f"sectum-ai {__version__}")
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
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Verbose DEBUG logging to stderr (may include raw content); off by default.",
            envvar="SECTUM_DEBUG",
        ),
    ] = False,
) -> None:
    """Sectum AI - multi-tenant AI verification."""
    # Structured JSON logging to stderr; stdout stays reserved for command output
    # (e.g. `probe --output json`). DEBUG is opt-in (the spec, section 16).
    configure_logging(debug=debug)


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
        FakeModel(),
        FakeMemory(),
        FakeSearchIndex(),
        FakeEvalSet(),
        FakeBackup(),
    ):
        registry.register(fake)
    typer.echo(f"{'ADAPTER':<22}{'FAMILY':<18}CAPABILITIES")
    for adapter in registry.all():
        capabilities = ", ".join(sorted(c.value for c in adapter.capabilities)) or "(none)"
        typer.echo(f"{adapter.name:<22}{adapter.family.value:<18}{capabilities}")


def _resolve_manifest_key(security: SecurityConfig) -> bytes | None:
    """Return the configured at-rest key, or ``None`` when encryption is off."""
    if security.manifest_key_env is None:
        return None
    return load_key_from_env(security.manifest_key_env)


def _write_substrate(substrate: Substrate, workdir: Path, key: bytes | None) -> Path:
    """Persist the substrate to ``workdir``, sealed when a key is given.

    Removes the other variant so a re-seed never leaves a stale copy behind - in
    particular, a plaintext substrate must not survive once a sealed one is
    written, or the at-rest protection would be silently defeated.
    """
    payload = substrate.model_dump_json(indent=2).encode("utf-8")
    sealed_path = workdir / "substrate.json.enc"
    plain_path = workdir / "substrate.json"
    if key is not None:
        sealed_path.write_bytes(seal_bytes(payload, key))
        plain_path.unlink(missing_ok=True)
        return sealed_path
    plain_path.write_bytes(payload)
    sealed_path.unlink(missing_ok=True)
    return plain_path


def _load_substrate(workdir: Path, key: bytes | None = None) -> Substrate:
    """Load the seeded substrate from ``workdir``, or exit with a config error.

    A sealed substrate (``substrate.json.enc``) requires the matching key; a
    plaintext ``substrate.json`` is loaded directly.
    """
    sealed = workdir / "substrate.json.enc"
    plain = workdir / "substrate.json"
    if sealed.exists():
        if key is None:
            typer.echo(
                f"the substrate at {sealed} is encrypted; set security.manifest_key_env",
                err=True,
            )
            raise typer.Exit(code=3)
        try:
            return Substrate.model_validate_json(unseal_bytes(sealed.read_bytes(), key))
        except ValueError as error:
            typer.echo(f"the substrate at {sealed} is malformed: {error}", err=True)
            raise typer.Exit(code=3) from error
    if plain.exists():
        try:
            return Substrate.model_validate_json(plain.read_text())
        except ValueError as error:
            typer.echo(f"the substrate at {plain} is malformed: {error}", err=True)
            raise typer.Exit(code=3) from error
    typer.echo(f"no substrate at {plain}; run 'sectum-ai seed' first", err=True)
    raise typer.Exit(code=3)


def _load_run(workdir: Path) -> RunResult:
    """Load the recorded run from ``workdir``, or exit with a config error."""
    path = workdir / "run.json"
    if not path.exists():
        typer.echo(f"no run at {path}; run 'sectum-ai probe' first", err=True)
        raise typer.Exit(code=3)
    try:
        return RunResult.model_validate_json(path.read_text())
    except ValueError as error:
        typer.echo(f"the run at {path} is malformed: {error}", err=True)
        raise typer.Exit(code=3) from error


def _per_probe_counts(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.probe_id] = counts.get(finding.probe_id, 0) + 1
    return counts


def _per_model_rpr(substrate: Substrate, vector: VectorStoreAdapter) -> dict[str, float]:
    """Per-embedding-model Retrieval-Pivot Rate for the run, or ``{}`` if not applicable.

    Needs two or more configured embedding models to be a comparison. Names that
    resolve to *real* providers (``st:``/``openai:``/``hash-``) run the genuine
    cosine sweep, which reflects the real embedding-strength gradient and is
    therefore recorded for any vector store - this is what makes the "stronger
    embeddings leak more" effect visible on a live stack. Legacy ``fake-*`` names
    fall back to the deterministic recall illustration, which is meaningful only
    for the in-memory ``FakeVectorStore`` and so is omitted from a live run's
    evidence.
    """
    names = substrate.scenario.embedding_models
    if len(names) <= 1:
        return {}
    real = [model for name in names if (model := resolve_embedding_model(name)) is not None]
    if real:
        return embedding_provider_sweep(substrate, real)
    if isinstance(vector, FakeVectorStore):
        return embedding_model_sweep(substrate, names)
    return {}


def _format_rpr(metrics: RunMetrics) -> str:
    """Render the Retrieval-Pivot Rate with its Wilson interval and sample size.

    Shows the point estimate, the 95% confidence interval, and ``n`` - for
    example ``95.4% (95% CI 92.1-97.3%, n=350)`` - so the headline rate is never
    presented as a precise number without its uncertainty (the spec's "avoid
    over-claiming"). Falls back to a bare percentage if the interval is absent
    (an older record), so the line is always safe to print.

    Args:
        metrics: The run metrics; the caller has checked the rate is not ``None``.

    Returns:
        The formatted rate string.
    """
    assert metrics.retrieval_pivot_rate is not None
    rate = f"{metrics.retrieval_pivot_rate:.1%}"
    if metrics.retrieval_pivot_rate_ci is None:
        return rate
    low, high = metrics.retrieval_pivot_rate_ci
    return f"{rate} (95% CI {low:.1%}-{high:.1%}, n={metrics.retrieval_pivot_n})"


def _resolve_target(substrate: Substrate, name: str | None) -> UUID:
    """Resolve a target tenant by display name, defaulting to the first tenant."""
    if name is None:
        return substrate.tenants[0].tenant_id
    for tenant in substrate.tenants:
        if tenant.display_name.lower() == name.lower():
            return tenant.tenant_id
    available = ", ".join(tenant.display_name for tenant in substrate.tenants)
    typer.echo(f"unknown tenant '{name}'; available: {available}", err=True)
    raise typer.Exit(code=3)


def _resolve_erasure_scope(scope: str | None) -> tuple[Surface, ...] | None:
    """Parse and validate a ``--scope`` surface list for the erasure command.

    ``scope`` is a comma-separated list of erasure-surface names (for example
    ``vector_db,tracing``). Returns the surfaces in canonical
    :data:`~sectum_ai.probes.ERASURE_SURFACES` order, or ``None`` when no scope
    was given (the full run). Every name must be a known erasure surface;
    an unknown name raises :class:`~sectum_ai.spec.ConfigError` (exit 3) with the
    valid set, so an engagement cannot silently scope to nothing.
    """
    if scope is None:
        return None
    requested = [name.strip() for name in scope.split(",") if name.strip()]
    if not requested:
        valid = ", ".join(surface.value for surface in ERASURE_SURFACES)
        raise ConfigError(f"--scope is empty; name one or more erasure surfaces: {valid}")
    known = {surface.value: surface for surface in ERASURE_SURFACES}
    selected: set[Surface] = set()
    unknown: list[str] = []
    for name in requested:
        surface = known.get(name)
        if surface is None:
            unknown.append(name)
        else:
            selected.add(surface)
    if unknown:
        valid = ", ".join(surface.value for surface in ERASURE_SURFACES)
        raise ConfigError(
            f"unknown erasure surface(s) in --scope: {', '.join(unknown)}; "
            f"valid surfaces are: {valid}"
        )
    # Return in canonical order so the scoped run's output and coverage block read
    # in the same stable sequence as a full run.
    return tuple(surface for surface in ERASURE_SURFACES if surface in selected)


@app.command()
@_handle_typed_errors
def seed(
    scenario_seed: Annotated[int | None, typer.Option("--seed", help="Scenario seed.")] = None,
    workdir: Annotated[Path | None, typer.Option(help="Directory for run artifacts.")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Read defaults from this sectum-ai.yaml file."),
    ] = None,
    embedding_model: Annotated[
        list[str] | None,
        typer.Option(
            "--embedding-model",
            help=(
                "Embedding model for the Class 2 per-model sweep; repeat for two or "
                "more to record a per-model Retrieval-Pivot Rate. Overrides the config. "
                "Forms: fake-<name>, hash-<dim>, st:<model>, openai:<model>."
            ),
        ),
    ] = None,
) -> None:
    """Provision synthetic tenants, generate corpora, and plant canary markers."""
    loaded = load_config(config) if config is not None else SectumConfig()
    effective_seed = scenario_seed if scenario_seed is not None else loaded.scenario.seed
    effective_workdir = workdir if workdir is not None else loaded.workdir
    if embedding_model:
        for spec in embedding_model:
            validate_embedding_spec(spec)  # ConfigError -> exit 3
        embedding_models = tuple(embedding_model)
    else:
        embedding_models = loaded.scenario.embedding_models
    substrate = build_substrate(
        default_scenario(
            seed=effective_seed,
            corpus_size=loaded.scenario.corpus_size,
            embedding_models=embedding_models,
        )
    )
    effective_workdir.mkdir(parents=True, exist_ok=True)
    path = _write_substrate(substrate, effective_workdir, _resolve_manifest_key(loaded.security))
    typer.echo(
        f"seeded {len(substrate.tenants)} tenants and "
        f"{len(substrate.documents)} documents -> {path}"
    )


@app.command()
@_handle_typed_errors
def probe(
    workdir: Annotated[
        Path | None, typer.Option(help="Directory holding the seeded substrate.")
    ] = None,
    only: Annotated[
        str | None, typer.Option("--probe", help="Run only the probe with this id.")
    ] = None,
    suite_name: Annotated[
        str | None,
        typer.Option("--suite", help="Run a named, control-mapped probe suite (see docs/skus.md)."),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Read adapters and workdir from this sectum-ai.yaml file."),
    ] = None,
    max_concurrency: Annotated[
        int,
        typer.Option(
            "--max-concurrency",
            help=(
                "Run probes in parallel via a thread pool (1 = serial). N > 1 requires "
                "thread-safe adapters AND that probe order does not matter; the demo's "
                "in-memory fakes share state across mutating and reading probes, so "
                "concurrent execution there yields nondeterministic findings."
            ),
        ),
    ] = 1,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            help=(
                "Render the run summary on stdout. `text` is human-readable (default); "
                "`json` emits a machine-parseable object for CI pipelines; `sarif` a "
                "SARIF 2.1.0 log for code scanning; `oscal` a NIST OSCAL 1.1.x "
                "assessment-results document for GRC platforms and auditors."
            ),
            case_sensitive=False,
        ),
    ] = OutputFormat.TEXT,
) -> None:
    """Run the probe suite against the configured stack and record the findings."""
    if max_concurrency < 1:
        raise ConfigError("--max-concurrency must be at least 1")
    loaded = load_config(config) if config is not None else _DEMO_CONFIG
    effective_workdir = workdir if workdir is not None else loaded.workdir
    substrate = _load_substrate(effective_workdir, _resolve_manifest_key(loaded.security))
    suite = _build_suite(build_detection_providers(loaded.detection))
    run_kv_timing = True
    if only is not None and suite_name is not None:
        typer.echo("pass at most one of --probe and --suite", err=True)
        raise typer.Exit(code=3)
    if suite_name is not None:
        spec = SUITES.get(suite_name)
        if spec is None:
            typer.echo(
                f"unknown suite '{suite_name}'; available: {', '.join(sorted(SUITES))}", err=True
            )
            raise typer.Exit(code=3)
        suite = tuple(instance for instance in suite if instance.id in spec.probe_ids)
        run_kv_timing = spec.include_kv_timing
        typer.echo(f"suite {spec.name}: {', '.join(spec.frameworks)}", err=True)
    if only is not None:
        available = [instance.id for instance in suite] + [KvCacheTimingProbe.id]
        if only not in available:
            typer.echo(f"unknown probe '{only}'; available: {', '.join(available)}", err=True)
            raise typer.Exit(code=3)
        suite = tuple(instance for instance in suite if instance.id == only)
        run_kv_timing = only == KvCacheTimingProbe.id
    bundle = build_adapters(loaded)
    suite, skipped_probes = _skip_inapplicable(suite, bundle)
    for skipped_id, missing_cap in skipped_probes:
        typer.echo(
            f"skipping {skipped_id}: no configured adapter provides '{missing_cap}' "
            "(e.g. a serving-only model trains no per-tenant adapter)",
            err=True,
        )
    vector = bundle.vector
    cache = bundle.cache
    model = bundle.model
    mcp = bundle.mcp
    memory = bundle.memory
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        vector.upsert(tenant.tenant_id, documents)
    if isinstance(mcp, FakeMCP):
        for marker in substrate.manifest.markers:
            if marker.marker_type is MarkerType.HARD_CANARY:
                mcp.provision(
                    marker.owner_tenant_id,
                    marker.marker_id,
                    f"MCP resource. Reference: {marker.plaintext}",
                )
    if isinstance(bundle.agent, FakeAgent):
        for marker in substrate.manifest.markers:
            if marker.marker_type is MarkerType.HARD_CANARY:
                bundle.agent.provision(
                    marker.owner_tenant_id,
                    marker.marker_id,
                    f"agent tool returned. Reference: {marker.plaintext}",
                )
    if isinstance(bundle.rag, FakeRAGPipeline):
        for tenant in substrate.tenants:
            documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
            bundle.rag.index(tenant.tenant_id, documents)
    runner = Runner(
        substrate,
        vector=vector,
        cache=cache,
        model=model,
        mcp=mcp,
        memory=memory,
        rag=bundle.rag,
        observability=bundle.observability,
        agent=bundle.agent,
    )

    started = datetime.now(UTC)
    step_results: list[StepResult] = []
    # A single probe stays serial regardless of --max-concurrency (a pool is only
    # worth its overhead for a suite > 1). The JobRunner is the seam where a
    # distributed orchestrator could later replace local threads (spec section 21).
    job_runner = build_job_runner(max_concurrency if len(suite) > 1 else 1)
    for group in job_runner.map(runner.run_per_step, suite):
        step_results.extend(group)
    # Build a FRESH model adapter for the KV-timing probe rather than reusing the
    # suite's `model`: the Class 9 LoRA probe trains/mutates that shared instance,
    # and a contaminated adapter state would confound the prefix-cache timing. A
    # fresh instance also gives the probe the cold cache its measurement warms.
    kv_report = None
    if run_kv_timing:
        kv_model = build_model(loaded.adapters.get("model", AdapterConfig(kind="fake")))
        kv_report = KvCacheTimingProbe(substrate, model=kv_model).run()
    finished = datetime.now(UTC)

    suite_findings = [finding for _, group in step_results for finding in group]
    kv_findings = list(kv_report.findings) if kv_report is not None else []
    findings = tuple(dedupe_findings([*suite_findings, *kv_findings]))
    confirmed = confirmed_findings(findings)
    bleed_steps = [result for result in step_results if result[0].probe_id in BLEED_PROBE_IDS]
    # The Retrieval-Pivot Rate is a binomial proportion (k of n benign cross-tenant
    # query steps surfaced a foreign canary). Record k and n so the rate's Wilson
    # confidence interval is reproducible from the signed evidence, and compute the
    # interval here so the headline rate is never shown without its uncertainty.
    rpr_k, rpr_n = retrieval_pivot_counts(bleed_steps)
    rpr_rate = rpr_k / rpr_n if rpr_n else None
    rpr_ci = wilson_interval(rpr_k, rpr_n) if rpr_n else None
    # Class 3/6/10 headline rates over each probe's benign query steps. Poisoning
    # excludes its own vector.upsert (plant) steps, which never produce findings.
    poison_query_steps = [
        result
        for result in step_results
        if result[0].probe_id == RagPoisoningProbe.id and result[0].action == "vector.query"
    ]
    inversion_steps = [
        result for result in step_results if result[0].probe_id == EmbeddingInversionProbe.id
    ]
    extraction_steps = [
        result for result in step_results if result[0].probe_id == IkeaExtractionProbe.id
    ]
    run = RunResult(
        run_id=f"run-{substrate.scenario.scenario_id}",
        scenario_hash=canonical_hash(substrate.scenario),
        manifest_hash=canonical_hash(substrate.manifest),
        started_at=started,
        finished_at=finished,
        adapter_versions={
            vector.name: _ADAPTERS_VERSION,
            cache.name: _ADAPTERS_VERSION,
            model.name: _ADAPTERS_VERSION,
            mcp.name: _ADAPTERS_VERSION,
            memory.name: _ADAPTERS_VERSION,
            bundle.rag.name: _ADAPTERS_VERSION,
            bundle.observability.name: _ADAPTERS_VERSION,
            bundle.agent.name: _ADAPTERS_VERSION,
        },
        probe_versions={
            **{instance.id: __version__ for instance in suite},
            **({KvCacheTimingProbe.id: __version__} if run_kv_timing else {}),
        },
        findings=findings,
        metrics=RunMetrics(
            confirmed_findings=len(confirmed),
            retrieval_pivot_rate=rpr_rate,
            retrieval_pivot_n=rpr_n,
            retrieval_pivot_k=rpr_k,
            retrieval_pivot_rate_ci=rpr_ci,
            # Real embedding providers (st:/openai:/hash-) record a genuine
            # per-model gradient for any stack; legacy fake names fall back to the
            # in-memory recall illustration. See _per_model_rpr.
            retrieval_pivot_rate_by_model=_per_model_rpr(substrate, vector),
            per_probe_findings=_per_probe_counts(confirmed),
            side_channel_effect_sizes=kv_report.effect_sizes if kv_report is not None else {},
            poisoning_bleed_delta=(
                confirmed_finding_rate(poison_query_steps) if poison_query_steps else None
            ),
            inversion_reconstruction_rate=(
                confirmed_finding_rate(inversion_steps) if inversion_steps else None
            ),
            extraction_efficiency=(
                confirmed_finding_rate(extraction_steps) if extraction_steps else None
            ),
        ),
    )
    path = effective_workdir / "run.json"
    path.write_text(run.model_dump_json(indent=2))
    probe_count = len(suite) + (1 if run_kv_timing else 0)
    if output is OutputFormat.JSON:
        # Single-shot JSON object so the consumer can `jq .` it. The full run
        # is still on disk at `run_path`; this is the summary CI dashboards read.
        summary = {
            "run_id": run.run_id,
            "probe_count": probe_count,
            "confirmed_findings": len(confirmed),
            "retrieval_pivot_rate": run.metrics.retrieval_pivot_rate,
            # The binomial counts and Wilson 95% CI travel with the rate so a CI
            # dashboard can show the rate's uncertainty, not a bare point estimate.
            "retrieval_pivot_n": run.metrics.retrieval_pivot_n,
            "retrieval_pivot_k": run.metrics.retrieval_pivot_k,
            "retrieval_pivot_rate_ci": (
                list(run.metrics.retrieval_pivot_rate_ci)
                if run.metrics.retrieval_pivot_rate_ci is not None
                else None
            ),
            "retrieval_pivot_rate_by_model": run.metrics.retrieval_pivot_rate_by_model,
            "poisoning_bleed_delta": run.metrics.poisoning_bleed_delta,
            "inversion_reconstruction_rate": run.metrics.inversion_reconstruction_rate,
            "extraction_efficiency": run.metrics.extraction_efficiency,
            "per_probe_findings": run.metrics.per_probe_findings,
            "run_path": str(path),
        }
        typer.echo(json.dumps(summary, indent=2))
    elif output is OutputFormat.SARIF:
        # SARIF 2.1.0 log of the findings for GitHub code scanning / SAST
        # dashboards; the signed evidence.json on disk stays the canonical record.
        typer.echo(json.dumps(run_to_sarif(run, tool_version=__version__), indent=2))
    elif output is OutputFormat.OSCAL:
        # NIST OSCAL 1.1.x assessment-results for GRC platforms / auditors: one
        # observation per finding, one finding per mapped control. Derived and
        # unsigned; the signed evidence.json on disk stays the canonical record.
        typer.echo(json.dumps(run_to_oscal(run, tool_version=__version__), indent=2))
    else:
        plural = "" if probe_count == 1 else "s"
        typer.echo(
            f"ran {probe_count} probe{plural}: {len(confirmed)} confirmed cross-tenant findings"
        )
        if run.metrics.retrieval_pivot_rate is not None:
            typer.echo(f"retrieval-pivot rate: {_format_rpr(run.metrics)}")
        for model_name, rate in run.metrics.retrieval_pivot_rate_by_model.items():
            typer.echo(f"  retrieval-pivot rate [{model_name}]: {rate:.0%}")
        for label, class_rate in (
            ("poisoning bleed delta", run.metrics.poisoning_bleed_delta),
            ("inversion reconstruction rate", run.metrics.inversion_reconstruction_rate),
            ("extraction efficiency", run.metrics.extraction_efficiency),
        ):
            if class_rate is not None:
                typer.echo(f"{label}: {class_rate:.0%}")
        typer.echo(f"run recorded -> {path}")
    if confirmed:
        raise typer.Exit(code=2)


def _resolve_timestamper(evidence: EvidenceConfig, tsa_override: str | None) -> Timestamper | None:
    """Resolve the configured timestamper, or ``None`` to use the local default.

    A ``--tsa <url>`` override forces an RFC 3161 TSA; otherwise the
    ``evidence.timestamper`` setting selects ``local`` (default) or ``rfc3161``.
    """
    if tsa_override is not None:
        return Rfc3161Timestamper(tsa_override)
    if evidence.timestamper == "rfc3161":
        url = evidence.tsa_url
        return Rfc3161Timestamper(url) if url is not None else Rfc3161Timestamper()
    return None


def _resolve_transparency_log(evidence: EvidenceConfig, rekor_flag: bool) -> TransparencyLog | None:
    """Resolve a Rekor transparency log when enabled by ``--rekor`` or the config.

    Recording uses an ephemeral signing key; the transparency guarantee is the
    public, timestamped inclusion of the digest, not the signer's identity.
    """
    if not (rekor_flag or evidence.rekor):
        return None
    url = evidence.rekor_url
    return RekorTransparencyLog(rekor_url=url) if url is not None else RekorTransparencyLog()


def _rekor_keyring_override(rekor_key: Path | None) -> dict[str, bytes] | None:
    """Build a one-key Rekor keyring from a ``--rekor-key`` PEM file, or ``None``."""
    if rekor_key is None:
        return None
    return rekor_keyring(rekor_key.read_bytes())


@app.command()
@_handle_typed_errors
def report(
    workdir: Annotated[
        Path | None, typer.Option(help="Directory holding the substrate and run.")
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Read defaults from this sectum-ai.yaml file."),
    ] = None,
    tsa: Annotated[
        str | None,
        typer.Option("--tsa", help="RFC 3161 TSA URL; switches the timestamper to a trusted TSA."),
    ] = None,
    rekor: Annotated[
        bool,
        typer.Option("--rekor", help="Also record the attested digest in a Sigstore Rekor log."),
    ] = False,
    pdf_engine: Annotated[
        PdfEngine,
        typer.Option(
            "--pdf-engine",
            help=(
                "Audit-pack PDF renderer. 'reportlab' (default) is pure Python; "
                "'weasyprint' is an HTML/CSS-templated alternative and needs the "
                "weasyprint extra (pip install 'sectum-ai[weasyprint]')."
            ),
            case_sensitive=False,
        ),
    ] = PdfEngine.REPORTLAB,
    bundle: Annotated[
        bool,
        typer.Option(
            "--bundle",
            help="Also write a single verifiable evidence-bundle.zip (the spec, section 8.2).",
        ),
    ] = False,
    include_manifest: Annotated[
        bool,
        typer.Option(
            "--include-manifest",
            help=(
                "Include the ground-truth manifest in the bundle, sealed AES-256-GCM "
                "under the configured security.manifest_key_env. Off by default - the "
                "manifest holds canary plaintexts."
            ),
        ),
    ] = False,
) -> None:
    """Assemble a tamper-evident evidence pack (JSON and PDF) from the run."""
    loaded = load_config(config) if config is not None else SectumConfig()
    if workdir is None:
        workdir = loaded.workdir
    substrate = _load_substrate(workdir, _resolve_manifest_key(loaded.security))
    run = _load_run(workdir)
    timestamper = _resolve_timestamper(loaded.evidence, tsa)
    transparency_log = _resolve_transparency_log(loaded.evidence, rekor)
    controls = control_mappings()
    # Render the audit PDF first and bind its hash as pdf_ref so the signed
    # attested digest covers the PDF; the PDF renders only digest-stable content,
    # so the on-disk file re-hashes to this pdf_ref and `sectum-ai verify` catches a
    # swap.
    pdf_path = workdir / "audit-pack.pdf"
    pdf_ref = render_audit_pack_and_hash(
        run, canonical_hash(substrate.manifest), controls, pdf_path, engine=pdf_engine
    )
    pack = build_evidence_pack(
        run,
        substrate.manifest,
        control_mappings=controls,
        pdf_ref=pdf_ref,
        timestamper=timestamper,
        transparency_log=transparency_log,
    )
    json_path = workdir / "evidence.json"
    json_path.write_text(pack.model_dump_json(indent=2))
    intoto_path = workdir / "attestation.intoto.json"
    intoto_path.write_text(json.dumps(to_in_toto_statement(pack), indent=2))
    # The DSSE envelope is the standard signable carrier of the in-toto statement
    # (the body of a Sigstore Rekor `dsse` entry); written unconditionally beside
    # the pack so it can be signed/distributed (the spec, sections 8 and 13).
    dsse_path = workdir / "evidence.dsse.json"
    dsse_path.write_text(json.dumps(build_dsse_envelope(pack), indent=2))
    typer.echo(f"evidence pack -> {json_path}")
    typer.echo(f"audit pack -> {pdf_path}")
    if bundle:
        members = {
            "evidence.json": json_path.read_bytes(),
            "audit-pack.pdf": pdf_path.read_bytes(),
            "attestation.intoto.json": intoto_path.read_bytes(),
            "evidence.dsse.json": dsse_path.read_bytes(),
        }
        if include_manifest:
            # The manifest holds canary plaintexts, so it is sealed AES-256-GCM
            # before it enters the bundle; the bundler itself stays crypto-agnostic.
            key_env = loaded.security.manifest_key_env
            if key_env is None:
                raise ConfigError(
                    "--include-manifest needs security.manifest_key_env set to seal the manifest"
                )
            sealed = seal_bytes(
                substrate.manifest.model_dump_json().encode("utf-8"), load_key_from_env(key_env)
            )
            members["ground-truth-manifest.json.aes"] = sealed
        bundle_path = workdir / "evidence-bundle.zip"
        bundle_path.write_bytes(build_bundle(members))
        typer.echo(f"evidence bundle -> {bundle_path}")
    typer.echo(f"in-toto attestation -> {intoto_path}")
    typer.echo(f"dsse envelope -> {dsse_path}")


# A config key names a secret when one of these words appears with a trailing
# word boundary (end / ``_`` / ``-`` / non-alphanumeric): ``api_key``,
# ``secret_key``, ``db_dsn`` and a bare ``token`` match, but ``max_tokens``,
# ``tokenizer`` and ``public_key`` do NOT (the trailing-boundary stops ``token``
# from matching inside ``tokens``). ``*_env`` keys name an environment variable,
# not the secret, and are kept (handled by the caller).
_CONFIG_SECRET_KEY_RE = re.compile(
    r"(?:api_?key|dsn|password|passphrase|token|secret|credential|application_key)"
    r"(?![A-Za-z0-9])"
)

# Value-shape backstop: an inline secret can hide under a benign key name - in a
# header value (`Authorization: Bearer ...`), embedded in a URL
# (`scheme://user:pass@host`), or as a CLI token in `args`. These shapes are
# scrubbed wherever they appear, regardless of the key, so key-name redaction
# alone cannot be bypassed. A `headers` map is redacted wholesale because any
# header value may be an opaque token with no recognisable shape.
# Each alternative is a single linear run (no overlapping/adjacent quantifiers),
# so there is no super-linear backtracking.
_CONFIG_SECRET_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9][A-Za-z0-9_-]{14,}"  # OpenAI-style API key
    r"|(?<![A-Za-z0-9])AKIA[A-Z0-9]{16}"  # AWS access-key id
    r"|(?<![A-Za-z0-9])gh[a-z]_[A-Za-z0-9]{20,}"  # GitHub token (ghp_/gho_/ghs_/ghu_/ghr_)
    r"|(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{20,}"  # GitHub fine-grained PAT
    r"|(?<![A-Za-z0-9])glpat-[A-Za-z0-9_-]{18,}"  # GitLab PAT
    r"|(?<![A-Za-z0-9])xox[baprs]-[A-Za-z0-9-]{10,}"  # Slack token
    r"|(?<![A-Za-z0-9])hf_[A-Za-z0-9]{20,}"  # Hugging Face token
    r"|(?<![A-Za-z0-9])AIza[A-Za-z0-9_-]{16,}"  # Google API key
    r"|SECTUM-CANARY-[A-Z2-7]+"  # Sectum canary plaintext
    r"|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{8,}"  # bearer token (any case)
)
# Embedded URL credentials: the whole userinfo (`user:pass@`, `:pass@`, `token@`)
# and any query-parameter value (a base_url can carry `?api-key=...`). The
# userinfo class allows `@` so a malformed mid-password `@` still redacts the
# whole userinfo up to the last `@` before the path. Single-run classes bounded
# by literals -> linear.
_URL_USERINFO_RE = re.compile(r"://[^\s/]+@")
_URL_QUERY_VALUE_RE = re.compile(r"([?&][^=&\s]+=)[^&\s]+")


def _scrub_config_secret_value(text: str) -> str:
    """Redact credential-shaped substrings and embedded URL credentials in a value,
    so a secret survives neither under a benign key, inside a URL's userinfo, nor in
    a URL query parameter."""
    scrubbed = _URL_USERINFO_RE.sub("://<redacted>@", text)
    scrubbed = _URL_QUERY_VALUE_RE.sub(r"\1<redacted>", scrubbed)
    return _CONFIG_SECRET_VALUE_RE.sub("<redacted>", scrubbed)


def _redact_config_value(value: object) -> object:
    """Recursively redact inline secrets in a parsed config.

    A key naming a secret (a ``_CONFIG_SECRET_KEY_RE`` match, not ending in
    ``_env``) has its value replaced with ``<redacted>``; a ``headers`` map is
    redacted wholesale; and every string is scrubbed for credential shapes and
    embedded URL credentials (`_scrub_config_secret_value`). ``*_env`` references
    and benign values are otherwise preserved, so the packed config keeps its
    reproducible shape without carrying a raw credential.
    """
    if isinstance(value, dict):
        redacted: dict[object, object] = {}
        for key, val in value.items():
            name = str(key).lower()
            is_secret_key = (
                not name.endswith("_env") and _CONFIG_SECRET_KEY_RE.search(name) is not None
            )
            # A `headers` map is redacted wholesale: any value may be an opaque token.
            is_headers = name == "headers" or name.endswith("_headers")
            if is_secret_key or is_headers:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_config_value(val)
        return redacted
    if isinstance(value, list):
        return [_redact_config_value(item) for item in value]
    if isinstance(value, str):
        return _scrub_config_secret_value(value)
    return value


def _redact_config_text(text: str) -> str:
    """Return the config YAML with inline secret values redacted.

    Comments are not preserved - the packed config is a record, not the editable
    source. A config that uses the ``*_env`` convention is unchanged.
    """
    import yaml

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return "# config omitted: not valid YAML\n"
    if not isinstance(data, dict | list):
        # A scalar-only config is not a real sectum-ai mapping, but still scrub it
        # for credential shapes rather than echoing it back verbatim.
        return _scrub_config_secret_value(text)
    dumped = yaml.safe_dump(_redact_config_value(data), sort_keys=False, default_flow_style=False)
    return str(dumped)


def _run_pack_readme(run_id: str, *, sealed_manifest: bool, has_config: bool) -> str:
    """The human-readable, secret-free README placed at the top of a run pack."""
    config_line = (
        "- `sectum-ai.config.redacted.yaml` - the configuration used, inline secrets redacted\n"
        if has_config
        else "- (no config file - the run used the built-in defaults)\n"
    )
    manifest_line = (
        "- `ground-truth-manifest.json.aes` - the marker manifest, sealed AES-256-GCM\n"
        if sealed_manifest
        else ""
    )
    return (
        f"# Sectum AI run pack - {run_id}\n\n"
        "**SENSITIVE - do not post publicly.** This is a complete, reproducible record of a\n"
        "Sectum AI verification run. It carries the run details (`run.json`, including\n"
        "evidence spans) and the ground-truth marker manifest - material Sectum normally\n"
        "redacts. Share it only with trusted parties (for example, your auditor under NDA).\n\n"
        "## Verify\n\n"
        "```sh\n"
        "sectum-ai verify run-pack.zip\n"
        "```\n\n"
        "A pack built with `report --tsa --rekor` verifies as independently anchored tamper\n"
        "evidence; otherwise add `--allow-unanchored` (the local-dev timestamp is\n"
        "regenerable, so it is an integrity-only check).\n\n"
        "## Contents\n\n"
        "- `evidence.json` - the signed, tamper-evident evidence pack (the canonical record)\n"
        "- `audit-pack.pdf` - the human-readable audit pack\n"
        "- `attestation.intoto.json`, `evidence.dsse.json` - the attestation sidecars\n"
        "- `run.json` - the full run record (findings + evidence spans) - SENSITIVE\n"
        f"{config_line}"
        f"{manifest_line}"
        "- `bundle-manifest.json` - the SHA-256 of every member\n"
    )


@app.command()
@_handle_typed_errors
def pack(
    workdir: Annotated[
        Path | None,
        typer.Option(help="Directory holding the substrate, run, and evidence pack."),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config", help="The sectum-ai.yaml used; bundled with inline secrets redacted."
        ),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Where to write the pack (default: <workdir>/run-pack.zip)."),
    ] = None,
    include_manifest: Annotated[
        bool,
        typer.Option(
            "--include-manifest",
            help=(
                "Include the ground-truth manifest, sealed AES-256-GCM under "
                "security.manifest_key_env. The manifest holds canary plaintexts."
            ),
        ),
    ] = False,
) -> None:
    """Assemble a single, portable run-pack.zip - the evidence pack plus the run
    record and (redacted) config - for reproducing or auditing a run.

    SENSITIVE: a run pack carries the run details and ground-truth markers that
    Sectum normally redacts, so share it only with trusted parties. Requires a
    prior ``sectum-ai report`` (the evidence pack and sidecars). Verify it with
    ``sectum-ai verify run-pack.zip``.
    """
    loaded = load_config(config) if config is not None else SectumConfig()
    if workdir is None:
        workdir = loaded.workdir
    evidence_path = workdir / "evidence.json"
    if not evidence_path.exists():
        raise ConfigError(f"no evidence pack at {evidence_path}; run 'sectum-ai report' first")
    run = _load_run(workdir)

    members: dict[str, bytes] = {"evidence.json": evidence_path.read_bytes()}
    for name in ("audit-pack.pdf", "attestation.intoto.json", "evidence.dsse.json", "run.json"):
        sibling = workdir / name
        if sibling.exists():
            members[name] = sibling.read_bytes()
    if config is not None:
        members["sectum-ai.config.redacted.yaml"] = _redact_config_text(
            Path(config).read_text(encoding="utf-8")
        ).encode("utf-8")
    if include_manifest:
        key_env = loaded.security.manifest_key_env
        if key_env is None:
            raise ConfigError(
                "--include-manifest needs security.manifest_key_env set to seal the manifest"
            )
        substrate = _load_substrate(workdir, _resolve_manifest_key(loaded.security))
        sealed = seal_bytes(
            substrate.manifest.model_dump_json().encode("utf-8"), load_key_from_env(key_env)
        )
        members["ground-truth-manifest.json.aes"] = sealed
    members["PACK-README.md"] = _run_pack_readme(
        run.run_id, sealed_manifest=include_manifest, has_config=config is not None
    ).encode("utf-8")

    out_path = out if out is not None else workdir / "run-pack.zip"
    out_path.write_bytes(build_bundle(members))
    typer.echo(f"run pack -> {out_path}")
    typer.echo(
        "SENSITIVE: this pack carries the run details and ground-truth markers; "
        "share only with trusted parties."
    )


def _sibling_audit_pdf(pack_path: Path) -> bytes | None:
    """Return the bytes of the audit PDF written beside ``pack_path``, if present.

    The ``report`` and ``erasure`` commands write the audit PDF next to the
    evidence json (``audit-pack.pdf`` / ``erasure-attestation.pdf``). When one is
    present, ``sectum-ai verify`` re-hashes it against the pack's bound ``pdf_ref``;
    when absent, verification still proceeds from the json alone.
    """
    for name in ("audit-pack.pdf", "erasure-attestation.pdf"):
        candidate = pack_path.parent / name
        if candidate.exists():
            return candidate.read_bytes()
    return None


def _sibling_intoto(pack_path: Path) -> Path | None:
    """Return the in-toto sidecar written beside ``pack_path``, if present.

    ``report``/``erasure`` write ``attestation.intoto.json`` /
    ``erasure-attestation.intoto.json`` next to the evidence json. When present,
    ``sectum-ai verify`` re-checks that it binds this pack's run digest; when absent,
    verification proceeds from the json alone (the pack is self-sufficient).
    """
    for name in ("attestation.intoto.json", "erasure-attestation.intoto.json"):
        candidate = pack_path.parent / name
        if candidate.exists():
            return candidate
    return None


def _sibling_dsse(pack_path: Path) -> Path | None:
    """Return the DSSE envelope written beside ``pack_path``, if present.

    ``report`` writes ``evidence.dsse.json`` next to the evidence json; when
    present, ``sectum-ai verify`` re-checks that its in-toto statement binds this
    pack's run digest, so a swapped envelope is caught.
    """
    candidate = pack_path.parent / "evidence.dsse.json"
    return candidate if candidate.exists() else None


def _echo_verdict(anchored: bool, *, what: str) -> None:
    """Print the final verify verdict, distinguishing anchored from unanchored.

    An anchored pass means a verified independent anchor (an RFC 3161 timestamp
    or a Rekor inclusion proof) binds the digest - genuine tamper evidence. An
    unanchored pass (reachable only with ``--allow-unanchored``) confirms
    internal consistency alone: a local-dev token can be regenerated by anyone
    over an edited pack, so the verdict must never read as a plain "VERIFIED".
    """
    if anchored:
        typer.echo(
            f"VERIFIED (independently anchored): the {what}'s attested content is "
            "intact and consistent."
        )
    else:
        typer.echo(
            f"INTEGRITY OK - UNANCHORED: the {what} is internally consistent, but its "
            "only timestamp is a reproducible local-dev token, so this result is NOT "
            "independent tamper evidence. Re-create it with `report --tsa`/`--rekor` "
            "for an anchored attestation."
        )


@app.command()
@_handle_typed_errors
def verify(
    pack: Annotated[Path, typer.Argument(help="Path to an evidence.json pack.")],
    tsa_cert: Annotated[
        Path | None,
        typer.Option("--tsa-cert", help="PEM of the TSA leaf certificate (overrides FreeTSA)."),
    ] = None,
    tsa_root: Annotated[
        Path | None,
        typer.Option("--tsa-root", help="PEM of the TSA root certificate (overrides FreeTSA)."),
    ] = None,
    rekor_key: Annotated[
        Path | None,
        typer.Option("--rekor-key", help="PEM of a Rekor public key (pins a private instance)."),
    ] = None,
    allow_unanchored: Annotated[
        bool,
        typer.Option(
            "--allow-unanchored",
            help=(
                "Accept a pack whose only timestamp is a local-dev token. Such a "
                "token is reproducible by anyone, so the result is integrity-only, "
                "NOT independent tamper evidence. Without this flag, verification "
                "requires a real RFC 3161 timestamp or a Rekor inclusion proof."
            ),
        ),
    ] = False,
) -> None:
    """Independently verify a tamper-evident evidence pack (or an .zip bundle)."""
    if not pack.exists():
        typer.echo(f"no evidence pack at {pack}", err=True)
        raise typer.Exit(code=3)
    for label, cert_path in (
        ("--tsa-cert", tsa_cert),
        ("--tsa-root", tsa_root),
        ("--rekor-key", rekor_key),
    ):
        if cert_path is not None and not cert_path.exists():
            typer.echo(f"no certificate at {cert_path} for {label}", err=True)
            raise typer.Exit(code=3)
    if pack.suffix == ".zip":
        # A bundle (report --bundle) carries the pack and its sidecars in one
        # archive; verify each member's digest and the contained pack together.
        bundle_result = verify_bundle(
            pack.read_bytes(),
            tsa_certificate=tsa_cert.read_bytes() if tsa_cert is not None else None,
            tsa_root=tsa_root.read_bytes() if tsa_root is not None else None,
            rekor_keyring=_rekor_keyring_override(rekor_key),
            require_anchored=not allow_unanchored,
        )
        for check in bundle_result.checks:
            typer.echo(f"[{'ok' if check.ok else 'FAIL'}] {check.name}: {check.detail}")
        if not bundle_result.passed:
            typer.echo("VERIFICATION FAILED", err=True)
            raise typer.Exit(code=4)
        _echo_verdict(bundle_result.anchored, what="evidence bundle")
        return
    try:
        # pydantic's ValidationError is a ValueError; this also catches invalid JSON.
        evidence = EvidencePack.model_validate_json(pack.read_text())
    except ValueError as error:
        typer.echo(f"not a valid evidence pack at {pack}: {error}", err=True)
        raise typer.Exit(code=3) from error
    # Re-hash the audit PDF if it sits beside the pack (report/erasure write
    # audit-pack.pdf / erasure-attestation.pdf next to the json); its hash is
    # bound into the attested digest, so a swapped PDF fails verification.
    pdf_bytes = _sibling_audit_pdf(pack)
    result = verify_pack(
        evidence,
        tsa_certificate=tsa_cert.read_bytes() if tsa_cert is not None else None,
        tsa_root=tsa_root.read_bytes() if tsa_root is not None else None,
        rekor_keyring=_rekor_keyring_override(rekor_key),
        pdf_bytes=pdf_bytes,
        require_anchored=not allow_unanchored,
    )
    for check in result.checks:
        typer.echo(f"[{'ok' if check.ok else 'FAIL'}] {check.name}: {check.detail}")
    passed = result.passed
    # Re-verify the in-toto sidecar if report/erasure wrote one beside the pack:
    # a swapped or corrupt statement that no longer binds this pack's run digest
    # is itemized as a failed check, never silently trusted.
    intoto_path = _sibling_intoto(pack)
    if intoto_path is not None:
        try:
            verify_in_toto_statement(json.loads(intoto_path.read_text()), evidence)
            typer.echo("[ok] in-toto-attestation: sidecar binds this pack's run digest")
        except (ValueError, EvidenceError) as error:
            typer.echo(f"[FAIL] in-toto-attestation: {error}")
            passed = False
    # Re-verify the DSSE envelope sidecar if report wrote one: its in-toto
    # statement must still bind this pack's run digest (a swapped envelope fails).
    dsse_path = _sibling_dsse(pack)
    if dsse_path is not None:
        try:
            verify_dsse_envelope(json.loads(dsse_path.read_text()), evidence)
            typer.echo("[ok] dsse-envelope: sidecar binds this pack's run digest")
        except (ValueError, EvidenceError) as error:
            typer.echo(f"[FAIL] dsse-envelope: {error}")
            passed = False
    if not passed:
        typer.echo("VERIFICATION FAILED", err=True)
        raise typer.Exit(code=4)
    _echo_verdict(result.anchored, what="evidence pack")
    typer.echo(
        "note: this confirms integrity and internal consistency; to also bind which "
        "marker belonged to which tenant, re-run with the original ground-truth manifest.",
        err=True,
    )


def _parse_subject_surface_map(
    path: Path, raw: dict[str, object], key: str
) -> dict[Surface, tuple[str, ...]]:
    """Parse one ``surface-name -> list[str]`` block of a subject manifest."""
    raw_map = raw.get(key) or {}
    if not isinstance(raw_map, dict):
        raise ConfigError(
            f"subject manifest {path}: '{key}' must map a surface to a list of strings"
        )
    result: dict[Surface, tuple[str, ...]] = {}
    for name, values in raw_map.items():
        try:
            surface: Surface | None = Surface(name)
        except ValueError:
            surface = None
        if surface is None or surface not in ERASURE_SURFACES:
            valid = ", ".join(s.value for s in ERASURE_SURFACES)
            raise ConfigError(
                f"subject manifest {path}: '{name}' is not an erasure surface; valid: {valid}"
            ) from None
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ConfigError(f"subject manifest {path}: {key}['{name}'] must be a list of strings")
        result[surface] = tuple(values)
    return result


def _load_subject_manifest(path: Path) -> SubjectManifest:
    """Parse a data-subject manifest (YAML) into a :class:`SubjectManifest`.

    The file carries a ``subject_ref`` (an opaque DSR reference - never subject
    content), ``records`` (a map of erasure-surface name to the subject's record
    **ids**), and optional ``fingerprints`` (a map of surface name to the subject's
    known **content** phrases to probe for residual). Surface names match the
    ``--scope`` names (``vector_db``, ``semantic_cache``, ...).
    """
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"subject manifest {path} must be a mapping")
    subject_ref = raw.get("subject_ref")
    if not isinstance(subject_ref, str) or not subject_ref:
        raise ConfigError(f"subject manifest {path} must set a non-empty 'subject_ref'")
    return SubjectManifest(
        subject_ref=subject_ref,
        records=_parse_subject_surface_map(path, raw, "records"),
        fingerprints=_parse_subject_surface_map(path, raw, "fingerprints"),
    )


def _emit_erasure_attestation(
    report: ErasureReport,
    *,
    run_id: str,
    substrate: Substrate,
    workdir: Path,
    adapter_versions: dict[str, str],
    probe_id: str,
    loaded: SectumConfig,
    started: datetime,
    finished: datetime,
) -> None:
    """Build and write the signed erasure attestation for a report, then report it.

    Shared by the canary (Class 11) and by-id data-subject (A3 Phase 0) erasure
    modes: both produce an :class:`ErasureReport`, so the run record, evidence
    pack, and exit-code logic are identical. Returns on a clean verified pass;
    raises ``typer.Exit`` with code 2 (residual / caveat) or 3 (inconclusive).
    """
    run = RunResult(
        run_id=run_id,
        scenario_hash=canonical_hash(substrate.scenario),
        manifest_hash=canonical_hash(substrate.manifest),
        started_at=started,
        finished_at=finished,
        adapter_versions=adapter_versions,
        probe_versions={probe_id: __version__},
        findings=report.findings,
        metrics=RunMetrics(
            confirmed_findings=len(confirmed_findings(report.findings)),
            erasure_residue={
                surface.surface.value: surface.residual_after
                for surface in report.surfaces
                if surface.erasure_supported
            },
            erasure_caveats={
                surface.surface.value: surface.residual_after
                for surface in report.surfaces
                if not surface.erasure_supported
            },
            erasure_coverage={
                surface.value: verdict.value for surface, verdict in report.coverage().items()
            },
        ),
    )
    controls = control_mappings()
    pdf_path = workdir / "erasure-attestation.pdf"
    pdf_ref = render_audit_pack_and_hash(
        run, canonical_hash(substrate.manifest), controls, pdf_path
    )
    pack = build_evidence_pack(
        run,
        substrate.manifest,
        control_mappings=controls,
        pdf_ref=pdf_ref,
        timestamper=_resolve_timestamper(loaded.evidence, None),
        transparency_log=_resolve_transparency_log(loaded.evidence, False),
    )
    json_path = workdir / "erasure-evidence.json"
    json_path.write_text(pack.model_dump_json(indent=2))
    intoto_path = workdir / "erasure-attestation.intoto.json"
    intoto_path.write_text(json.dumps(to_in_toto_statement(pack), indent=2))

    for surface in report.surfaces:
        typer.echo(
            f"{surface.surface.value}: {surface.markers_before} markers before, "
            f"{surface.residual_after} after -> {surface.verdict}"
        )
    if report.not_covered:
        not_covered_names = ", ".join(surface.value for surface in report.not_covered)
        typer.echo(f"not covered (NOT_COVERED): {not_covered_names}")
    typer.echo(f"erasure attestation -> {json_path}, {pdf_path}")
    if report.genuine_residual:
        typer.echo("ERASURE FAILED: residual data remains.", err=True)
        if report.caveats:
            caveat_names = ", ".join(surface.surface.value for surface in report.caveats)
            typer.echo(
                f"  also attestable-with-caveat: {caveat_names} expose no per-tenant "
                "erasure API, so that data is presumed retained (a backend "
                "limitation, itemized in the attestation).",
                err=True,
            )
        raise typer.Exit(code=2)
    if report.caveats:
        names = ", ".join(surface.surface.value for surface in report.caveats)
        typer.echo(
            f"ERASURE ATTESTABLE WITH CAVEAT: {names} expose no per-tenant erasure "
            "API, so the tenant's data is presumed retained until it ages out of "
            "the backend's retention window. Itemized as a caveat in the "
            "attestation - a backend limitation, not a failure of the erasure flow.",
            err=True,
        )
        raise typer.Exit(code=2)
    if report.erased:
        scanned = ", ".join(surface.surface.value for surface in report.surfaces)
        typer.echo(f"ERASURE VERIFIED: no residual marker on {scanned}.")
        if report.not_covered:
            not_covered_names = ", ".join(surface.value for surface in report.not_covered)
            typer.echo(
                f"  scope: this attests {scanned} only; NOT_COVERED (not verified): "
                f"{not_covered_names}.",
            )
        return
    no_baseline = [
        surface.surface.value for surface in report.surfaces if surface.markers_before == 0
    ]
    scanned = ", ".join(no_baseline) or "(no supported ids or adapters were provided)"
    typer.echo(
        f"ERASURE INCONCLUSIVE: no baseline on {scanned} - "
        "the target tenant's markers were not found on those surfaces, so "
        "erasure cannot be attested.",
        err=True,
    )
    raise typer.Exit(code=3)


@app.command()
@_handle_typed_errors
def erasure(
    target_tenant: Annotated[
        str | None, typer.Option("--target-tenant", help="Tenant display name.")
    ] = None,
    soft_delete: Annotated[
        bool,
        typer.Option(
            "--soft-delete",
            help=(
                "Model a store that fails erasure. Ignored when --config is given; "
                "set 'soft_delete: true' on the adapter in the config instead."
            ),
        ),
    ] = False,
    scope: Annotated[
        str | None,
        typer.Option(
            "--scope",
            help=(
                "Comma-separated erasure surfaces to verify (a cheaper single-surface "
                "'snapshot' engagement), e.g. 'vector_db' or 'vector_db,tracing'. "
                "Surfaces outside the scope are reported NOT_COVERED, never ERASED. "
                "Omit to verify every configured surface (the default). Valid surfaces: "
                "vector_db, tracing, agent_memory, semantic_cache, model_adapter, "
                "search_index, eval_set, backup."
            ),
        ),
    ] = None,
    workdir: Annotated[
        Path | None, typer.Option(help="Directory holding the seeded substrate.")
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Read defaults from this sectum-ai.yaml file."),
    ] = None,
    subject: Annotated[
        Path | None,
        typer.Option(
            "--subject",
            help=(
                "Verify a REAL data subject's erasure by record id (A3 Phase 0), instead "
                "of the synthetic-canary scan. Reads a YAML manifest with 'subject_ref' "
                "(an opaque DSR reference, no PII) and 'records' mapping a surface "
                "(vector_db, semantic_cache) to the subject's record ids, then checks each "
                "id is gone after your own deletion ran. Surfaces with no by-id check or no "
                "ids read NOT_COVERED. Ignores --scope and --soft-delete."
            ),
        ),
    ] = None,
) -> None:
    """Run the GDPR Article 17 erasure-verification workflow (Class 11, the wedge)."""
    erasure_scope = _resolve_erasure_scope(scope)
    if config is not None:
        loaded = load_config(config)
        fake_default = AdapterConfig(kind="fake")
        if soft_delete:
            typer.echo(
                "warning: --soft-delete is ignored when --config is given; "
                "set 'soft_delete: true' on the adapter in the config instead.",
                err=True,
            )
    else:
        loaded = SectumConfig()
        fake_default = AdapterConfig(kind="fake", soft_delete=soft_delete)
    if workdir is None:
        workdir = loaded.workdir
    substrate = _load_substrate(workdir, _resolve_manifest_key(loaded.security))
    target = _resolve_target(substrate, target_tenant)
    if subject is not None:
        # A3 Phase 0/2: verify a real data subject's data is gone - by record id
        # (Phase 0) and, for supplied content, by semantic fingerprint (Phase 2) -
        # rather than scanning the synthetic canaries. Only the surfaces with a
        # by-id / fingerprint primitive are checked; the rest read NOT_COVERED, the
        # same anti-over-claim contract as the canary scan.
        if scope is not None:
            typer.echo(
                "warning: --scope is ignored with --subject; the manifest's surfaces "
                "define what is checked.",
                err=True,
            )
        manifest = _load_subject_manifest(subject)
        subject_store = build_vector_store(loaded.adapters.get("vector_store", fake_default))
        subject_cache = build_cache(loaded.adapters.get("cache", fake_default))
        subject_obs = build_observability(loaded.adapters.get("observability", fake_default))
        subject_model = build_model(loaded.adapters.get("model", fake_default))
        subject_memory = build_memory(loaded.adapters.get("memory", fake_default))
        subject_search = build_search_index(loaded.adapters.get("search_index", fake_default))
        unsupported = [
            surface.value
            for surface in manifest.records
            if surface not in SUBJECT_VERIFIABLE_SURFACES
        ]
        if unsupported:
            typer.echo(
                "warning: by-id erasure verification is not supported yet for "
                f"{', '.join(unsupported)} -> NOT_COVERED.",
                err=True,
            )
        fp_unsupported = [
            surface.value
            for surface in manifest.fingerprints
            if surface not in SUBJECT_FINGERPRINT_SURFACES
        ]
        if fp_unsupported:
            typer.echo(
                "warning: content-fingerprint probing is not supported yet for "
                f"{', '.join(fp_unsupported)} -> NOT_COVERED.",
                err=True,
            )
        if any(surface in SUBJECT_FINGERPRINT_SURFACES for surface in manifest.fingerprints):
            typer.echo(
                "note: content-fingerprint probing is best-effort - a clean result is "
                "evidence the content no longer surfaces, not proof of absence.",
                err=True,
            )
        # A verifiable surface backed by only the built-in synthetic fake (no live
        # adapter configured) checks the subject's data against an empty store, so an
        # ERASED verdict there does not reflect the customer's production data. Say
        # so loudly - an honest DSR attestation must not read as verified when it
        # verified nothing real.
        synthetic = []
        vector_checked = (
            Surface.VECTOR_DB in manifest.records or Surface.VECTOR_DB in manifest.fingerprints
        )
        if vector_checked and isinstance(subject_store, FakeVectorStore):
            synthetic.append("vector_db")
        if Surface.SEMANTIC_CACHE in manifest.records and isinstance(subject_cache, FakeCache):
            synthetic.append("semantic_cache")
        if Surface.TRACING in manifest.records and isinstance(subject_obs, FakeObservability):
            synthetic.append("tracing")
        if Surface.MODEL_ADAPTER in manifest.fingerprints and isinstance(subject_model, FakeModel):
            synthetic.append("model_adapter")
        if Surface.AGENT_MEMORY in manifest.fingerprints and isinstance(subject_memory, FakeMemory):
            synthetic.append("agent_memory")
        if Surface.SEARCH_INDEX in manifest.fingerprints and isinstance(
            subject_search, FakeSearchIndex
        ):
            synthetic.append("search_index")
        if synthetic:
            typer.echo(
                f"warning: no live adapter configured for {', '.join(synthetic)} - "
                "verifying against the built-in synthetic store, so an ERASED verdict "
                "does not reflect production data. Configure a real adapter via --config "
                "for a DSR attestation.",
                err=True,
            )
        subject_started = datetime.now(UTC)
        subject_report = SubjectErasureProbe(
            vector=subject_store,
            cache=subject_cache,
            observability=subject_obs,
            model=subject_model,
            memory=subject_memory,
            search_index=subject_search,
        ).verify(target, manifest)
        subject_finished = datetime.now(UTC)
        _emit_erasure_attestation(
            subject_report,
            run_id=f"erasure-subject-{target.hex[:8]}",
            substrate=substrate,
            workdir=workdir,
            adapter_versions={
                subject_store.name: _ADAPTERS_VERSION,
                subject_cache.name: _ADAPTERS_VERSION,
                subject_obs.name: _ADAPTERS_VERSION,
                subject_model.name: _ADAPTERS_VERSION,
                subject_memory.name: _ADAPTERS_VERSION,
                subject_search.name: _ADAPTERS_VERSION,
            },
            probe_id=SubjectErasureProbe.id,
            loaded=loaded,
            started=subject_started,
            finished=subject_finished,
        )
        return
    store = build_vector_store(loaded.adapters.get("vector_store", fake_default))
    obs = build_observability(loaded.adapters.get("observability", fake_default))
    memory = build_memory(loaded.adapters.get("memory", fake_default))
    cache = build_cache(loaded.adapters.get("cache", fake_default))
    model = build_model(loaded.adapters.get("model", fake_default))
    # The eval set and backup have no live adapters yet; deterministic fakes model
    # them. soft_delete rides on fake_default's extras (set from --soft-delete when
    # no config is given, absent under --config). The search index resolves from
    # config (kind: opensearch) like the other surfaces, falling back to the fake.
    _fake_soft_delete = bool((fake_default.model_extra or {}).get("soft_delete"))
    search = build_search_index(loaded.adapters.get("search_index", fake_default))
    evalset = FakeEvalSet(soft_delete=_fake_soft_delete)
    backup = FakeBackup(soft_delete=_fake_soft_delete)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        store.upsert(tenant.tenant_id, documents)
    for marker in substrate.manifest.markers:
        if marker.marker_type is not MarkerType.HARD_CANARY:
            continue
        if isinstance(obs, FakeObservability):
            obs.record(
                marker.owner_tenant_id,
                "sectum-ai-erasure",
                f"trace recording marker {marker.plaintext}",
            )
        if isinstance(memory, FakeMemory):
            memory.remember(marker.owner_tenant_id, f"memory note recording {marker.plaintext}")
        if isinstance(cache, FakeCache):
            cache.set(
                marker.owner_tenant_id,
                f"sectum-ai-erasure-{marker.marker_id}",
                f"cached answer mentioning {marker.plaintext}",
            )
        if isinstance(model, FakeModel):
            model.train_adapter(marker.owner_tenant_id, [f"fine-tune sample {marker.plaintext}"])
        search.index(marker.owner_tenant_id, f"search index entry mentioning {marker.plaintext}")
        evalset.add(marker.owner_tenant_id, f"eval set fixture mentioning {marker.plaintext}")
        backup.add(marker.owner_tenant_id, f"backup snapshot mentioning {marker.plaintext}")

    started = datetime.now(UTC)
    report = ErasureProbe(
        substrate,
        vector=store,
        observability=obs,
        memory=memory,
        cache=cache,
        model=model,
        search_index=search,
        eval_set=evalset,
        backup=backup,
    ).run(target, scope=erasure_scope)
    finished = datetime.now(UTC)

    _emit_erasure_attestation(
        report,
        run_id=f"erasure-{target.hex[:8]}",
        substrate=substrate,
        workdir=workdir,
        adapter_versions={
            store.name: _ADAPTERS_VERSION,
            obs.name: _ADAPTERS_VERSION,
            memory.name: _ADAPTERS_VERSION,
            cache.name: _ADAPTERS_VERSION,
            model.name: _ADAPTERS_VERSION,
            search.name: _ADAPTERS_VERSION,
            evalset.name: _ADAPTERS_VERSION,
            backup.name: _ADAPTERS_VERSION,
        },
        probe_id=ErasureProbe.id,
        loaded=loaded,
        started=started,
        finished=finished,
    )


@app.command()
def init(
    output: Annotated[
        Path, typer.Option(help="Path for the generated config file.")
    ] = _DEFAULT_CONFIG,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite an existing config file.")
    ] = False,
) -> None:
    """Scaffold a sectum-ai.yaml configuration file."""
    if output.exists() and not force:
        typer.echo(f"{output} already exists; pass --force to overwrite", err=True)
        raise typer.Exit(code=3)
    output.write_text(_CONFIG_TEMPLATE)
    typer.echo(f"wrote {output}")


class _BatchToSingleEmbedder:
    """Adapt a batch ``EmbeddingModel`` to the single-text ``EmbeddingProvider`` protocol.

    The detection pipeline (and the calibration harness) embed one observation at
    a time via ``EmbeddingProvider.embed(text) -> tuple[float, ...]``, while the
    Class-2 sweep models in ``sectum_ai.embeddings`` expose a batch
    ``embed(texts) -> list[list[float]]``. This wraps the latter so a ``--embedder
    st:<model>`` / ``openai:<model>`` resolves into the pipeline unchanged.
    """

    def __init__(self, model: EmbeddingModel) -> None:
        self._model = model
        self.name = model.name

    def embed(self, text: str) -> tuple[float, ...]:
        """Embed a single text by calling the batch model with a one-item list."""
        return tuple(self._model.embed([text])[0])


def _resolve_calibration_embedder(
    spec: str | None, detection_embedder: EmbedderConfig
) -> tuple[EmbeddingProvider, str]:
    """Resolve the embedder to calibrate, returning ``(provider, canonical_name)``.

    A ``--embedder`` overrides the config. The literal ``fake`` selects the
    deterministic offline :class:`FakeEmbeddingProvider`; any other spec
    (``st:<model>`` / ``openai:<model>`` / ``hash-<dim>``) is resolved through
    ``sectum_ai.embeddings`` and adapted to the single-text protocol. When no
    ``--embedder`` is given the config's ``detection.embedder`` is used: ``fake``
    -> the offline fake, ``openai`` -> the live OpenAI provider (which needs an
    API key). The canonical name is the key under which a calibrated threshold can
    be added to ``MODEL_THRESHOLDS``.
    """
    if spec is not None:
        if spec == "fake":
            return FakeEmbeddingProvider(), "fake"
        model = resolve_embedding_model(spec)
        if model is None:
            raise ConfigError(
                f"--embedder {spec!r} does not name a real embedding model; "
                "use fake, hash-<dim>, st:<model>, or openai:<model>"
            )
        return _BatchToSingleEmbedder(model), model.name
    provider = build_embedder(detection_embedder)
    if provider is None:  # kind: fake -> the offline deterministic embedder
        return FakeEmbeddingProvider(), "fake"
    name = embedder_model_name(detection_embedder) or detection_embedder.kind
    return provider, name


def _render_calibration_text(result: CalibrationResult) -> None:
    """Print the calibration table, the recommendation, and the suggested config."""
    typer.echo(f"calibrating semantic threshold for embedder: {result.model_name}")
    typer.echo(
        f"labeled set: {result.positives} positive (cross-tenant leak), "
        f"{result.negatives} negative (same-tenant / unrelated)"
    )
    typer.echo("")
    header = (
        f"{'THRESHOLD':>10}  {'PREC':>6}  {'RECALL':>6}  {'F1':>6}  "
        f"{'TP':>4} {'FP':>4} {'FN':>4}  ZERO-FP"
    )
    typer.echo(header)
    for score in result.scores:
        marker = " <- recommended" if score is result.recommended_score else ""
        typer.echo(
            f"{score.threshold:>10.4f}  {score.precision:>6.3f}  {score.recall:>6.3f}  "
            f"{score.f1:>6.3f}  {score.true_positives:>4} {score.false_positives:>4} "
            f"{score.false_negatives:>4}  {'yes' if score.zero_false_positive else 'no':>7}{marker}"
        )
    typer.echo("")
    if result.recommended_score is None:
        typer.echo(
            f"no threshold separated the classes with zero false positives; "
            f"recommending the conservative default {result.recommended_threshold:g} "
            "(a stronger, real embedding model is expected to separate cleanly - "
            "the offline fake embedder cannot)."
        )
    else:
        typer.echo(
            f"recommended semantic_threshold: {result.recommended_threshold:g} "
            f"(max F1 = {result.recommended_score.f1:g} with zero false positives)"
        )
    typer.echo("")
    typer.echo("apply it in sectum-ai.yaml:")
    typer.echo("  detection:")
    typer.echo(f"    semantic_threshold: {result.recommended_threshold:g}")


def _render_calibration_json(result: CalibrationResult) -> None:
    """Print the calibration result as one machine-parseable JSON object on stdout."""
    payload = {
        "model_name": result.model_name,
        "recommended_threshold": result.recommended_threshold,
        "zero_false_positive": result.recommended_score is not None,
        "positives": result.positives,
        "negatives": result.negatives,
        "scores": [
            {
                "threshold": score.threshold,
                "precision": score.precision,
                "recall": score.recall,
                "f1": score.f1,
                "true_positives": score.true_positives,
                "false_positives": score.false_positives,
                "false_negatives": score.false_negatives,
                "zero_false_positive": score.zero_false_positive,
            }
            for score in result.scores
        ],
    }
    typer.echo(json.dumps(payload, indent=2))


@app.command()
@_handle_typed_errors
def calibrate(
    embedder: Annotated[
        str | None,
        typer.Option(
            "--embedder",
            help=(
                "Embedder to calibrate as kind:model (e.g. st:all-mpnet-base-v2, "
                "openai:text-embedding-3-small, hash-256, or fake). Defaults to the "
                "config's detection.embedder."
            ),
        ),
    ] = None,
    scenario_seed: Annotated[
        int | None, typer.Option("--seed", help="Scenario seed (deterministic).")
    ] = None,
    workdir: Annotated[
        Path | None, typer.Option(help="Directory for run artifacts (sources config defaults).")
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Read defaults from this sectum-ai.yaml file."),
    ] = None,
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            help=(
                "Render the calibration on stdout. `text` is human-readable (default); "
                "`json` emits a single machine-parseable object."
            ),
            case_sensitive=False,
        ),
    ] = OutputFormat.TEXT,
) -> None:
    """Recommend a per-embedding-model semantic threshold from a labeled leak set.

    Builds a deterministic labeled set from a seeded substrate - positives are a
    foreign tenant's entity genuinely surfaced into another tenant's session,
    negatives are same-tenant and unrelated text - scores each with the configured
    embedder, and recommends the threshold that maximises F1 subject to zero false
    positives among the negatives (the engineering spec, section 6.4). Set the
    recommended value as ``detection.semantic_threshold`` (or use ``auto`` for the
    built-in preset).
    """
    if output in (OutputFormat.SARIF, OutputFormat.OSCAL):
        raise ConfigError(f"calibrate supports --output text or json, not {output.value}")
    loaded = load_config(config) if config is not None else SectumConfig()
    effective_seed = scenario_seed if scenario_seed is not None else loaded.scenario.seed
    # workdir is accepted for parity with the other workflow commands and to source
    # config defaults; calibration is a pure function of (seed, embedder) and the
    # substrate it builds, so it writes nothing and needs no prior `seed` run.
    _ = workdir if workdir is not None else loaded.workdir
    provider, model_name = _resolve_calibration_embedder(embedder, loaded.detection.embedder)
    substrate = build_substrate(
        default_scenario(seed=effective_seed, corpus_size=loaded.scenario.corpus_size)
    )
    result = calibrate_threshold(substrate, model_name=model_name, embedder=provider)
    if output is OutputFormat.JSON:
        _render_calibration_json(result)
    else:
        _render_calibration_text(result)


def _delta_verdict(delta: MetricDelta) -> str:
    """The status tag for a metric delta line: regression, informational, or ok."""
    if delta.informational:
        return "info"
    return "REGRESSED" if delta.regressed else "ok"


@app.command()
@_handle_typed_errors
def baseline(
    workdir: Annotated[
        Path | None, typer.Option(help="Directory holding the recorded run.")
    ] = None,
    save: Annotated[
        bool, typer.Option("--save", help="Save the current run as the baseline.")
    ] = False,
    compare: Annotated[
        bool,
        typer.Option("--compare", help="Compare the current run against the saved baseline."),
    ] = False,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Read defaults from this sectum-ai.yaml file."),
    ] = None,
) -> None:
    """Save a regression baseline from the current run, or compare against it."""
    loaded = load_config(config) if config is not None else SectumConfig()
    if workdir is None:
        workdir = loaded.workdir
    run = _load_run(workdir)
    baseline_path = workdir / "baseline.json"
    if save:
        baseline_path.write_text(run.model_dump_json(indent=2))
        typer.echo(f"baseline saved -> {baseline_path}")
        return
    if not compare:
        typer.echo("pass --save to record a baseline or --compare to check against it", err=True)
        raise typer.Exit(code=3)
    if not baseline_path.exists():
        typer.echo(
            f"no baseline at {baseline_path}; run 'sectum-ai baseline --save' first", err=True
        )
        raise typer.Exit(code=3)
    try:
        saved = RunResult.model_validate_json(baseline_path.read_text())
    except ValueError as error:
        typer.echo(
            f"the baseline at {baseline_path} is malformed "
            f"(re-run 'sectum-ai baseline --save' to refresh it): {error}",
            err=True,
        )
        raise typer.Exit(code=3) from error
    # Use the full run diff (the same logic as `sectum-ai diff`), not a metric-only
    # comparison: a leak that newly confirmed or escalated in severity is a
    # regression the headline counts can miss.
    result = diff_runs(saved, run)
    for delta in result.metrics.deltas:
        typer.echo(
            f"[{_delta_verdict(delta)}] {delta.name}: {delta.baseline:g} -> {delta.current:g}"
        )
    for change in result.findings.severity_escalations:
        typer.echo(
            f"[REGRESSED] severity escalated: {change.previous.finding_id} "
            f"{change.previous.severity.value} -> {change.current.severity.value}"
        )
    for finding in result.findings.newly_confirmed:
        typer.echo(f"[REGRESSED] newly confirmed leak: {finding.finding_id}")
    if result.regressed:
        typer.echo(
            "BASELINE REGRESSION: a metric worsened, a leak was newly confirmed, "
            "or a confirmed leak escalated in severity.",
            err=True,
        )
        raise typer.Exit(code=2)
    typer.echo("no regression against the baseline")


def _load_run_artifact(path: Path) -> RunResult:
    """Load a :class:`RunResult` from a ``run.json`` or an evidence pack of one.

    Accepts either the run record written by ``sectum-ai probe`` or an
    ``evidence.json`` pack (whose ``run_result`` is unwrapped), so two signed
    packs compare directly. Raises :class:`ConfigError` for a missing file,
    malformed JSON, or a payload that is neither shape.
    """
    if not path.exists():
        raise ConfigError(f"no such run file: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ConfigError(f"{path} is not valid JSON: {error}") from error
    try:
        if isinstance(data, dict) and "run_result" in data:
            return EvidencePack.model_validate(data).run_result
        return RunResult.model_validate(data)
    except ValidationError as error:
        raise ConfigError(f"{path} is not a sectum run or evidence pack: {error}") from error


def _finding_row(finding: Finding) -> dict[str, str | None]:
    """A JSON-safe, comparison-relevant subset of a finding for diff output.

    The user dimension (ADR-0006) is included when set, so two distinct
    cross-user leaks within one tenant do not collapse to the same row; both
    user fields are ``null`` for a tenant-level finding.
    """
    return {
        "finding_id": finding.finding_id,
        "probe_id": finding.probe_id,
        "severity": finding.severity.value,
        "status": finding.status.value,
        "surface": finding.surface.value,
        "owner_tenant_id": str(finding.owner_tenant_id),
        "observed_in_tenant_id": str(finding.observed_in_tenant_id),
        "owner_user_id": str(finding.owner_user_id) if finding.owner_user_id else None,
        "observed_in_user_id": (
            str(finding.observed_in_user_id) if finding.observed_in_user_id else None
        ),
    }


def _change_row(change: FindingChange) -> dict[str, str | None]:
    """A finding row for an in-place change, carrying its previous status/severity."""
    row = _finding_row(change.current)
    row["previous_status"] = change.previous.status.value
    row["previous_severity"] = change.previous.severity.value
    return row


def _render_diff_text(earlier: Path, later: Path, result: RunDiff) -> None:
    """Print the human-readable diff: finding changes, metric deltas, verdict."""
    findings = result.findings
    typer.echo(f"sectum-ai diff: {earlier} -> {later}")
    typer.echo("")
    typer.echo("Findings:")
    typer.echo(
        f"  + {len(findings.appeared)} appeared, "
        f"- {len(findings.resolved)} resolved, "
        f"= {len(findings.persisting)} persisting, "
        f"! {len(findings.newly_confirmed)} newly confirmed, "
        f"~ {len(findings.changed)} changed"
    )

    def _line(sign: str, finding: Finding) -> str:
        owner = str(finding.owner_tenant_id)[:8]
        observed = str(finding.observed_in_tenant_id)[:8]
        return (
            f"    {sign} [{finding.status.value}/{finding.severity.value}] "
            f"{finding.probe_id}  {owner} -> {observed}  "
            f"({finding.surface.value})  {finding.finding_id[:12]}"
        )

    escalation_ids = {change.current.finding_id for change in findings.severity_escalations}

    def _change_line(change: FindingChange) -> str:
        finding = change.current
        owner = str(finding.owner_tenant_id)[:8]
        observed = str(finding.observed_in_tenant_id)[:8]
        sign = "!" if finding.finding_id in escalation_ids else "~"
        transition = (
            f"{change.previous.status.value}/{change.previous.severity.value}"
            f" -> {finding.status.value}/{finding.severity.value}"
        )
        return (
            f"    {sign} [{transition}] {finding.probe_id}  "
            f"{owner} -> {observed}  ({finding.surface.value})  "
            f"{finding.finding_id[:12]}"
        )

    if findings.appeared:
        typer.echo("  appeared:")
        for finding in findings.appeared:
            typer.echo(_line("+", finding))
    if findings.resolved:
        typer.echo("  resolved:")
        for finding in findings.resolved:
            typer.echo(_line("-", finding))
    if findings.changed:
        typer.echo("  changed:")
        for change in findings.changed:
            typer.echo(_change_line(change))

    typer.echo("")
    typer.echo("Metrics:")
    for delta in result.metrics.deltas:
        typer.echo(
            f"  [{_delta_verdict(delta)}] {delta.name}: {delta.baseline:g} -> {delta.current:g}"
        )

    typer.echo("")
    typer.echo("RESULT: REGRESSION" if result.regressed else "RESULT: no regression")


def _render_diff_json(earlier: Path, later: Path, result: RunDiff) -> None:
    """Print the diff as one machine-parseable JSON object on stdout."""
    payload = {
        "earlier": str(earlier),
        "later": str(later),
        "findings": {
            "appeared": [_finding_row(f) for f in result.findings.appeared],
            "resolved": [_finding_row(f) for f in result.findings.resolved],
            "newly_confirmed": [_finding_row(f) for f in result.findings.newly_confirmed],
            "changed": [_change_row(c) for c in result.findings.changed],
            "severity_escalation_count": len(result.findings.severity_escalations),
            "persisting_count": len(result.findings.persisting),
        },
        "metrics": [
            {
                "name": delta.name,
                "baseline": delta.baseline,
                "current": delta.current,
                "regressed": delta.regressed,
                "informational": delta.informational,
            }
            for delta in result.metrics.deltas
        ],
        "regressed": result.regressed,
    }
    typer.echo(json.dumps(payload, indent=2))


@app.command()
@_handle_typed_errors
def diff(
    earlier: Annotated[
        Path,
        typer.Argument(help="The earlier/reference run.json or evidence.json."),
    ],
    later: Annotated[
        Path,
        typer.Argument(help="The later run.json or evidence.json under scrutiny."),
    ],
    output: Annotated[
        OutputFormat,
        typer.Option(
            "--output",
            help=(
                "Render the diff on stdout. `text` is human-readable (default); "
                "`json` emits a single machine-parseable object for CI pipelines."
            ),
            case_sensitive=False,
        ),
    ] = OutputFormat.TEXT,
) -> None:
    """Diff two runs (or evidence packs): new, resolved, changed, persisting findings.

    Compares metric deltas (as ``baseline --compare`` does) and, in addition, the
    findings themselves keyed by id - including in-place changes (status or
    severity). Exits with code 2 when the later run regressed - any worsened
    metric, a newly confirmed finding, or a severity escalation of a finding
    confirmed in both runs - else 0, so the command can gate a CI pipeline (the
    engineering spec, section 10).
    """
    if output in (OutputFormat.SARIF, OutputFormat.OSCAL):
        # SARIF and OSCAL project a single run's findings; a two-run delta has no
        # meaningful rendering in either, so reject them rather than silently
        # falling through to text (the guard symmetry the calibrate command uses).
        raise ConfigError(f"diff supports --output text or json, not {output.value}")
    earlier_run = _load_run_artifact(earlier)
    later_run = _load_run_artifact(later)
    result = diff_runs(earlier_run, later_run)
    if output is OutputFormat.JSON:
        _render_diff_json(earlier, later, result)
    else:
        _render_diff_text(earlier, later, result)
    if result.regressed:
        raise typer.Exit(code=2)


if __name__ == "__main__":  # pragma: no cover
    app()
