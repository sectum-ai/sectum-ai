"""Tests for the ``sectum-ai erasure`` CLI command (Class 11, the wedge)."""

from pathlib import Path

from typer.testing import CliRunner

from sectum_ai.cli.app import app

_runner = CliRunner()


def test_erasure_is_verified_against_a_hard_deleting_store(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    assert "ERASURE VERIFIED" in result.output
    assert (tmp_path / "erasure-evidence.json").exists()
    assert (tmp_path / "erasure-attestation.pdf").read_bytes().startswith(b"%PDF")


def test_erasure_fails_against_a_soft_deleting_store(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path), "--soft-delete"])
    assert result.exit_code == 2
    assert "ERASURE FAILED" in result.output


def test_erasure_attestation_verifies(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["erasure", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app,
        [
            "verify",
            str(tmp_path / "erasure-evidence.json"),
            "--allow-unanchored",
            "--allow-synthetic",
        ],
    )
    assert result.exit_code == 0
    assert "INTEGRITY OK - UNANCHORED" in result.output


def test_erasure_rejects_an_unknown_tenant(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app, ["erasure", "--workdir", str(tmp_path), "--target-tenant", "Nonexistent"]
    )
    assert result.exit_code == 3


def test_erasure_with_a_config_uses_its_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "from-config"
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(f"workdir: {workdir}\n")
    _runner.invoke(app, ["seed", "--workdir", str(workdir)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path)])
    assert result.exit_code == 0
    assert (workdir / "erasure-evidence.json").exists()


def test_erasure_uses_the_configs_soft_delete_setting(tmp_path: Path) -> None:
    """A config with soft-delete fakes drives the erasure failure (exit 2)."""
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(
        f"workdir: {tmp_path}\n"
        "adapters:\n"
        "  vector_store: {kind: fake, soft_delete: true}\n"
        "  observability: {kind: fake, soft_delete: true}\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path)])
    assert result.exit_code == 2
    assert "ERASURE FAILED" in result.output


def test_erasure_honors_only_observability_soft_delete_from_config(tmp_path: Path) -> None:
    """Asymmetric soft-delete: vector hard-deletes; only observability leaves residue."""
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(
        f"workdir: {tmp_path}\n"
        "adapters:\n"
        "  vector_store: {kind: fake, soft_delete: false}\n"
        "  observability: {kind: fake, soft_delete: true}\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path)])
    # the observability soft-delete drives the failure (the vector surface erased fine)
    assert result.exit_code == 2
    assert "ERASURE FAILED" in result.output


def test_erasure_attestable_with_caveat_when_observability_has_no_erasure_api(
    tmp_path: Path,
) -> None:
    """A no-erasure observability backend is a caveat, not a flat failure.

    The data genuinely remains (exit 2, never a clean PASS), but the operator
    message must say ATTESTABLE WITH CAVEAT - distinct from the bare 'ERASURE
    FAILED' a soft-delete (residual) surface produces - spec §7 #8.
    """
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(
        f"workdir: {tmp_path}\n"
        "adapters:\n"
        "  vector_store: {kind: fake, soft_delete: false}\n"
        "  observability: {kind: fake, no_erasure: true}\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path)])
    assert result.exit_code == 2
    assert "ATTESTABLE WITH CAVEAT" in result.output
    # it is NOT misreported as a flat erasure failure
    assert "ERASURE FAILED" not in result.output
    # the surface verdict line reflects the caveat too
    assert "-> ATTESTABLE WITH CAVEAT" in result.output
    # and the signed evidence pack keeps the caveat out of the residue metric:
    # tracing lands in erasure_caveats, not erasure_residue (which would
    # otherwise conflate it with a failure in the pack + the baseline diff).
    import json

    pack = json.loads((tmp_path / "erasure-evidence.json").read_text())
    metrics = pack["run_result"]["metrics"]
    assert metrics["erasure_caveats"].get("tracing", 0) > 0
    assert "tracing" not in metrics["erasure_residue"]


def test_erasure_reports_the_memory_surface(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    # the run scans and reports the agent-memory surface alongside vector/tracing
    assert "agent_memory:" in result.output


def test_erasure_honors_only_memory_soft_delete_from_config(tmp_path: Path) -> None:
    """Asymmetric soft-delete: only the memory surface leaves residue."""
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(
        f"workdir: {tmp_path}\n"
        "adapters:\n"
        "  vector_store: {kind: fake, soft_delete: false}\n"
        "  observability: {kind: fake, soft_delete: false}\n"
        "  memory: {kind: fake, soft_delete: true}\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path)])
    assert result.exit_code == 2
    assert "ERASURE FAILED" in result.output


def test_erasure_reports_the_cache_surface(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    # the run scans and reports the semantic-cache surface too
    assert "semantic_cache:" in result.output


def test_erasure_honors_only_cache_soft_delete_from_config(tmp_path: Path) -> None:
    """Asymmetric soft-delete: only the cache surface leaves residue."""
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(
        f"workdir: {tmp_path}\n"
        "adapters:\n"
        "  vector_store: {kind: fake, soft_delete: false}\n"
        "  observability: {kind: fake, soft_delete: false}\n"
        "  memory: {kind: fake, soft_delete: false}\n"
        "  cache: {kind: fake, soft_delete: true}\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path)])
    assert result.exit_code == 2
    assert "ERASURE FAILED" in result.output


def test_erasure_reports_the_model_surface(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    # the run scans and reports the model/fine-tune-adapter surface too
    assert "model_adapter:" in result.output


def test_erasure_honors_only_model_soft_delete_from_config(tmp_path: Path) -> None:
    """Asymmetric soft-delete: only the model surface leaves residue."""
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(
        f"workdir: {tmp_path}\n"
        "adapters:\n"
        "  vector_store: {kind: fake, soft_delete: false}\n"
        "  observability: {kind: fake, soft_delete: false}\n"
        "  memory: {kind: fake, soft_delete: false}\n"
        "  cache: {kind: fake, soft_delete: false}\n"
        "  model: {kind: fake, soft_delete: true}\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path)])
    assert result.exit_code == 2
    assert "ERASURE FAILED" in result.output


def test_erasure_warns_when_soft_delete_is_combined_with_config(tmp_path: Path) -> None:
    """--soft-delete is ignored when --config is given; a warning is emitted."""
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(f"workdir: {tmp_path}\n")
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path), "--soft-delete"])
    # --soft-delete is dropped, so the run uses the config's default (hard-delete fake)
    # and exits 0; the warning tells the user the flag was ignored
    assert result.exit_code == 0
    assert "--soft-delete is ignored" in result.output


def test_erasure_itemizes_a_caveat_alongside_a_genuine_residual(tmp_path: Path) -> None:
    """A genuine residual (soft-delete) and a caveat (no-erasure-API) can
    co-exist; the dominant failure must not hide the caveat - both are reported
    so a DPO sees every surface that still holds data (exit 2)."""
    config_path = tmp_path / "sectum-ai.yaml"
    config_path.write_text(
        f"workdir: {tmp_path}\n"
        "adapters:\n"
        "  vector_store: {kind: fake, soft_delete: true}\n"
        "  observability: {kind: fake, no_erasure: true}\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--config", str(config_path)])
    assert result.exit_code == 2
    # the dominant genuine failure is reported ...
    assert "ERASURE FAILED" in result.output
    # ... and the co-existing caveat surface is still itemized, not hidden
    assert "also attestable-with-caveat" in result.output
    assert "tracing" in result.output


def test_erasure_records_a_coverage_block_for_every_surface(tmp_path: Path) -> None:
    """The signed evidence pack carries a per-surface coverage verdict for every
    erasure surface - the honest, anti-over-claim record."""
    import json

    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    pack = json.loads((tmp_path / "erasure-evidence.json").read_text())
    coverage = pack["run_result"]["metrics"]["erasure_coverage"]
    # Every erasure surface has a verdict; on the default all-hard-delete run they
    # are all ERASED (no surface implied without being scanned).
    expected_surfaces = {
        "vector_db",
        "tracing",
        "agent_memory",
        "semantic_cache",
        "model_adapter",
        "search_index",
        "eval_set",
        "backup",
    }
    assert set(coverage) == expected_surfaces
    assert all(verdict == "ERASED" for verdict in coverage.values())


def test_erasure_scope_restricts_the_run_and_marks_the_rest_not_covered(tmp_path: Path) -> None:
    """`--scope vector_db` verifies only the vector store; every other surface is
    NOT_COVERED in the pack and the operator output says so."""
    import json

    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path), "--scope", "vector_db"])
    assert result.exit_code == 0
    assert "ERASURE VERIFIED" in result.output
    # the operator is told what was NOT verified
    assert "NOT_COVERED" in result.output
    coverage = json.loads((tmp_path / "erasure-evidence.json").read_text())["run_result"][
        "metrics"
    ]["erasure_coverage"]
    assert coverage["vector_db"] == "ERASED"
    assert coverage["tracing"] == "NOT_COVERED"
    assert coverage["backup"] == "NOT_COVERED"
    # only the scoped surface produced a scan line
    assert "vector_db:" in result.output
    assert "tracing:" not in result.output


def test_erasure_scope_accepts_multiple_surfaces(tmp_path: Path) -> None:
    import json

    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app, ["erasure", "--workdir", str(tmp_path), "--scope", "vector_db,tracing"]
    )
    assert result.exit_code == 0
    coverage = json.loads((tmp_path / "erasure-evidence.json").read_text())["run_result"][
        "metrics"
    ]["erasure_coverage"]
    assert coverage["vector_db"] == "ERASED"
    assert coverage["tracing"] == "ERASED"
    assert coverage["agent_memory"] == "NOT_COVERED"


def test_erasure_rejects_an_unknown_scope_surface(tmp_path: Path) -> None:
    """An unknown --scope surface is a ConfigError (exit 3), not a silent no-op."""
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app, ["erasure", "--workdir", str(tmp_path), "--scope", "vector_db,not_a_surface"]
    )
    assert result.exit_code == 3
    assert "not_a_surface" in result.output
    # the error lists the valid surfaces so an operator can fix the typo
    assert "valid surfaces" in result.output


def test_erasure_rejects_an_empty_scope(tmp_path: Path) -> None:
    """A --scope that names no surfaces (e.g. just commas) is a config error."""
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path), "--scope", ", ,"])
    assert result.exit_code == 3


def test_erasure_scoped_pack_still_verifies(tmp_path: Path) -> None:
    """A scoped (snapshot) attestation is a fully valid, tamper-evident pack."""
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["erasure", "--workdir", str(tmp_path), "--scope", "vector_db"])
    result = _runner.invoke(
        app,
        [
            "verify",
            str(tmp_path / "erasure-evidence.json"),
            "--allow-unanchored",
            "--allow-synthetic",
        ],
    )
    assert result.exit_code == 0
    assert "INTEGRITY OK - UNANCHORED" in result.output
