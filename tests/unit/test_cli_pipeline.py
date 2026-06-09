"""Tests for the ``sectum`` evidence-pipeline CLI commands."""

import json
from pathlib import Path

from typer.testing import CliRunner

from sectum_ai.cli.app import _resolve_timestamper, _resolve_transparency_log, app
from sectum_ai.config import EvidenceConfig
from sectum_ai.evidence import RekorTransparencyLog, Rfc3161Timestamper
from sectum_ai.spec import RunMetrics, RunResult

_runner = CliRunner()


def _seed_and_probe(workdir: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(workdir)])
    _runner.invoke(app, ["probe", "--workdir", str(workdir)])


def test_full_cli_sweep_records_per_model_rpr(tmp_path: Path) -> None:
    # The P5 wiring, end to end: a multi-embedding-model scenario makes `sectum
    # probe` record a per-model Retrieval-Pivot Rate. Before embedding_models was
    # threaded through config -> seed -> substrate it was always {} on real runs.
    seed = _runner.invoke(
        app,
        [
            "seed",
            "--workdir",
            str(tmp_path),
            "--embedding-model",
            "hash-32",
            "--embedding-model",
            "hash-256",
        ],
    )
    assert seed.exit_code == 0
    probe = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert probe.exit_code == 2  # the shared-index demo leaks
    metrics = json.loads((tmp_path / "run.json").read_text())["metrics"]
    rates = metrics["retrieval_pivot_rate_by_model"]
    assert set(rates) == {"hash-32", "hash-256"}
    # the stronger (higher-dim, fewer-collision) model surfaces more cross-tenant pivots
    assert rates["hash-32"] < rates["hash-256"]


def test_seed_rejects_an_unknown_embedding_model(tmp_path: Path) -> None:
    result = _runner.invoke(
        app, ["seed", "--workdir", str(tmp_path), "--embedding-model", "minilm"]
    )
    assert result.exit_code == 3
    assert "unknown embedding model" in result.output


def test_probe_stamps_the_adapters_distribution_version(tmp_path: Path) -> None:
    # A run's adapter_versions must attest the sectum-ai-adapters distribution
    # version (the code that drove each surface), resolved via adapters.version()
    # — not the core CLI's hard-coded __version__.
    from importlib.metadata import version as dist_version

    from sectum_ai.adapters import version as adapters_version

    assert adapters_version() == dist_version("sectum-ai-adapters")
    _seed_and_probe(tmp_path)
    adapter_versions = json.loads((tmp_path / "run.json").read_text())["adapter_versions"]
    assert adapter_versions
    assert set(adapter_versions.values()) == {adapters_version()}


def test_seed_writes_a_substrate(tmp_path: Path) -> None:
    result = _runner.invoke(app, ["seed", "--workdir", str(tmp_path), "--seed", "2026"])
    assert result.exit_code == 0
    substrate = json.loads((tmp_path / "substrate.json").read_text())
    assert substrate["tenants"]
    assert substrate["documents"]


def test_seed_reads_workdir_and_seed_from_a_config(tmp_path: Path) -> None:
    workdir = tmp_path / "from-config"
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(f"scenario:\n  seed: 1\nworkdir: {workdir}\n")
    result = _runner.invoke(app, ["seed", "--config", str(config_path)])
    assert result.exit_code == 0
    assert (workdir / "substrate.json").exists()


def test_seed_explicit_flag_overrides_a_config_value(tmp_path: Path) -> None:
    config_workdir = tmp_path / "from-config"
    explicit_workdir = tmp_path / "from-flag"
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(f"workdir: {config_workdir}\n")
    result = _runner.invoke(
        app,
        ["seed", "--config", str(config_path), "--workdir", str(explicit_workdir)],
    )
    assert result.exit_code == 0
    assert (explicit_workdir / "substrate.json").exists()
    assert not config_workdir.exists()


def test_probe_records_a_run_and_exits_two_on_confirmed_leaks(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    # the built-in demo stack is intentionally leaky: confirmed findings -> exit 2
    assert result.exit_code == 2
    run = json.loads((tmp_path / "run.json").read_text())
    metrics = run["metrics"]
    assert metrics["confirmed_findings"] > 0
    assert metrics["retrieval_pivot_rate"] is not None
    # The binomial counts behind the rate are recorded so the confidence interval
    # is reproducible from the evidence: rate == k / n, and the Wilson interval
    # brackets the point estimate and stays in [0, 1].
    n, k = metrics["retrieval_pivot_n"], metrics["retrieval_pivot_k"]
    assert n > 0
    assert 0 <= k <= n
    assert metrics["retrieval_pivot_rate"] == k / n
    low, high = metrics["retrieval_pivot_rate_ci"]
    assert 0.0 <= low <= metrics["retrieval_pivot_rate"] <= high <= 1.0


def test_probe_text_output_shows_the_rpr_confidence_interval(tmp_path: Path) -> None:
    # The human-readable summary presents the headline rate with its 95% interval
    # and sample size, never as a bare point estimate (the spec's anti-over-claim).
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--output", "text"])
    assert result.exit_code == 2
    assert "retrieval-pivot rate:" in result.stdout
    assert "95% CI" in result.stdout
    assert "n=" in result.stdout


def test_probe_json_output_carries_the_rpr_counts_and_interval(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--output", "json"])
    assert result.exit_code == 2
    summary = json.loads(result.stdout)
    assert summary["retrieval_pivot_n"] > 0
    assert summary["retrieval_pivot_rate"] == (
        summary["retrieval_pivot_k"] / summary["retrieval_pivot_n"]
    )
    low, high = summary["retrieval_pivot_rate_ci"]
    assert 0.0 <= low <= summary["retrieval_pivot_rate"] <= high <= 1.0


def test_probe_with_an_isolated_config_yields_no_findings(tmp_path: Path) -> None:
    """A config with non-leaky fakes produces zero confirmed cross-tenant findings."""
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(
        "adapters:\n"
        "  vector_store: {kind: fake, shared_index: false}\n"
        "  cache: {kind: fake, tenant_scoped: true}\n"
        "  model: {kind: fake}\n"
        "  mcp: {kind: fake}\n"
        "  memory: {kind: fake}\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app, ["probe", "--config", str(config_path), "--workdir", str(tmp_path)]
    )
    # isolated adapters mean no confirmed cross-tenant findings -> exit 0
    assert result.exit_code == 0
    run = json.loads((tmp_path / "run.json").read_text())
    assert run["metrics"]["confirmed_findings"] == 0


def test_probe_without_a_seeded_substrate_fails_cleanly(tmp_path: Path) -> None:
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code == 3


def test_probe_can_run_a_single_probe(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app, ["probe", "--workdir", str(tmp_path), "--probe", "agent-tool-hijack"]
    )
    assert result.exit_code == 2
    run = json.loads((tmp_path / "run.json").read_text())
    assert set(run["probe_versions"]) == {"agent-tool-hijack"}
    # the Retrieval-Pivot Rate is a Class 2 metric; it is unset when Class 2 did not run
    assert run["metrics"]["retrieval_pivot_rate"] is None
    # likewise the Class 3/6/10 rates are unset when their probes did not run
    assert run["metrics"]["poisoning_bleed_delta"] is None
    assert run["metrics"]["inversion_reconstruction_rate"] is None
    assert run["metrics"]["extraction_efficiency"] is None


def test_probe_records_class_3_6_10_metrics_on_a_full_sweep(tmp_path: Path) -> None:
    """The Class 3 (poisoning), 6 (inversion), and 10 (extraction) headline rates
    populate when their probes run against the leaky demo stack."""
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code == 2
    metrics = json.loads((tmp_path / "run.json").read_text())["metrics"]
    for key in (
        "poisoning_bleed_delta",
        "inversion_reconstruction_rate",
        "extraction_efficiency",
    ):
        assert metrics[key] is not None, key
        assert 0.0 <= metrics[key] <= 1.0, key
    # the poison lure plants a HARD_CANARY that surfaces cross-tenant on the
    # shared-index demo stack, so its exact-match bleed rate is non-zero - and so
    # are the inversion (Class 6) and extraction (Class 10) rates on the same
    # leaky stack. A regression that silenced any of these classes would drop its
    # rate to zero here, not merely to a populated-but-meaningless value.
    assert metrics["poisoning_bleed_delta"] > 0.0
    assert metrics["inversion_reconstruction_rate"] > 0.0
    assert metrics["extraction_efficiency"] > 0.0


def test_probe_rejects_an_unknown_probe_id(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--probe", "no-such-probe"])
    assert result.exit_code == 3


def test_probe_records_no_duplicate_finding_ids(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    run = json.loads((tmp_path / "run.json").read_text())
    finding_ids = [finding["finding_id"] for finding in run["findings"]]
    assert finding_ids
    assert len(finding_ids) == len(set(finding_ids))


def test_baseline_saves_and_compares_clean_against_an_unchanged_run(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    saved = _runner.invoke(app, ["baseline", "--workdir", str(tmp_path), "--save"])
    assert saved.exit_code == 0
    assert (tmp_path / "baseline.json").exists()
    same = _runner.invoke(app, ["baseline", "--workdir", str(tmp_path), "--compare"])
    assert same.exit_code == 0
    assert "no regression" in same.output


def test_baseline_compare_flags_an_injected_regression(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    # A baseline taken from a then-clean stack: the same run, but with no leaks
    # and no retrieval pivot. (The baseline is now a full RunResult, not just
    # metrics, so `--compare` can run the same finding-level diff as `sectum-ai diff`.)
    run = RunResult.model_validate_json((tmp_path / "run.json").read_text())
    clean = run.model_copy(
        update={
            "findings": (),
            "metrics": RunMetrics(confirmed_findings=0, retrieval_pivot_rate=0.0),
        }
    )
    (tmp_path / "baseline.json").write_text(clean.model_dump_json())
    result = _runner.invoke(app, ["baseline", "--workdir", str(tmp_path), "--compare"])
    assert result.exit_code == 2
    assert "REGRESSION" in result.output


def test_baseline_compare_without_a_saved_baseline_fails(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    result = _runner.invoke(app, ["baseline", "--workdir", str(tmp_path), "--compare"])
    assert result.exit_code == 3


def test_baseline_without_save_or_compare_is_a_usage_error(tmp_path: Path) -> None:
    # Invoked with neither --save nor --compare, `baseline` is a usage error: it
    # exits 3 (config/usage, per the CLI spec) and points the user at the two
    # valid modes rather than doing nothing silently.
    _seed_and_probe(tmp_path)
    result = _runner.invoke(app, ["baseline", "--workdir", str(tmp_path)])
    assert result.exit_code == 3
    assert "pass --save" in result.output
    assert "--compare" in result.output


def test_report_builds_an_evidence_pack_and_pdf(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    result = _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "evidence.json").exists()
    assert (tmp_path / "audit-pack.pdf").read_bytes().startswith(b"%PDF")


def test_report_emits_an_in_toto_attestation(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    statement = json.loads((tmp_path / "attestation.intoto.json").read_text())
    assert statement["_type"] == "https://in-toto.io/Statement/v1"
    # the subject digest binds the same run digest the pack is built over
    pack = json.loads((tmp_path / "evidence.json").read_text())
    assert statement["subject"][0]["digest"]["sha256"]
    assert statement["predicate"]["manifest_hash"] == pack["manifest_hash"]


def test_verify_passes_for_a_freshly_built_pack(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["verify", str(tmp_path / "evidence.json"), "--allow-unanchored"])
    assert result.exit_code == 0
    assert "INTEGRITY OK - UNANCHORED" in result.output


def test_verify_fails_on_a_tampered_pack(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    evidence_path = tmp_path / "evidence.json"
    pack = json.loads(evidence_path.read_text())
    pack["run_result"]["run_id"] = "tampered"
    evidence_path.write_text(json.dumps(pack))
    result = _runner.invoke(app, ["verify", str(evidence_path)])
    assert result.exit_code == 4


def test_report_bundle_round_trips_through_verify(tmp_path: Path) -> None:
    # report --bundle writes one evidence-bundle.zip; `verify <bundle.zip>` checks
    # every member digest and the contained pack together (the spec, section 8.2).
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path), "--bundle"])
    bundle_path = tmp_path / "evidence-bundle.zip"
    assert bundle_path.exists()
    result = _runner.invoke(app, ["verify", str(bundle_path), "--allow-unanchored"])
    assert result.exit_code == 0
    assert "INTEGRITY OK - UNANCHORED" in result.output


def test_cli_version_is_the_installed_package_version_and_is_stamped(tmp_path: Path) -> None:
    # The embedded version must match the packaged release (not a hard-coded
    # 0.0.0): it is stamped into every evidence pack's adapter/probe versions and
    # the audit PDF, so a drift falsifies the tamper-evident artifact.
    from importlib.metadata import version

    from sectum_ai.cli.app import __version__

    assert __version__ == version("sectum-ai")
    assert __version__ != "0.0.0"
    _seed_and_probe(tmp_path)
    run = RunResult.model_validate_json((tmp_path / "run.json").read_text())
    assert run.adapter_versions
    assert set(run.adapter_versions.values()) == {__version__}
    assert set(run.probe_versions.values()) == {__version__}


def test_version_flag_prints_the_package_version() -> None:
    from importlib.metadata import version

    result = _runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert version("sectum-ai") in result.output


def test_verify_rechecks_the_in_toto_sidecar(tmp_path: Path) -> None:
    # report writes attestation.intoto.json beside the pack; verify must re-check
    # it -- the one shipped artifact the verifier previously ignored.
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    ok = _runner.invoke(app, ["verify", str(tmp_path / "evidence.json"), "--allow-unanchored"])
    assert ok.exit_code == 0
    assert "in-toto-attestation" in ok.output
    # a sidecar swapped to attest a different run digest fails verification (exit 4)
    intoto = tmp_path / "attestation.intoto.json"
    statement = json.loads(intoto.read_text())
    statement["subject"][0]["digest"]["sha256"] = "0" * 64
    intoto.write_text(json.dumps(statement))
    bad = _runner.invoke(app, ["verify", str(tmp_path / "evidence.json"), "--allow-unanchored"])
    assert bad.exit_code == 4
    assert "in-toto-attestation" in bad.output


def test_verify_fails_when_the_audit_pdf_is_swapped(tmp_path: Path) -> None:
    # The audit PDF's SHA-256 is bound into the attested digest and re-hashed by
    # verify; replacing the sibling PDF (without touching the json) fails (exit 4).
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    (tmp_path / "audit-pack.pdf").write_bytes(b"%PDF-1.4 forged audit pack")
    result = _runner.invoke(app, ["verify", str(tmp_path / "evidence.json"), "--allow-unanchored"])
    assert result.exit_code == 4


def test_verify_on_a_malformed_pack_exits_cleanly(tmp_path: Path) -> None:
    # The OSS verifier runs on packs it did not produce, so a malformed file must
    # exit with a code (3), not a traceback.
    bad_pack = tmp_path / "evidence.json"
    bad_pack.write_text("{not valid json")
    result = _runner.invoke(app, ["verify", str(bad_pack)])
    assert result.exit_code == 3


def test_verify_with_a_missing_tsa_cert_errors(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app,
        ["verify", str(tmp_path / "evidence.json"), "--tsa-cert", str(tmp_path / "absent.pem")],
    )
    assert result.exit_code == 3


def test_resolve_timestamper_defaults_to_the_local_timestamper() -> None:
    assert _resolve_timestamper(EvidenceConfig(), None) is None


def test_resolve_timestamper_honors_the_rfc3161_setting() -> None:
    stamper = _resolve_timestamper(
        EvidenceConfig(timestamper="rfc3161", tsa_url="https://tsa.example/tsr"), None
    )
    assert isinstance(stamper, Rfc3161Timestamper)
    assert stamper.tsa == "https://tsa.example/tsr"


def test_resolve_timestamper_rfc3161_without_a_url_uses_freetsa() -> None:
    stamper = _resolve_timestamper(EvidenceConfig(timestamper="rfc3161"), None)
    assert isinstance(stamper, Rfc3161Timestamper)
    assert stamper.tsa == "https://freetsa.org/tsr"


def test_resolve_timestamper_cli_override_wins_over_the_config() -> None:
    stamper = _resolve_timestamper(EvidenceConfig(), "https://pinned.example/tsr")
    assert isinstance(stamper, Rfc3161Timestamper)
    assert stamper.tsa == "https://pinned.example/tsr"


def test_resolve_transparency_log_is_none_by_default() -> None:
    assert _resolve_transparency_log(EvidenceConfig(), False) is None


def test_resolve_transparency_log_enabled_by_the_flag() -> None:
    log = _resolve_transparency_log(EvidenceConfig(), True)
    assert isinstance(log, RekorTransparencyLog)
    assert log.rekor_url == "https://rekor.sigstore.dev"


def test_resolve_transparency_log_honors_a_config_url() -> None:
    log = _resolve_transparency_log(
        EvidenceConfig(rekor=True, rekor_url="https://rekor.example"), False
    )
    assert isinstance(log, RekorTransparencyLog)
    assert log.rekor_url == "https://rekor.example"


def test_verify_with_a_missing_rekor_key_errors(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app,
        ["verify", str(tmp_path / "evidence.json"), "--rekor-key", str(tmp_path / "absent.pem")],
    )
    assert result.exit_code == 3


def test_report_with_a_config_uses_its_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "from-config"
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(f"workdir: {workdir}\n")
    _runner.invoke(app, ["seed", "--workdir", str(workdir)])
    _runner.invoke(app, ["probe", "--workdir", str(workdir)])
    result = _runner.invoke(app, ["report", "--config", str(config_path)])
    assert result.exit_code == 0
    assert (workdir / "evidence.json").exists()


def test_baseline_save_with_a_config_uses_its_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "from-config"
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(f"workdir: {workdir}\n")
    _runner.invoke(app, ["seed", "--workdir", str(workdir)])
    _runner.invoke(app, ["probe", "--workdir", str(workdir)])
    result = _runner.invoke(app, ["baseline", "--save", "--config", str(config_path)])
    assert result.exit_code == 0
    assert (workdir / "baseline.json").exists()


def test_probe_with_max_concurrency_and_isolated_config_yields_no_findings(
    tmp_path: Path,
) -> None:
    """An isolated config runs to completion under --max-concurrency 4."""
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(
        "adapters:\n"
        "  vector_store: {kind: fake, shared_index: false}\n"
        "  cache: {kind: fake, tenant_scoped: true}\n"
        "  model: {kind: fake}\n"
        "  mcp: {kind: fake}\n"
        "  memory: {kind: fake}\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app,
        [
            "probe",
            "--config",
            str(config_path),
            "--workdir",
            str(tmp_path),
            "--max-concurrency",
            "4",
        ],
    )
    assert result.exit_code == 0
    run = json.loads((tmp_path / "run.json").read_text())
    assert run["metrics"]["confirmed_findings"] == 0


def test_probe_rejects_max_concurrency_below_one(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--max-concurrency", "0"])
    assert result.exit_code == 3


def test_probe_with_max_concurrency_still_exits_two_against_the_demo(tmp_path: Path) -> None:
    """The leaky demo + concurrent execution still surfaces confirmed leaks.

    Finding counts may vary across runs because mutating probes (Class 3 vector
    upsert, Class 8 memory write, Class 9 model train) interleave with reading
    probes nondeterministically; the exit code is the stable contract.
    """
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--max-concurrency", "4"])
    assert result.exit_code == 2


def test_probe_single_probe_filter_runs_serially_under_max_concurrency(tmp_path: Path) -> None:
    """A --probe filter that selects a single probe stays serial regardless of
    --max-concurrency (the thread pool is only worth its overhead for suite > 1).
    """
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app,
        [
            "probe",
            "--workdir",
            str(tmp_path),
            "--probe",
            "agent-tool-hijack",
            "--max-concurrency",
            "4",
        ],
    )
    # the single-probe filter + concurrent flag still completes without error
    assert result.exit_code == 2
    run = json.loads((tmp_path / "run.json").read_text())
    assert set(run["probe_versions"]) == {"agent-tool-hijack"}


def test_probe_output_json_emits_a_parseable_summary_on_stdout(tmp_path: Path) -> None:
    """--output json emits a single JSON object on stdout that a CI pipeline can parse."""
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--output", "json"])
    # the leaky demo still exits 2 on confirmed findings; --output toggles the rendering
    assert result.exit_code == 2
    summary = json.loads(result.stdout)
    assert summary["run_id"].startswith("run-")
    # the full suite + the KV timing probe = 12 entries
    assert summary["probe_count"] == 12
    assert summary["confirmed_findings"] > 0
    assert summary["retrieval_pivot_rate"] is not None
    assert summary["run_path"].endswith("run.json")
    # the per-probe count must agree with run.json's metrics block
    run = json.loads(Path(summary["run_path"]).read_text())
    assert summary["per_probe_findings"] == run["metrics"]["per_probe_findings"]


def test_probe_output_text_is_the_default(tmp_path: Path) -> None:
    """No --output flag still produces the human-readable rendering, not JSON."""
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code == 2
    # the human-readable rendering is not parseable as a single JSON object
    assert "ran " in result.stdout
    assert "run recorded -> " in result.stdout


def test_probe_output_json_rejects_an_unknown_value(tmp_path: Path) -> None:
    """Typer/Click rejects an --output value outside the enum and exits non-zero."""
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--output", "yaml"])
    # invalid enum value -> Click usage error (exit 2 from Click's parser)
    assert result.exit_code != 0
    # nothing on disk gets written because the parser rejected the args before the command body
    assert not (tmp_path / "run.json").exists()


def test_headline_rpr_counts_a_pipeline_bleed_only_leak() -> None:
    # End-to-end C3 guard: a run where ONLY the rag-pipeline-bleed probe surfaced
    # a leak must yield a non-zero headline Retrieval-Pivot Rate. The old filter
    # (entity-bleed only) excluded the pipeline-bleed step and read 0%. Builds the
    # 2-tuple StepResults the runner produces and replicates app.py's bleed filter.
    from uuid import UUID

    from sectum_ai.cli.app import BLEED_PROBE_IDS
    from sectum_ai.probes import RagEntityBleedProbe, RagPipelineBleedProbe
    from sectum_ai.runner import retrieval_pivot_rate
    from sectum_ai.spec import Finding, FindingStatus, ProbeStep, Severity, Surface

    tenant_a, tenant_b = UUID(int=0xA), UUID(int=0xB)

    def _step(probe_id: str) -> ProbeStep:
        return ProbeStep(
            step_id=f"s-{probe_id}",
            probe_id=probe_id,
            actor_tenant_id=tenant_a,
            action="rag.ask",
            payload={"query": "q"},
        )

    leak = Finding(
        finding_id="f-pipeline",
        probe_id=RagPipelineBleedProbe.id,
        severity=Severity.HIGH,
        confidence=1.0,
        status=FindingStatus.CONFIRMED,
        owner_tenant_id=tenant_b,
        observed_in_tenant_id=tenant_a,
        surface=Surface.RAG_PIPELINE,
    )
    # StepResult is (ProbeStep, list[Finding]); entity-bleed step found nothing,
    # pipeline-bleed step found the leak.
    step_results = [
        (_step(RagEntityBleedProbe.id), []),
        (_step(RagPipelineBleedProbe.id), [leak]),
    ]
    bleed_steps = [r for r in step_results if r[0].probe_id in BLEED_PROBE_IDS]
    # both probes counted -> 1 of 2 leaked -> 0.5; entity-only would read 0.0.
    assert retrieval_pivot_rate(bleed_steps) > 0


def test_verify_requires_an_anchor_by_default(tmp_path: Path) -> None:
    # A local-dev pack is integrity-only (its token is reproducible by anyone),
    # so without --allow-unanchored the CLI refuses to call it verified: exit 4
    # and a failing independent-anchor check naming the missing anchor.
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["verify", str(tmp_path / "evidence.json")])
    assert result.exit_code == 4
    assert "independent-anchor" in result.output
