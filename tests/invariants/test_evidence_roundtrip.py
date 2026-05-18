"""Invariant: the evidence chain round-trips - a built pack verifies, a tampered one fails.

The engineering spec, section 15: ``build_evidence_pack`` then ``verify_pack``
PASSES; mutating any part of the pack makes verification FAIL with a clear reason.
"""

from datetime import UTC, datetime
from uuid import UUID

from sectum.evidence import build_evidence_pack, verify_pack
from sectum.spec import (
    Finding,
    FindingStatus,
    GroundTruthManifest,
    RunMetrics,
    RunResult,
    Severity,
    Surface,
    canonical_hash,
)


def _manifest() -> GroundTruthManifest:
    return GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())


def _run_result(manifest: GroundTruthManifest) -> RunResult:
    finding = Finding(
        finding_id="f-1",
        probe_id="tenant-boundary-fetch",
        severity=Severity.CRITICAL,
        confidence=1.0,
        status=FindingStatus.CONFIRMED,
        owner_tenant_id=UUID(int=0xB),
        observed_in_tenant_id=UUID(int=0xA),
        surface=Surface.VECTOR_DB,
    )
    moment = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    return RunResult(
        run_id="run-1",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(manifest),
        started_at=moment,
        finished_at=moment,
        findings=(finding,),
        metrics=RunMetrics(),
    )


def test_a_freshly_built_pack_verifies() -> None:
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    result = verify_pack(pack, manifest)
    assert result.passed
    assert all(check.ok for check in result.checks)


def test_tampering_with_the_run_record_fails_verification() -> None:
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    tampered_run = pack.run_result.model_copy(update={"run_id": "run-tampered"})
    tampered = pack.model_copy(update={"run_result": tampered_run})
    result = verify_pack(tampered, manifest)
    assert not result.passed
    assert any(not check.ok and "altered" in check.detail for check in result.checks)


def test_a_mismatched_manifest_fails_verification() -> None:
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    other = GroundTruthManifest(manifest_id="m-2", scenario_hash="other-hash", markers=())
    assert not verify_pack(pack, other).passed


def test_a_pack_without_a_timestamp_token_fails_verification() -> None:
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    untimestamped = pack.model_copy(update={"tsa_token": None})
    assert not verify_pack(untimestamped).passed


def test_a_malformed_timestamp_token_fails_verification() -> None:
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    malformed = pack.model_copy(update={"tsa_token": "not-json"})
    assert not verify_pack(malformed).passed
