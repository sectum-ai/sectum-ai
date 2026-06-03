"""Tests for named, sellable probe suites (`sectum probe --suite`, the spec §19)."""

from pathlib import Path
from typing import Any, cast

import sectum_ai.probes as probes
from sectum_ai.cli.app import app
from sectum_ai.spec import RunResult
from sectum_ai.suites import SUITES
from typer.testing import CliRunner

_runner = CliRunner()


def _catalog_probe_ids() -> set[str]:
    ids: set[str] = set()
    for name in probes.__all__:
        obj = getattr(probes, name)
        if isinstance(obj, type) and getattr(obj, "id", None) and hasattr(obj, "owasp_llm"):
            ids.add(cast(Any, obj).id)
    return ids


def test_every_suite_names_only_real_probes() -> None:
    catalog = _catalog_probe_ids()
    assert SUITES, "no suites defined"
    for name, suite in SUITES.items():
        unknown = set(suite.probe_ids) - catalog
        assert not unknown, f"suite {name!r} names probes not in the catalog: {sorted(unknown)}"
        assert suite.probe_ids, f"suite {name!r} is empty"
        assert suite.frameworks, f"suite {name!r} declares no compliance frameworks"


def test_suite_runs_exactly_its_probe_set(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app, ["probe", "--workdir", str(tmp_path), "--suite", "soc2-tenant-isolation"]
    )
    assert result.exit_code in (0, 2)  # 2 == confirmed leaks on the leaky demo default
    run = RunResult.model_validate_json((tmp_path / "run.json").read_text())
    spec = SUITES["soc2-tenant-isolation"]
    expected = set(spec.probe_ids) | ({"kv-cache-timing"} if spec.include_kv_timing else set())
    assert set(run.probe_versions) == expected
    # the curated SOC 2 set deliberately omits the extraction/poisoning probes
    assert "ikea-extraction" not in run.probe_versions
    assert "rag-poisoning" not in run.probe_versions


def test_unknown_suite_is_a_usage_error(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(app, ["probe", "--workdir", str(tmp_path), "--suite", "nope"])
    assert result.exit_code == 3
    assert "unknown suite" in result.output


def test_probe_and_suite_are_mutually_exclusive(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    result = _runner.invoke(
        app,
        [
            "probe",
            "--workdir",
            str(tmp_path),
            "--probe",
            "tenant-boundary-fetch",
            "--suite",
            "owasp-llm08",
        ],
    )
    assert result.exit_code == 3
    assert "at most one" in result.output
