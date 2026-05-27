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


def test_a_malformed_rekor_proof_fails_verification() -> None:
    # A pack with a Rekor inclusion proof must validate it on verify; a
    # mutated/garbage proof string trips the rekor-inclusion check.
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    tampered = pack.model_copy(update={"rekor_proof": "garbage-not-a-rekor-proof"})
    result = verify_pack(tampered, manifest)
    assert not result.passed
    failed = [check for check in result.checks if not check.ok]
    assert any(check.name == "rekor-inclusion" for check in failed), (
        f"expected a failed rekor-inclusion check, got {[c.name for c in failed]}"
    )
    # The detail string must be human-readable - an operator parsing the
    # output should see a real reason, not a stack trace or an empty string.
    rekor_check = next(c for c in failed if c.name == "rekor-inclusion")
    assert rekor_check.detail, "the failed rekor-inclusion check had an empty detail message"


def test_verify_skips_the_rekor_check_when_the_pack_carries_no_proof() -> None:
    # A pack with rekor_proof=None must not add a rekor-inclusion check to
    # the result; the check is opt-in per the engineering spec, §8.2 step 4.
    # `build_evidence_pack` returns rekor_proof=None by default (no
    # `transparency_log` was passed), which is precisely the pack shape this
    # test pins — assert that precondition holds so a future default change
    # that silently flips on Rekor cannot make the test vacuous.
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    assert pack.rekor_proof is None, (
        "build_evidence_pack now adds a rekor_proof by default; "
        "this test must construct an explicitly proof-less pack instead"
    )
    result = verify_pack(pack, manifest)
    assert result.passed
    assert not any(check.name == "rekor-inclusion" for check in result.checks), (
        "rekor-inclusion check fired even though the pack carries no proof"
    )


def test_verify_runs_a_rekor_check_when_the_pack_carries_a_proof() -> None:
    # The companion to the opt-in test above: when a pack DOES carry a
    # rekor_proof, `verify_pack` must add a rekor-inclusion check to the
    # result. A stub transparency log makes the proof present; the verifier
    # will refuse it (the stub is not a real Rekor signer), so the check
    # lands ok=False — but the check IS present, which is what this test
    # pins.
    class _StubTransparencyLog:
        def record(self, digest: str) -> str:
            return f"stub-rekor-proof::{digest}"

    manifest = _manifest()
    pack = build_evidence_pack(
        _run_result(manifest), manifest, transparency_log=_StubTransparencyLog()
    )
    assert pack.rekor_proof is not None
    result = verify_pack(pack, manifest)
    rekor_checks = [check for check in result.checks if check.name == "rekor-inclusion"]
    assert len(rekor_checks) == 1, (
        f"expected exactly one rekor-inclusion check, got {len(rekor_checks)}"
    )
    # The check is present even though it fails on the stub proof; the
    # detail is non-empty so an operator can read the failure reason.
    assert rekor_checks[0].detail, "rekor-inclusion check returned an empty detail"


def test_verify_runs_a_manifest_check_only_when_a_manifest_is_supplied() -> None:
    # `verify_pack(pack)` without a manifest argument verifies the pack alone;
    # the manifest-hash check is added only when the caller passes one.
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    result_without_manifest = verify_pack(pack)
    assert result_without_manifest.passed
    assert not any(check.name == "manifest-hash" for check in result_without_manifest.checks)
    result_with_manifest = verify_pack(pack, manifest)
    assert result_with_manifest.passed
    assert any(check.name == "manifest-hash" and check.ok for check in result_with_manifest.checks)


def test_run_result_with_mismatched_manifest_hash_fails_consistency_check() -> None:
    # The pack's own manifest_hash is the authoritative reference; if the
    # run_result inside the pack carries a different hash, the
    # manifest-consistency check must catch the divergence even when the
    # caller does not supply a separate manifest argument.
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    diverged_run = pack.run_result.model_copy(update={"manifest_hash": "deadbeef"})
    tampered = pack.model_copy(update={"run_result": diverged_run})
    result = verify_pack(tampered)
    assert not result.passed
    consistency = next(c for c in result.checks if c.name == "manifest-consistency")
    assert not consistency.ok
    assert "manifest hash" in consistency.detail.lower()


def test_check_detail_strings_are_informative_on_happy_path() -> None:
    # On a passing verification, every check's detail is a non-empty string
    # that an audit-pack reviewer can read. Catches silent regressions where
    # a check returns ok=True with an empty detail (no diagnostic surface).
    # This covers the no-rekor default path (timestamp-token, manifest-
    # consistency, manifest-hash); the rekor-inclusion check's non-empty
    # detail is asserted by test_verify_runs_a_rekor_check_when_the_pack_
    # carries_a_proof on the present-but-failing-on-stub branch. A true
    # rekor happy-path assertion would require a real Sigstore signer the
    # offline test suite does not stand up.
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest)
    result = verify_pack(pack, manifest)
    assert result.passed
    for check in result.checks:
        assert check.detail, f"check {check.name} returned an empty detail string"
