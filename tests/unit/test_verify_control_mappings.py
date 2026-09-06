"""`verify` asks whether the run earned the compliance claims, not only who signed them.

The attested digest binds ``control_mappings``, so nobody can edit them after the
pack is signed - and that was the whole of the guarantee. Nothing asked whether
the run SUPPORTS them, so a pack built by any other tool, or by a patched copy of
this one, carried whatever table its author chose and verified `[ok]` on every
line. A clean isolation run over an empty ``erasure_coverage``, packed with the
unfiltered table, asserted GDPR Article 17 "Erasure across the AI surfaces
verified" and CCPA 1798.105 into a signed pack, an audit PDF and a DSSE
predicate, at exit 0.

That is the exact over-claim ``controls.control_mappings``' filter exists to
prevent - it just ran only at build time. The OSCAL export, which re-derives from
the run, emitted the 9 isolation controls for the same pack: the divergence was
observable, in a different artifact, to a reader who thought to compare them.
"""

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from sectum_ai.cli.app import app
from sectum_ai.evidence import build_evidence_pack, verify_pack
from sectum_ai.evidence.controls import control_mappings
from sectum_ai.evidence.verify import Check, VerificationResult
from sectum_ai.spec import (
    ControlMapping,
    EvidencePack,
    GroundTruthManifest,
    RunResult,
    Surface,
    SurfaceProvenance,
    canonical_hash,
)

_MANIFEST = GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())
_runner = CliRunner()


def _run() -> RunResult:
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    return RunResult(
        run_id="run-controls",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(_MANIFEST),
        started_at=moment,
        finished_at=moment,
        probe_versions={"tenant-boundary-fetch": "1"},
        surface_provenance={Surface.VECTOR_DB.value: SurfaceProvenance.LIVE.value},
    )


def _check(result: VerificationResult) -> Check:
    return next(c for c in result.checks if c.name == "control-mappings")


def test_a_pack_whose_mappings_its_run_earned_passes() -> None:
    run = _run()
    pack = build_evidence_pack(run, _MANIFEST, control_mappings=control_mappings(run))
    check = _check(verify_pack(pack))
    assert check.ok, check.detail
    assert "evidence supports" in check.detail


def test_a_pack_asserting_erasure_over_a_run_with_none_is_refused() -> None:
    # The deletion controls need erasure coverage, which the isolation probes
    # structurally cannot produce - they are `sectum-ai erasure`'s output. This
    # run has none, and the forged pack asserts them anyway.
    run = _run()
    assert run.metrics.erasure_coverage == {}
    forged = ControlMapping(
        framework="GDPR",
        control_ids=("Article 17",),
        assertion="Erasure across the AI surfaces verified.",
    )
    pack = build_evidence_pack(run, _MANIFEST, control_mappings=(*control_mappings(run), forged))
    result = verify_pack(pack)
    assert not result.passed
    check = _check(result)
    assert not check.ok
    assert "not earned" in check.detail or "did not earn" in check.detail
    # The digest still recomputes: the pack is internally consistent and the
    # forgery is invisible to every byte-integrity check beside this one.
    assert next(c for c in result.checks if c.name == "manifest-consistency").ok


def test_the_cli_refuses_a_pack_asserting_a_control_its_run_did_not_earn(tmp_path: Path) -> None:
    run = _run()
    forged = ControlMapping(
        framework="CCPA",
        control_ids=("1798.105",),
        assertion="Deletion across the AI surfaces verified.",
    )
    pack = build_evidence_pack(run, _MANIFEST, control_mappings=(forged,))
    path = tmp_path / "evidence.json"
    path.write_text(pack.model_dump_json())
    result = _runner.invoke(app, ["verify", str(path), "--allow-unanchored"])
    assert result.exit_code != 0, result.output
    assert "control-mappings" in result.output, result.output


def test_asserting_fewer_controls_than_the_run_earned_is_allowed() -> None:
    # A subset, not an equality. Under-claiming is honest - `report` without the
    # compliance table records no mappings at all over a run that earns nine -
    # and only the other direction is the over-claim this check exists to refuse.
    run = _run()
    earned = control_mappings(run)
    assert len(earned) > 1, "the fixture run must earn more than one mapping"
    assert _check(verify_pack(build_evidence_pack(run, _MANIFEST, control_mappings=earned[:-1]))).ok
    assert _check(verify_pack(build_evidence_pack(run, _MANIFEST))).ok


def test_a_mapping_naming_live_surfaces_the_run_did_not_exercise_is_refused() -> None:
    # The assertion carries the live surfaces it rests on, inside the signed pack.
    # Comparing the whole mapping binds that too: "verified" over a surface the
    # run never ran live against is the same over-claim, one clause further in.
    run = _run()
    earned = control_mappings(run)
    widened = earned[0].model_copy(
        update={"assertion": f"{earned[0].assertion} Live surfaces: vector_db, semantic_cache."}
    )
    assert not _check(
        verify_pack(build_evidence_pack(run, _MANIFEST, control_mappings=(widened,)))
    ).ok


def test_a_pack_carrying_no_mappings_at_all_is_read_as_a_pack_of_no_mappings() -> None:
    # `report` without the compliance table is an ordinary, honest pack, and the
    # check must not turn every one of those into a failure.
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    bare = RunResult(
        run_id="run-bare",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(_MANIFEST),
        started_at=moment,
        finished_at=moment,
    )
    pack: EvidencePack = build_evidence_pack(bare, _MANIFEST)
    assert pack.control_mappings == ()
    assert _check(verify_pack(pack)).ok
