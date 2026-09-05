"""`verify` answers what the pack is about, not only whether its bytes are intact.

Every other check in the verifier concerns the bytes - the digest recomputes, an
anchor binds it, the PDF matches its bound hash. All of them pass just as cleanly
for a run against Sectum's own in-memory fakes, so "the signature is valid" and
"this describes a real system" were unrelated facts and only the first was
checked. A third party receiving a vendor's pack is the party least able to
notice that, which is why the CLI fails closed.

The library defaults permissive and the CLI decides, matching ``require_anchored``:
the library reports, the command line sets policy.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sectum_ai.cli.app import app
from sectum_ai.evidence import build_evidence_pack, verify_pack
from sectum_ai.evidence.pdf import provenance_statement
from sectum_ai.evidence.verify import Check, VerificationResult
from sectum_ai.spec import (
    EvidencePack,
    GroundTruthManifest,
    RunResult,
    Surface,
    SurfaceProvenance,
    canonical_hash,
)

_MANIFEST = GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())

_runner = CliRunner()


def _run(provenance: dict[str, str]) -> RunResult:
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    return RunResult(
        run_id="run-test",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(_MANIFEST),
        started_at=moment,
        finished_at=moment,
        surface_provenance=provenance,
    )


def _pack(provenance: dict[str, str]) -> EvidencePack:
    return build_evidence_pack(_run(provenance), _MANIFEST)


def _scope(result: VerificationResult) -> Check:
    return next(c for c in result.checks if c.name == "run-scope")


_LIVE = {Surface.VECTOR_DB.value: SurfaceProvenance.LIVE.value}
_FAKE = {Surface.VECTOR_DB.value: SurfaceProvenance.SYNTHETIC.value}
_MIXED = {
    Surface.VECTOR_DB.value: SurfaceProvenance.LIVE.value,
    Surface.SEMANTIC_CACHE.value: SurfaceProvenance.SYNTHETIC.value,
}


def test_a_live_pack_passes_the_scope_check() -> None:
    check = _scope(verify_pack(_pack(_LIVE), require_live=True))
    assert check.ok
    assert "live backend" in check.detail


def test_an_all_synthetic_pack_is_refused_when_live_is_required() -> None:
    result = verify_pack(_pack(_FAKE), require_live=True)
    assert not result.passed
    check = _scope(result)
    assert not check.ok
    assert "NO surface was live" in check.detail


def test_the_library_defaults_permissive_like_require_anchored() -> None:
    # The library reports and the CLI sets policy; a library default that refused
    # would make every programmatic verification of a demo pack fail.
    result = verify_pack(_pack(_FAKE))
    assert result.passed
    # Still reported - the check is always present, it just does not fail here.
    assert _scope(result).ok
    assert "NO surface was live" in _scope(result).detail


def test_a_mixed_pack_passes_but_names_the_synthetic_surfaces() -> None:
    check = _scope(verify_pack(_pack(_MIXED), require_live=True))
    assert check.ok
    assert Surface.SEMANTIC_CACHE.value in check.detail
    assert "1 of 2 surfaces were live" in check.detail


def test_a_pack_without_provenance_cannot_establish_its_subject() -> None:
    result = verify_pack(_pack({}), require_live=True)
    assert not result.passed
    assert "cannot be established" in _scope(result).detail


@pytest.mark.parametrize(
    "provenance,expected",
    [
        (_LIVE, "every surface exercised by this run was a live"),
        (_FAKE, "This pack is a demonstration, not an attestation."),
        (_MIXED, "1 of 2 surfaces were live"),
        ({}, "not recorded"),
    ],
)
def test_the_audit_pdf_states_the_provenance(provenance: dict[str, str], expected: str) -> None:
    # The PDF is what actually reaches an auditor. Before this it rendered a run
    # against eight fakes identically to a production assessment.
    assert expected in provenance_statement(_run(provenance))


def test_the_cli_refuses_a_synthetic_pack_by_default(tmp_path: Path) -> None:
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    pack = tmp_path / "evidence.json"
    refused = _runner.invoke(app, ["verify", str(pack), "--allow-unanchored"])
    assert refused.exit_code != 0
    assert "NO surface was live" in refused.output
    accepted = _runner.invoke(app, ["verify", str(pack), "--allow-unanchored", "--allow-synthetic"])
    assert accepted.exit_code == 0


@pytest.mark.parametrize("value", ["synthetic", "Live", "LIVE ", "bogus"])
def test_a_non_member_provenance_value_is_refused_by_the_model(value: str) -> None:
    # Both gates compare against the exact member strings, so anything else read
    # as not-synthetic in `score` and as live in `verify`: a hand-edited record
    # passed a fail-closed check by misspelling the thing it was meant to disclose.
    with pytest.raises(ValueError, match="surface_provenance"):
        _run({Surface.VECTOR_DB.value: value})


def test_a_provenance_value_that_is_not_live_never_counts_as_live() -> None:
    # Belt and braces under the validator: the gate itself only counts LIVE.
    from sectum_ai.evidence.verify import _check_run_scope

    pack = _pack(_LIVE).model_copy(deep=True)
    run = pack.run_result.model_construct(
        **{**pack.run_result.model_dump(), "surface_provenance": {"vector_db": "Live"}}
    )
    doctored = pack.model_construct(**{**pack.model_dump(), "run_result": run})
    check = _check_run_scope(doctored, require_live=True)
    assert not check.ok
    assert "NO surface was live" in check.detail


def test_a_live_slot_no_probe_drove_cannot_pass_the_scope_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No catalog probe drives the tracing slot. Recording every slot's provenance
    # let a live tracing adapter alone satisfy the run-scope gate for a run whose
    # every probed surface was the built-in fake.
    import json

    from sectum_ai import config as config_module
    from sectum_ai.adapters.fakes import FakeObservability

    class _LiveTracing(FakeObservability):
        synthetic = False

    monkeypatch.setattr(config_module, "build_observability", lambda _cfg: _LiveTracing())
    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    recorded = json.loads((tmp_path / "run.json").read_text())["surface_provenance"]
    assert Surface.TRACING.value not in recorded, recorded
    assert set(recorded.values()) == {SurfaceProvenance.SYNTHETIC.value}
    _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    refused = _runner.invoke(app, ["verify", str(tmp_path / "evidence.json"), "--allow-unanchored"])
    assert refused.exit_code == 4, refused.output
    assert "NO surface was live" in refused.output


def test_a_stale_run_record_inside_a_current_pack_is_refused() -> None:
    # `report` accepted a 0.6.x run.json (which recorded every adapter slot,
    # including a live one no probe drove), stamped the pack 0.7.0, and `verify`
    # passed run-scope on that phantom LIVE slot.
    from sectum_ai.spec import SCHEMA_VERSION

    pack = _pack(_LIVE)
    stale_run = pack.run_result.model_copy(update={"schema_version": "0.6.0"})
    stale = pack.model_copy(update={"run_result": stale_run})
    result = verify_pack(stale, require_live=True)
    assert not result.passed
    check = next(c for c in result.checks if c.name == "schema-version")
    assert not check.ok
    assert "0.6.0" in check.detail and SCHEMA_VERSION in check.detail


def test_report_refuses_a_run_from_another_schema_line(tmp_path: Path) -> None:
    import json

    _runner.invoke(app, ["seed", "--workdir", str(tmp_path)])
    _runner.invoke(app, ["probe", "--workdir", str(tmp_path)])
    run_path = tmp_path / "run.json"
    run = json.loads(run_path.read_text())
    run["schema_version"] = "0.6.0"
    run_path.write_text(json.dumps(run))
    result = _runner.invoke(app, ["report", "--workdir", str(tmp_path)])
    assert result.exit_code == 3, result.output
    assert "schema '0.6.0'" in result.output
    assert not (tmp_path / "evidence.json").exists()
