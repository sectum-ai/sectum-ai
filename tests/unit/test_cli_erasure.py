"""Tests for the ``sectum-ai erasure`` CLI command (Class 11, the wedge)."""

import json
from pathlib import Path

import pytest
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


def test_the_erasure_attestation_records_surface_provenance(tmp_path: Path) -> None:
    """The erasure path built its run record without the provenance block.

    Its packs therefore said "predates surface provenance" while stamped with the
    schema that carries it, and the audit PDF printed that sentence as fact - the
    one deliverable whose whole point is saying what it ran against.
    """
    import json

    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app, ["erasure", "--workdir", str(tmp_path), "--target-tenant", "Acme Robotics"]
    )
    assert result.exit_code == 0, result.output
    pack = json.loads((tmp_path / "erasure-evidence.json").read_text())
    provenance = pack["run_result"]["surface_provenance"]
    assert len(provenance) == 8, provenance
    assert set(provenance.values()) == {"SYNTHETIC"}
    # The tenant path now says so on stderr, as the subject path always did.
    assert "no live adapter configured for every surface" in result.output
    verified = _runner.invoke(
        app,
        [
            "verify",
            str(tmp_path / "erasure-evidence.json"),
            "--allow-unanchored",
            "--allow-synthetic",
        ],
    )
    assert verified.exit_code == 0, verified.output
    assert "predates" not in verified.output
    assert "NO surface was live" in verified.output


def test_a_scoped_erasure_records_provenance_for_the_scanned_surfaces_only(
    tmp_path: Path,
) -> None:
    # `--scope vector_db` says nothing about the other seven surfaces, live or not.
    import json

    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app,
        [
            "erasure",
            "--workdir",
            str(tmp_path),
            "--target-tenant",
            "Acme Robotics",
            "--scope",
            "vector_db",
        ],
    )
    assert result.exit_code == 0, result.output
    pack = json.loads((tmp_path / "erasure-evidence.json").read_text())
    assert set(pack["run_result"]["surface_provenance"]) == {"vector_db"}


def test_erasure_that_could_not_establish_absence_is_inconclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A marker still stored but ranked below the similarity page is invisible to
    # the scan and looks exactly like a purged one. The run must say so rather
    # than sign ERASURE VERIFIED, and the reason has to reach the operator: "0
    # after" on its own reads as a purge.
    from sectum_ai.adapters import FakeVectorStore
    from sectum_ai.probes.erasure import probe as erasure_probe

    erased: list[bool] = []
    real_delete = FakeVectorStore.delete

    def _delete(self: FakeVectorStore, tenant: object) -> None:
        real_delete(self, tenant)  # type: ignore[arg-type]
        erased.append(True)

    # Present before the purge, then neither found nor ruled out: every page
    # comes back full without the marker, which a still-stored one produces too.
    monkeypatch.setattr(FakeVectorStore, "delete", _delete)
    monkeypatch.setattr(
        erasure_probe.ErasureProbe,
        "_marker_observable",
        lambda self, target, marker: None if erased else True,
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path), "--scope", "vector_db"])
    assert result.exit_code == 3, result.output
    assert "ERASURE VERIFIED" not in result.output
    assert "ERASURE INCONCLUSIVE" in result.output
    # The summary must name the reason, not fall through to the "no baseline"
    # wording - there WAS a baseline; what failed is establishing absence.
    assert "could not establish that the tenant's markers are absent" in result.output, (
        result.output
    )
    assert "no baseline on" not in result.output
    # And the per-surface line says why "0 after" is not a purge.
    assert "-> NOT VERIFIED" in result.output
    assert "full similarity page" in result.output


def test_erasure_honours_a_configured_app_adapter(tmp_path: Path) -> None:
    # `erasure` read `vector_store` directly while `probe` resolves the same slot
    # from `app` too, so a config carrying only `app` built a clean DEFAULT fake:
    # the run dropped that adapter's soft_delete knob and attested ERASURE
    # VERIFIED against a backend the operator never configured.
    config = tmp_path / "sectum-ai.yaml"
    config.write_text(
        "workdir: " + str(tmp_path) + "\nadapters:\n  app:\n    kind: fake\n    soft_delete: true\n"
    )
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path), "--config", str(config)])
    result = _runner.invoke(
        app,
        ["erasure", "--workdir", str(tmp_path), "--config", str(config), "--scope", "vector_db"],
    )
    assert "ERASURE VERIFIED" not in result.output, result.output
    assert "RESIDUAL DATA" in result.output, result.output
    assert result.exit_code == 2


def test_soft_delete_reaches_the_vector_store(tmp_path: Path) -> None:
    # The `--soft-delete` flag rides on the default adapter config. A shared
    # vector-slot builder that made its OWN default dropped it, so the surface the
    # whole demo is about attested ERASED on a run explicitly modelling a store
    # that fails erasure - and the shipped residual-data sample could no longer be
    # regenerated from its own documented recipe.
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path), "--soft-delete"])
    assert "vector_db: 2 markers before, 2 after -> RESIDUAL DATA" in result.output, result.output
    assert "ERASURE FAILED" in result.output
    assert result.exit_code == 2


def test_a_surface_with_no_baseline_records_no_residue_count(tmp_path: Path) -> None:
    # The other way to establish nothing. A surface with no pre-erasure baseline
    # wrote `erasure_residue: 0` - a number the run never measured - and `diff`
    # read the drop from a prior run's 2 as a leak that had been fixed, which is
    # exactly what the guard beside it exists to stop.
    from sectum_ai.adapters import FakeVectorStore

    monkeypatch = pytest.MonkeyPatch()
    # A store that was never seeded: no baseline on the vector surface.
    monkeypatch.setattr(FakeVectorStore, "query", lambda self, tenant, text, k=5, **kw: [])
    try:
        _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
        result = _runner.invoke(
            app, ["erasure", "--workdir", str(tmp_path), "--scope", "vector_db"]
        )
    finally:
        monkeypatch.undo()
    assert result.exit_code == 3, result.output
    run = json.loads((tmp_path / "erasure-evidence.json").read_text())["run_result"]
    assert run["metrics"]["erasure_residue"] == {}, run["metrics"]["erasure_residue"]
    assert run["metrics"]["erasure_coverage"]["vector_db"] == "NOT_COVERED"


def test_erasure_records_provenance_for_a_configured_app_adapter(tmp_path: Path) -> None:
    # An `app` adapter fills the vector SLOT but declares Surface.API, so its
    # provenance was keyed `api` while the erasure report speaks of `vector_db` -
    # and the "only the surfaces this run scanned" filter then dropped it,
    # leaving the block EMPTY. `verify` read that as "the run records no surface
    # provenance (it predates the block)" on a pack stamped 0.7.0.
    config = tmp_path / "sectum-ai.yaml"
    config.write_text("workdir: " + str(tmp_path) + "\nadapters:\n  app:\n    kind: fake\n")
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path), "--config", str(config)])
    _runner.invoke(
        app,
        ["erasure", "--workdir", str(tmp_path), "--config", str(config), "--scope", "vector_db"],
    )
    run = json.loads((tmp_path / "erasure-evidence.json").read_text())["run_result"]
    assert run["surface_provenance"] == {"vector_db": "SYNTHETIC"}, run["surface_provenance"]


def test_an_inconclusive_surface_reports_the_backend_s_own_reason(tmp_path: Path) -> None:
    # The verdict was right and the REASON was fiction: both messages hard-coded
    # the vector store's "full similarity page", while a capped search-index,
    # eval-set, memory or trace listing never ran a similarity query - and the
    # adapter's own message, which names the actual cap and count, was discarded.
    from sectum_ai.adapters import FakeObservability
    from sectum_ai.spec import AdapterError

    def _refuse(self: object, tenant: object, marker: object) -> list[object]:
        raise AdapterError("Datadog listed 1000 traces, its page cap, so a miss is not absence")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(FakeObservability, "search_traces", _refuse)
    try:
        _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
        result = _runner.invoke(app, ["erasure", "--workdir", str(tmp_path), "--scope", "tracing"])
    finally:
        monkeypatch.undo()
    assert "its page cap" in result.output, result.output
    assert "full similarity page" not in result.output
    assert result.exit_code == 3
