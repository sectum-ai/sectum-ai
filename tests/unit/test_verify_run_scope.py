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
