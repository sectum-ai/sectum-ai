"""Tests for the ``sectum`` evidence-pipeline CLI commands."""

import json
from pathlib import Path

from typer.testing import CliRunner

from sectum.cli.app import app
from sectum.spec import RunMetrics

_runner = CliRunner()


def _seed_and_probe(workdir: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(workdir)])
    _runner.invoke(app, ["probe", "--workdir", str(workdir)])


def test_seed_writes_a_substrate(tmp_path: Path) -> None:
    result = _runner.invoke(app, ["seed", "--workdir", str(tmp_path), "--seed", "2026"])
    assert result.exit_code == 0
    substrate = json.loads((tmp_path / "substrate.json").read_text())
    assert substrate["tenants"]
    assert substrate["documents"]


def test_seed_reads_workdir_and_seed_from_a_config(tmp_path: Path) -> None:
    workdir = tmp_path / "from-config"
    config_path = tmp_path / "sectum.yaml"
    config_path.write_text(f"scenario:\n  seed: 1\nworkdir: {workdir}\n")
    result = _runner.invoke(app, ["seed", "--config", str(config_path)])
    assert result.exit_code == 0
    assert (workdir / "substrate.json").exists()


def test_seed_explicit_flag_overrides_a_config_value(tmp_path: Path) -> None:
    config_workdir = tmp_path / "from-config"
    explicit_workdir = tmp_path / "from-flag"
    config_path = tmp_path / "sectum.yaml"
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
    assert run["metrics"]["confirmed_findings"] > 0
    assert run["metrics"]["retrieval_pivot_rate"] is not None


def test_probe_with_an_isolated_config_yields_no_findings(tmp_path: Path) -> None:
    """A config with non-leaky fakes produces zero confirmed cross-tenant findings."""
    config_path = tmp_path / "sectum.yaml"
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
    # a baseline taken from a then-clean stack: no leaks, no retrieval pivot
    (tmp_path / "baseline.json").write_text(
        RunMetrics(confirmed_findings=0, retrieval_pivot_rate=0.0).model_dump_json()
    )
    result = _runner.invoke(app, ["baseline", "--workdir", str(tmp_path), "--compare"])
    assert result.exit_code == 2
    assert "REGRESSION" in result.output


def test_baseline_compare_without_a_saved_baseline_fails(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    result = _runner.invoke(app, ["baseline", "--workdir", str(tmp_path), "--compare"])
    assert result.exit_code == 3


def test_report_builds_an_evidence_pack_and_pdf(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    result = _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "evidence.json").exists()
    assert (tmp_path / "audit-pack.pdf").read_bytes().startswith(b"%PDF")


def test_verify_passes_for_a_freshly_built_pack(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["verify", str(tmp_path / "evidence.json")])
    assert result.exit_code == 0
    assert "VERIFIED" in result.output


def test_verify_fails_on_a_tampered_pack(tmp_path: Path) -> None:
    _seed_and_probe(tmp_path)
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    evidence_path = tmp_path / "evidence.json"
    pack = json.loads(evidence_path.read_text())
    pack["run_result"]["run_id"] = "tampered"
    evidence_path.write_text(json.dumps(pack))
    result = _runner.invoke(app, ["verify", str(evidence_path)])
    assert result.exit_code == 4


def test_report_with_a_config_uses_its_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "from-config"
    config_path = tmp_path / "sectum.yaml"
    config_path.write_text(f"workdir: {workdir}\n")
    _runner.invoke(app, ["seed", "--workdir", str(workdir)])
    _runner.invoke(app, ["probe", "--workdir", str(workdir)])
    result = _runner.invoke(app, ["report", "--config", str(config_path)])
    assert result.exit_code == 0
    assert (workdir / "evidence.json").exists()


def test_baseline_save_with_a_config_uses_its_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "from-config"
    config_path = tmp_path / "sectum.yaml"
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
    config_path = tmp_path / "sectum.yaml"
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
