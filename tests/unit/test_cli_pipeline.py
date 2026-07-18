"""Tests for the ``sectum`` evidence-pipeline CLI commands."""

import json
from pathlib import Path
from uuid import UUID

import pytest
from typer.testing import CliRunner

from sectum_ai.cli.app import _resolve_timestamper, _resolve_transparency_log, app
from sectum_ai.config import EvidenceConfig
from sectum_ai.evidence import RekorTransparencyLog, Rfc3161Timestamper
from sectum_ai.spec import RunMetrics, RunResult, SyntheticUserSpec

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


def test_probe_text_output_renders_a_clean_zero_rate_on_an_isolated_stack(tmp_path: Path) -> None:
    # On an isolated stack the bleed probes still run (n=48) but confirm nothing (k=0), so the
    # flagship RPR is a measured 0.0% - falsy but not None. The text summary must still show it
    # (with its CI and n) and the Class-3/6/10 rates; a truthiness guard would drop exactly the
    # passing-run headline, rendering a proven-isolated stack the same as one Class 2 never ran
    # on. The other text-output test uses the leaky demo (RPR > 0), so nothing else pins 0.0.
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
    assert result.exit_code == 0
    assert "retrieval-pivot rate: 0.0% (95% CI 0.0%-7.4%, n=48)" in result.output
    assert "poisoning bleed delta: 0%" in result.output
    assert "inversion reconstruction rate: 0%" in result.output
    assert "extraction efficiency: 0%" in result.output


def test_probe_without_a_seeded_substrate_fails_cleanly(tmp_path: Path) -> None:
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code == 3


def test_probe_can_run_a_single_probe(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app, ["probe", "--workdir", str(tmp_path), "--probe", "agent-tool-hijack"]
    )
    assert result.exit_code == 2
    # A single-probe run says "probe", not "probes" - the plural keys on the count.
    assert "ran 1 probe:" in result.output
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


def test_baseline_compare_does_not_let_a_record_forge_its_verdict(tmp_path: Path) -> None:
    # The last surface in the family. `baseline --compare` renders finding ids straight
    # off the records it compares, so a newline in one forged `baseline`'s OWN success
    # sentinel on stdout - and the real "BASELINE REGRESSION" banner goes to stderr, so a
    # stdout-capturing CI log showed a regressed run reporting no regression.
    _seed_and_probe(tmp_path)
    run = RunResult.model_validate_json((tmp_path / "run.json").read_text())
    clean = run.model_copy(update={"findings": (), "metrics": RunMetrics(confirmed_findings=0)})
    (tmp_path / "baseline.json").write_text(clean.model_dump_json())
    forged = "no regression against the baseline"
    leaked = run.findings[0].model_copy(update={"finding_id": f"f00d\n{forged}"})
    (tmp_path / "run.json").write_text(
        run.model_copy(update={"findings": (leaked,)}).model_dump_json()
    )
    result = _runner.invoke(app, ["baseline", "--workdir", str(tmp_path), "--compare"])
    assert result.exit_code == 2
    assert not any(line.strip() == forged for line in result.stdout.splitlines())
    assert "\\x0a" in result.stdout


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


def test_probe_with_a_serving_only_model_skips_class_9(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # End to end: a serving-only model (vLLM/TGI) trains no per-tenant adapter, so
    # `probe` must skip Class 9 (lora-cross-tenant) and still complete — including
    # driving Class 5 KV-cache timing against it. Inject one without a live SDK by
    # stubbing the model builder; the rest of the demo bundle is unchanged.
    import sectum_ai.cli.app as app_mod
    import sectum_ai.config as config_mod
    from sectum_ai.adapters.model.vllm import VLLMModel

    class _FakeServingBackend:
        def complete(self, prompt: str) -> str:
            return ""  # completion only, never an echo of the prompt

        def first_token_latency_ms(self, prompt: str) -> float:
            return 5.0

    def _serving_model(_config: object) -> VLLMModel:
        return VLLMModel(_FakeServingBackend())

    # build_adapters (config) builds the suite model; the probe command builds a
    # fresh KV-timing model via the app-level name — patch both to the serving stub.
    monkeypatch.setattr(config_mod, "build_model", _serving_model)
    monkeypatch.setattr(app_mod, "build_model", _serving_model)

    assert _runner.invoke(app, ["seed", "--workdir", str(tmp_path)]).exit_code == 0
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    # The demo's other surfaces still leak, so the run completes with exit 2.
    assert result.exit_code == 2, result.output
    versions = json.loads((tmp_path / "run.json").read_text())["probe_versions"]
    assert "lora-cross-tenant" not in versions  # gated out: a serving model can't train
    assert "tenant-boundary-fetch" in versions  # the rest of the suite still ran


def test_score_grades_the_leaky_demo_run_and_shows_its_coverage(tmp_path: Path) -> None:
    # The demo substrate is deliberately leaky, so the graded posture must be F - and
    # the letter must say *why* (a confirmed critical failure), not just assert itself.
    _seed_and_probe(tmp_path)
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    assert "GRADE F" in result.output
    # The cap keys on the failing CLASS's weight band, never on a finding's severity -
    # the wording must not invite the reader to recompute from finding.severity.
    assert "capped by a failing critical-band class" in result.output
    # Every class is listed - including the ones that never ran. (The per-row content is
    # pinned by test_score_renders_a_row_per_class_with_its_verdict_and_band; a bare
    # substring check here left 10 of 11 rows droppable.)
    assert "NOT_COVERED" in result.output
    # The methodology is cited, so a reader can recompute the letter.
    assert "docs/scorecard.md" in result.output
    assert "Untested classes lower confidence, never the grade." in result.output
    # The rendered numbers ARE the scorecard, and docs/scorecard.md reproduces this block
    # verbatim. Greping only for the letter let a swapped covered/total or
    # weighted/coverage print a plausible, wrong posture, so pin the exact strings.
    assert "10/11 classes covered" in result.output  # Class 13 needs a multimodal adapter
    assert "weighted 0.00 over the covered classes; coverage 0.88." in result.output


def test_score_output_json_emits_a_parseable_isolation_score(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["grade"] == "F"
    assert payload["capped_by"] == "critical"
    assert payload["methodology_version"] == "1.0"  # pinned; see docs/scorecard.md
    # The demo leaks on every surface it exercised, so the covered classes all fail.
    assert payload["weighted_score"] == 0.0
    assert payload["coverage"] == pytest.approx(36 / 41, abs=5e-3)
    # k/n-style transparency: every catalog class appears, verdicts included.
    assert payload["classes_total"] == len(payload["classes"])
    assert {c["verdict"] for c in payload["classes"]} == {"FAIL", "NOT_COVERED"}


def test_score_json_round_trips_into_the_isolation_score_model(tmp_path: Path) -> None:
    from sectum_ai.spec import IsolationScore

    _seed_and_probe(tmp_path)
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"])
    card = IsolationScore.model_validate_json(result.output)
    assert card.classes and card.grade.value == "F"


def test_score_on_an_isolated_stack_grades_well(tmp_path: Path) -> None:
    # The discriminating case: the same catalog against a per-tenant-namespace store
    # must NOT grade F, else the scorecard is a rubber stamp.
    config_path = tmp_path / "iso.yaml"
    config_path.write_text(
        f"workdir: {tmp_path}\nadapters:\n  vector_store:\n    kind: fake\n"
        "    shared_index: false\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path), "--config", str(config_path)])
    _runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--config", str(config_path)])
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["grade"] == "A"
    assert payload["capped_by"] is None
    assert payload["weighted_score"] == 1.0


def test_score_without_a_run_file_exits_3(tmp_path: Path) -> None:
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path)])
    assert result.exit_code == 3


def test_score_refuses_a_run_that_exercised_no_catalog_class(tmp_path: Path) -> None:
    # The documented exit-3 path (docs/scorecard.md): grading nothing would emit a letter
    # that means nothing, and F would falsely read as "failed" when the truth is "never
    # tested". Distinct from the missing-file branch above - this reaches score_run.
    _seed_and_probe(tmp_path)
    run_path = tmp_path / "run.json"
    record = json.loads(run_path.read_text())
    record["probe_versions"] = {}
    record["findings"] = []
    run_path.write_text(json.dumps(record))
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path)])
    assert result.exit_code == 3  # a ConfigError, not a ZeroDivisionError traceback
    assert "nothing to grade" in (result.output + str(result.exception or ""))


def test_score_rejects_sarif_and_oscal(tmp_path: Path) -> None:
    # SARIF/OSCAL project findings; a graded posture has no rendering in either, so the
    # command rejects them rather than silently falling through to text.
    _seed_and_probe(tmp_path)
    for fmt in ("sarif", "oscal"):
        result = _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", fmt])
        assert result.exit_code == 3, fmt


def test_score_reads_its_workdir_from_a_config(tmp_path: Path) -> None:
    workdir = tmp_path / "from-config"
    workdir.mkdir()
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(f"workdir: {workdir}\n")
    _seed_and_probe(workdir)
    result = _runner.invoke(app, ["score", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "GRADE" in result.output


@pytest.mark.parametrize(
    ("shape", "mutate"),
    [
        # One principal: the obvious case.
        ("one tenant, no users", lambda s: {"tenants": s.tenants[:1]}),
        # TWO principals, no boundary. The proxy this guard used to be - "fewer than two
        # principals" - passed this: principals() counts a tenant AND each of its users,
        # but is_cross_principal never crosses a tenant with its own users' data, so a
        # tenant with one user has two principals and nothing foreign to anybody.
        (
            "one tenant, one user",
            lambda s: {
                "tenants": (
                    s.tenants[0].model_copy(
                        update={
                            "users": (
                                SyntheticUserSpec(user_id=UUID(int=0x101), display_name="u1"),
                            )
                        }
                    ),
                )
            },
        ),
    ],
)
def test_probe_refuses_a_substrate_that_crosses_no_boundary(
    tmp_path: Path, shape: str, mutate: object
) -> None:
    # CRITICAL regression, and the precondition of the whole product: isolation is a claim
    # about a boundary BETWEEN principals, so where nothing is foreign to anyone no probe
    # can confirm a leak however broken the stack is. Probing anyway produced a GENUINE,
    # signable record of nothing - the same maximally-leaky demo stack that grades F on
    # four tenants graded A here, so the letter described the substrate, not the stack, and
    # `verify` passed it. `seed` builds four tenants, so this is reachable through a
    # supplied substrate.json - exactly the record `probe` is not entitled to trust.
    from sectum_ai.substrate import build_substrate, default_scenario

    scenario = default_scenario(seed=2026)
    degenerate = build_substrate(scenario.model_copy(update=mutate(scenario)))  # type: ignore[operator]
    (tmp_path / "substrate.json").write_text(degenerate.model_dump_json())
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code == 3, shape
    assert "no marker in this substrate is foreign" in result.output
    assert not (tmp_path / "run.json").exists()  # no record of a run that proved nothing


def _one_tenant_two_users() -> object:
    """A substrate with a genuine USER-level boundary but only one tenant (ADR-0006)."""
    from sectum_ai.substrate import build_substrate, default_scenario

    scenario = default_scenario(seed=2026)
    users = (
        SyntheticUserSpec(user_id=UUID(int=0x101), display_name="u1"),
        SyntheticUserSpec(user_id=UUID(int=0x102), display_name="u2"),
    )
    return build_substrate(
        scenario.model_copy(
            update={"tenants": (scenario.tenants[0].model_copy(update={"users": users}),)}
        )
    )


def test_probe_accepts_a_single_tenant_that_declares_users(tmp_path: Path) -> None:
    # The positive direction of the guard, and ADR-0006's whole point: a user IS an
    # isolation boundary. One tenant with two users has real boundaries to verify (each
    # user's markers are foreign to the other), so refusing it would silently drop
    # user-granularity verification - the guard must not over-refuse to be safe.
    (tmp_path / "substrate.json").write_text(_one_tenant_two_users().model_dump_json())  # type: ignore[attr-defined]
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code in (0, 2)
    assert (tmp_path / "run.json").exists()


def test_a_kv_probe_that_measured_nothing_is_not_recorded_as_having_run(tmp_path: Path) -> None:
    # A live path, not a hypothetical: the KV probe iterates TENANTS while the substrate
    # guard asks about PRINCIPALS, so one tenant with two users is rightly accepted (a real
    # user-level boundary) yet leaves the KV probe no cross-tenant pair to time. It measures
    # nothing. Recording it graded Class 5 PASS off zero measurements - rule 1 exactly.
    (tmp_path / "substrate.json").write_text(_one_tenant_two_users().model_dump_json())  # type: ignore[attr-defined]
    assert _runner.invoke(app, ["probe", "--workdir", str(tmp_path)]).exit_code in (0, 2)
    versions = json.loads((tmp_path / "run.json").read_text())["probe_versions"]
    assert "kv-cache-timing" not in versions

    payload = json.loads(
        _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"]).output
    )
    kv = next(c for c in payload["classes"] if c["class_id"] == 5)
    assert kv["verdict"] == "NOT_COVERED"


def test_a_class_starved_of_anything_to_find_is_never_a_pass(tmp_path: Path) -> None:
    # The substrate refusal is a GLOBAL existential - some marker is foreign to somebody -
    # while a vacuous PASS is PER CLASS, so a substrate can satisfy the refusal and still
    # starve one class. Demote only the HARD_CANARYs to tenant level: the entity canaries
    # stay user-owned so the run is legitimately accepted (Class 2 is real), but Classes
    # 4/8/9 have nothing foreign to plant. They used to write their canary anyway - a
    # cache.set, a model.train, a memory.write - never read it back, and grade PASS,
    # including a CRITICAL-band PASS on a maximally-leaky memory store. Rule 1 exactly:
    # the probes now plan nothing rather than plant what nobody can steal.
    from sectum_ai.spec import MarkerType

    substrate = _one_tenant_two_users()
    markers = tuple(
        marker.model_copy(update={"owner_user_id": None})
        if marker.marker_type is MarkerType.HARD_CANARY
        else marker
        for marker in substrate.manifest.markers  # type: ignore[attr-defined]
    )
    starved = substrate.model_copy(  # type: ignore[attr-defined]
        update={"manifest": substrate.manifest.model_copy(update={"markers": markers})}  # type: ignore[attr-defined]
    )
    (tmp_path / "substrate.json").write_text(starved.model_dump_json())
    assert _runner.invoke(app, ["probe", "--workdir", str(tmp_path)]).exit_code in (0, 2)
    versions = set(json.loads((tmp_path / "run.json").read_text())["probe_versions"])
    # rag-poisoning also plants against hard canaries; round 8 gated the other three
    # planters and missed it, so its Class 3 graded a vacuous PASS that lifted the letter a
    # full band (D->F). All four planters are now starved here.
    assert not versions & {
        "semantic-cache-contamination",
        "memory-contamination",
        "lora-cross-tenant",
        "rag-poisoning",
    }

    payload = json.loads(
        _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"]).output
    )
    by_id = {c["class_id"]: c for c in payload["classes"]}
    for class_id in (3, 4, 8, 9):
        assert by_id[class_id]["verdict"] == "NOT_COVERED", f"class {class_id} found nothing"


def test_probe_reports_the_probe_count_the_record_attests(tmp_path: Path) -> None:
    # The summary said "ran 12 probes" while the signed run recorded 8 - claiming coverage
    # the evidence does not carry, in the direction rule 1 exists to prevent.
    from sectum_ai.substrate import build_substrate, default_scenario

    scenario = default_scenario(seed=2026)
    (tmp_path / "substrate.json").write_text(
        build_substrate(scenario.model_copy(update={"shared_entities": ()})).model_dump_json()
    )
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--output", "json"])
    recorded = len(json.loads((tmp_path / "run.json").read_text())["probe_versions"])
    assert json.loads(result.stdout)["probe_count"] == recorded


def test_probe_refuses_before_touching_the_stack(tmp_path: Path) -> None:
    # A refused run must not have run. The refusal is checkable from its output only by
    # exit 3, the message and the absent run.json - all of which a check placed too late
    # produces identically, having already driven the stack. So spy on the stack itself.
    #
    # Both halves are load-bearing and were found the hard way. The probe steps are the
    # obvious half. The seeding upsert is the one that bit: it ran ~40 lines BEFORE the
    # refusal and, unlike the MCP/agent/RAG provisioning beside it, was not Fake-gated -
    # so `probe` exited 3 saying it would not assess this stack having already committed
    # 24 synthetic documents to the customer's real pgvector/Pinecone index, with no run
    # record to explain them and no cleanup. An earlier version of this test spied only on
    # the runner and was blind to it, asserting less than its own name claimed.
    from sectum_ai.adapters import FakeVectorStore
    from sectum_ai.runner import Runner
    from sectum_ai.substrate import build_substrate, default_scenario

    scenario = default_scenario(seed=2026)
    one = build_substrate(scenario.model_copy(update={"tenants": scenario.tenants[:1]}))
    (tmp_path / "substrate.json").write_text(one.model_dump_json())

    executed: list[str] = []
    written: list[int] = []
    run_per_step, upsert = Runner.run_per_step, FakeVectorStore.upsert

    def spy_run(self: Runner, probe: object) -> object:
        executed.append(getattr(probe, "id", "?"))
        return run_per_step(self, probe)  # type: ignore[arg-type]

    def spy_upsert(self: FakeVectorStore, tenant_id: object, documents: object) -> object:
        written.append(len(list(documents)))  # type: ignore[call-overload]
        return upsert(self, tenant_id, documents)  # type: ignore[arg-type]

    Runner.run_per_step = spy_run  # type: ignore[assignment,method-assign]
    FakeVectorStore.upsert = spy_upsert  # type: ignore[assignment,method-assign]
    try:
        result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    finally:
        Runner.run_per_step = run_per_step  # type: ignore[method-assign]
        FakeVectorStore.upsert = upsert  # type: ignore[method-assign]
    assert result.exit_code == 3
    assert not executed, f"a refused run drove probes against the stack: {executed}"
    assert not written, f"a refused run wrote {sum(written)} documents to the stack"


def test_probe_refuses_a_substrate_with_no_markers_to_find(tmp_path: Path) -> None:
    # Principals alone are not the precondition: four tenants and 48 documents still
    # verify nothing if no marker was planted. This shape is the more dangerous one - the
    # probes DO run and DO query, so Class 2 reported `0.0% RPR (95% CI 0.0%-13.8%, n=24)`:
    # a well-powered clean measurement of a question that could never have an answer.
    from sectum_ai.substrate import build_substrate, default_scenario

    substrate = build_substrate(default_scenario(seed=2026))
    unmarked = substrate.model_copy(
        update={"manifest": substrate.manifest.model_copy(update={"markers": ()})}
    )
    (tmp_path / "substrate.json").write_text(unmarked.model_dump_json())
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    assert result.exit_code == 3
    assert "no marker in this substrate is foreign" in result.output


def test_score_refuses_a_record_carrying_a_non_finite_metric(tmp_path: Path) -> None:
    # json.loads accepts a bare NaN and a hand-edited record is the expected input, so
    # this reaches canonicalization, which refuses it. Exit 3 is the documented contract;
    # it used to escape the typed-error handler as exit 1 and a raw traceback.
    _seed_and_probe(tmp_path)
    run_path = tmp_path / "run.json"
    run = json.loads(run_path.read_text())
    run["metrics"]["retrieval_pivot_rate"] = float("nan")
    run_path.write_text(json.dumps(run))
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path)])
    assert result.exit_code == 3
    assert "Traceback" not in result.output


def test_probe_records_only_the_probes_that_asked_the_stack_something(tmp_path: Path) -> None:
    # CRITICAL regression. `probe_versions` was built from SUITE MEMBERSHIP, but score.py
    # reads it as "what actually ran" (its own docstring says so) - so a probe whose plan
    # came back empty was recorded as having run, found nothing, and graded its class
    # PASS: a check the stack was never asked to perform, which is precisely what rule 1
    # exists to forbid. Four principals with no shared organic entity leaves the
    # entity-bleed probes nothing to query, while the rest of the suite still runs.
    from sectum_ai.substrate import build_substrate, default_scenario

    scenario = default_scenario(seed=2026)
    no_entities = scenario.model_copy(update={"shared_entities": ()})
    (tmp_path / "substrate.json").write_text(build_substrate(no_entities).model_dump_json())
    assert _runner.invoke(app, ["probe", "--workdir", str(tmp_path)]).exit_code in (0, 2)
    versions = set(json.loads((tmp_path / "run.json").read_text())["probe_versions"])
    # These plan zero steps with no shared entity: there is nothing organic to pivot on.
    assert not versions & {"tenant-boundary-fetch", "rag-entity-bleed", "ikea-extraction"}
    assert "agent-tool-hijack" in versions  # this one does take steps, so it stays recorded

    payload = json.loads(
        _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"]).output
    )
    by_id = {c["class_id"]: c for c in payload["classes"]}
    for class_id in (1, 2, 10):
        assert by_id[class_id]["verdict"] == "NOT_COVERED", f"class {class_id} asked nothing"
    # Rule 2: the gap lands on confidence, never on the letter.
    assert payload["confidence"] != "high"


def test_score_explicit_workdir_overrides_a_config_value(tmp_path: Path) -> None:
    # docs/configuration.md promises an explicit flag always beats the config. `seed`
    # pins that; `score` did not, and it is the command where losing lets the config
    # silently redirect the grade to a different run - a clean workdir printing A over
    # the leaky one the operator named.
    config_workdir = tmp_path / "from-config"
    explicit_workdir = tmp_path / "from-flag"
    _seed_and_probe(config_workdir)  # clean of findings only because we never probe it
    (config_workdir / "run.json").write_text(
        json.dumps({**json.loads((config_workdir / "run.json").read_text()), "findings": []})
    )
    _seed_and_probe(explicit_workdir)
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(f"workdir: {config_workdir}\n")
    result = _runner.invoke(
        app,
        ["score", "--config", str(config_path), "--workdir", str(explicit_workdir)],
    )
    assert result.exit_code == 0
    assert "GRADE F" in result.output  # the workdir named on the command line governs
    assert str(explicit_workdir) in result.output


def test_score_renders_a_row_per_class_with_its_verdict_and_band(tmp_path: Path) -> None:
    # The breakdown IS the evidence behind the letter, and only the letter was asserted.
    # Dropping every failing row, or rendering every band as a constant, left GRADE F,
    # "10/11 classes covered" and the capped-by line all intact - a scorecard that reads
    # whole while the evidence under it is gone.
    _seed_and_probe(tmp_path)
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    rows = [line for line in result.output.splitlines() if line.lstrip().startswith("Class ")]
    payload = json.loads(
        _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"]).output
    )
    assert len(rows) == payload["classes_total"] == 11
    # The text table and the JSON agree on which classes, in which order.
    assert [int(r.split()[1]) for r in rows] == [c["class_id"] for c in payload["classes"]]
    # A failing class carries its name, verdict and DECLARED band on its own row...
    boundary = next(r for r in rows if "Direct tenant boundary fetch" in r)
    assert "FAIL" in boundary and "critical" in boundary
    # ...and each band is the class's own, not one constant repeated down the column.
    assert "medium" in next(r for r in rows if "KV-cache timing" in r)
    assert "high" in next(r for r in rows if "Adversarial RAG poisoning" in r)
    # An untested class explains the gap rather than rendering an empty cell.
    assert "probe did not run" in next(r for r in rows if "NOT_COVERED" in r)
    # A COVERED class carries its measured headline rate in its own row - the quantitative
    # evidence behind the verdict. Only the NOT_COVERED note arm of the row's `detail` was
    # pinned; dropping the headline arm would blank these while the verdicts and coverage line
    # still read whole.
    assert "RPR" in next(r for r in rows if "Organic entity-bleed RAG" in r)
    assert "poisoning bleed" in next(r for r in rows if "Adversarial RAG poisoning" in r)


def test_score_renders_the_confidence_of_a_thin_run_as_low(tmp_path: Path) -> None:
    # Rule 2 lives or dies in the render: a run covering one class and a full sweep both
    # grade A, and the confidence beside the letter is the only thing telling them apart.
    # Hardcoding it to `high` over-claims exactly what rule 2 exists to prevent.
    _seed_and_probe(tmp_path)
    run_path = tmp_path / "run.json"
    run = json.loads(run_path.read_text())
    run["probe_versions"] = {"tenant-boundary-fetch": "1.0"}
    run["findings"] = []
    run_path.write_text(json.dumps(run))
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    assert "GRADE A" in result.output  # the letter is clean...
    assert "confidence: low" in result.output  # ...and says how little it rests on
    assert "1/11 classes covered" in result.output


def test_score_names_the_pack_when_it_graded_the_pack(tmp_path: Path) -> None:
    # The pack-only path is the auditor's case, and it was only ever exercised through
    # --output json, which returns before the render - so the text path could cite
    # run.json, a file that is not even present, while grading evidence.json.
    _seed_and_probe(tmp_path)
    assert _runner.invoke(app, ["report", "--workdir", str(tmp_path)]).exit_code == 0
    (tmp_path / "run.json").unlink()
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    assert "evidence.json" in result.output
    assert "run.json" not in result.output


def test_score_json_explains_every_not_covered_class(tmp_path: Path) -> None:
    # The note is *why* a class is NOT_COVERED. A machine consumer that loses it sees an
    # unexplained gap and cannot tell "no adapter satisfies it" from "nobody ran it".
    _seed_and_probe(tmp_path)
    payload = json.loads(
        _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"]).output
    )
    untested = [c for c in payload["classes"] if c["verdict"] == "NOT_COVERED"]
    assert untested
    assert all(c["note"] for c in untested)


def test_score_grades_an_evidence_pack_when_only_the_pack_is_present(tmp_path: Path) -> None:
    # The pack is the artifact an auditor actually holds, so it must be re-gradable.
    _seed_and_probe(tmp_path)
    assert _runner.invoke(app, ["report", "--workdir", str(tmp_path)]).exit_code == 0
    (tmp_path / "run.json").unlink()  # auditor received the pack only
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["grade"] == "F"


def test_score_prefers_a_fresh_run_over_a_stale_evidence_pack(tmp_path: Path) -> None:
    # REGRESSION: `probe` rewrites run.json unconditionally, but evidence.json is only as
    # fresh as the last `report`. Preferring the pack graded the STALE record - so after
    # probe/report/probe, a clean pack from the last good release hid today's regression,
    # printing an A over a failing run. run.json must win when both exist.
    _seed_and_probe(tmp_path)
    assert _runner.invoke(app, ["report", "--workdir", str(tmp_path)]).exit_code == 0
    # Rewrite the pack's embedded run as a clean, passing record from "last release".
    pack_path = tmp_path / "evidence.json"
    pack = json.loads(pack_path.read_text())
    pack["run_result"]["run_id"] = "run-LAST-GOOD-RELEASE"
    pack["run_result"]["findings"] = []
    pack_path.write_text(json.dumps(pack))
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["run_id"] != "run-LAST-GOOD-RELEASE"  # the stale pack was not graded
    assert payload["grade"] == "F"  # today's leaky run governs


def test_score_does_not_let_the_graded_record_forge_the_scorecard(tmp_path: Path) -> None:
    # The run_id is the record's own claim about itself, and the record is the thing
    # under scrutiny. Echoed raw it forged our output: a newline in run_id printed a
    # second "GRADE A" card under the real one, and \x1b[2J wiped the real letter off
    # an auditor's terminal - for a run with 229 confirmed cross-tenant leaks, at exit 0.
    _seed_and_probe(tmp_path)
    run_path = tmp_path / "run.json"
    run = json.loads(run_path.read_text())
    run["run_id"] = "run-acme\x1b[2J\x1b[H\n\nMulti-tenant isolation: GRADE A   (confidence: high)"
    run_path.write_text(json.dumps(run))
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    assert "GRADE F" in result.output  # the real letter still governs
    # The payload cannot open a line of its own.
    assert not any(
        line.lstrip().startswith("Multi-tenant isolation: GRADE A")
        for line in result.output.splitlines()
    )
    # Escaped, not stripped: the tampering is visible rather than silently swallowed.
    # This pair is the load-bearing check on ESC. Asserting `"\x1b" not in output` here
    # would be vacuous - click strips ANSI whenever stdout is not a TTY, so it passes with
    # no sanitizer at all and pins click's behaviour rather than ours. The escape reaching
    # a real terminal is pinned by test_a_run_pack_readme_..., which renders directly.
    assert "\\x1b" in result.output and "\\x0a" in result.output


def test_a_run_pack_readme_does_not_let_the_run_id_forge_it(tmp_path: Path) -> None:
    # Same defect, same fix, other surface: the pack README interpolates the record's
    # run_id into markdown an auditor reads.
    from sectum_ai.cli.app import _run_pack_readme

    readme = _run_pack_readme(
        "run-acme\x1b[2J\n\n## Verified: no cross-tenant leaks",
        sealed_manifest=False,
        has_config=False,
    )
    # `##` is only a heading at the start of a line; escaped, the payload stays inline
    # on the title line and renders as text, so assert it cannot open a line of its own.
    assert not any(line.startswith("## Verified") for line in readme.splitlines())
    assert "\\x0a" in readme
    # Parity with the scorecard, asserted rather than assumed: escaping only the newline
    # and letting ESC through passed this test until it checked for it.
    assert "\x1b" not in readme
    assert "\\x1b" in readme


def test_verify_does_not_let_a_pack_forge_its_own_anchor_claims(tmp_path: Path) -> None:
    # The worst member of the family, and the only one in the command that IS the trust
    # anchor. The pack supplies schema_version; the compatibility gate reads only the
    # major and minor, and `_attested_content` never binds the field - so text smuggled
    # after the patch digit passed the gate, was rendered raw, and printed `[ok]` lines
    # asserting the RFC 3161 and Rekor anchoring `verify` exists to establish, on an
    # unanchored local-dev pack. Signing does not help: the vendor is the signer.
    _seed_and_probe(tmp_path)
    assert _runner.invoke(app, ["report", "--workdir", str(tmp_path)]).exit_code == 0
    pack_path = tmp_path / "evidence.json"
    pack = json.loads(pack_path.read_text())
    pack["schema_version"] = (
        "0.5.0\n[ok] timestamp-token: pack digest timestamped by an RFC 3161 TSA"
        "\n[ok] rekor-inclusion: pack digest recorded in the Sigstore Rekor log"
    )
    pack_path.write_text(json.dumps(pack))
    result = _runner.invoke(app, ["verify", str(pack_path), "--allow-unanchored"])
    forged = [
        line
        for line in result.output.splitlines()
        if line.startswith("[ok] timestamp-token: pack digest timestamped by an RFC")
        or line.startswith("[ok] rekor-inclusion")
    ]
    assert not forged, f"the pack forged its own anchor claims: {forged}"


def test_verify_does_not_let_an_incompatible_pack_forge_its_anchor_claims(tmp_path: Path) -> None:
    # The incompatible-version arm of the same forgery. schema_version renders on two branches -
    # "supported" and "incompatible"; the test above exercises only the supported one (0.5.0
    # matches this verifier), so the incompatible branch's escaping was unpinned. A crafted pack
    # declaring an incompatible major.minor with `[ok]` lines smuggled after it must escape them
    # too. Verification still fails overall (incompatible version), but the forged anchor lines
    # must not print.
    _seed_and_probe(tmp_path)
    assert _runner.invoke(app, ["report", "--workdir", str(tmp_path)]).exit_code == 0
    pack_path = tmp_path / "evidence.json"
    pack = json.loads(pack_path.read_text())
    pack["schema_version"] = (
        "0.4.0\n[ok] timestamp-token: pack digest timestamped by an RFC 3161 TSA"
        "\n[ok] rekor-inclusion: pack digest recorded in the Sigstore Rekor log"
    )
    pack_path.write_text(json.dumps(pack))
    result = _runner.invoke(app, ["verify", str(pack_path), "--allow-unanchored"])
    forged = [
        line
        for line in result.output.splitlines()
        if line.startswith("[ok] timestamp-token: pack digest timestamped by an RFC")
        or line.startswith("[ok] rekor-inclusion")
    ]
    assert not forged, f"the incompatible pack forged its own anchor claims: {forged}"


def test_score_binds_its_grade_to_the_exact_record(tmp_path: Path) -> None:
    # run_id is derived from the scenario, so every run against one substrate repeats
    # it: a leaking record and a doctored clean copy grade F and A under a byte-identical
    # run_id. The digest is what identifies WHICH record earned the letter - and it is
    # the same run identifier the attestation and the audit PDF bind.
    _seed_and_probe(tmp_path)
    run_path = tmp_path / "run.json"
    leaking = json.loads(run_path.read_text())
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"])
    leaking_card = json.loads(result.output)
    assert leaking_card["grade"] == "F"

    doctored = {**leaking, "findings": []}
    run_path.write_text(json.dumps(doctored))
    clean_card = json.loads(
        _runner.invoke(app, ["score", "--workdir", str(tmp_path), "--output", "json"]).output
    )
    assert clean_card["grade"] == "A"
    assert clean_card["run_id"] == leaking_card["run_id"]  # provenance run_id cannot tell...
    assert clean_card["run_digest"] != leaking_card["run_digest"]  # ...but the digest does
    # What the digest must COVER is pinned by test_the_digest_binds_every_field_of_the_record;
    # recomputing it here with run_digest itself could not catch a digest that stopped
    # covering a field, since both sides would move together.
    assert len(clean_card["run_digest"]) == 64  # sha256 hex


def test_score_names_the_record_it_graded(tmp_path: Path) -> None:
    # A letter with no provenance invites grading the wrong run silently.
    _seed_and_probe(tmp_path)
    result = _runner.invoke(app, ["score", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    assert "run-sectum-ai-demo-2026" in result.output
    assert "run.json" in result.output
