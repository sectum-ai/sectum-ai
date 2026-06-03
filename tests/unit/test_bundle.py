"""Tests for the single-archive evidence bundle (the engineering spec, section 8.2 step 5)."""

import io
import zipfile
from datetime import UTC, datetime

import pytest

from sectum.evidence import EVIDENCE_MEMBER, build_bundle, build_evidence_pack, verify_bundle
from sectum.spec import EvidencePack, GroundTruthManifest, RunMetrics, RunResult, canonical_hash


def _pack() -> EvidencePack:
    manifest = GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())
    moment = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    run = RunResult(
        run_id="run-1",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(manifest),
        started_at=moment,
        finished_at=moment,
        metrics=RunMetrics(),
    )
    return build_evidence_pack(run, manifest)


def _members(pack: EvidencePack | None = None) -> dict[str, bytes]:
    return {
        EVIDENCE_MEMBER: (pack or _pack()).model_dump_json().encode("utf-8"),
        "audit-pack.pdf": b"%PDF-1.4 audit pack bytes",
        "attestation.intoto.json": b'{"_type": "https://in-toto.io/Statement/v1"}',
    }


def _swap_member(bundle: bytes, name: str, new: bytes) -> bytes:
    """Rewrite one member of a built bundle, leaving the digest manifest stale."""
    with zipfile.ZipFile(io.BytesIO(bundle)) as src:
        items = {entry: src.read(entry) for entry in src.namelist()}
    items[name] = new
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for entry, data in items.items():
            dst.writestr(entry, data)
    return out.getvalue()


def test_a_freshly_built_bundle_verifies() -> None:
    result = verify_bundle(build_bundle(_members()))
    assert result.passed
    assert all(check.ok for check in result.checks)


def test_a_bundle_must_contain_the_evidence_member() -> None:
    with pytest.raises(ValueError, match=r"evidence\.json"):
        build_bundle({"audit-pack.pdf": b"x"})


def test_build_is_deterministic_for_identical_inputs() -> None:
    members = _members()
    assert build_bundle(members) == build_bundle(dict(members))


def test_tampering_with_a_member_fails_verification() -> None:
    tampered = _swap_member(build_bundle(_members()), "audit-pack.pdf", b"%PDF forged")
    result = verify_bundle(tampered)
    assert not result.passed
    assert any(not check.ok and "altered" in check.detail for check in result.checks)


def test_a_bundle_of_a_tampered_pack_fails_pack_verification() -> None:
    # Re-bundling a tampered pack makes the member digest self-consistent (it is
    # computed over the tampered bytes), so the member check passes - but the
    # pack's own attested digest no longer matches its token, so verify_pack fails.
    pack = _pack()
    tampered = pack.model_copy(
        update={"run_result": pack.run_result.model_copy(update={"run_id": "run-forged"})}
    )
    result = verify_bundle(build_bundle(_members(tampered)))
    assert not result.passed
    assert all(c.ok for c in result.checks if c.name.startswith("member:"))
    assert any(not c.ok and c.name == "timestamp-token" for c in result.checks)


def test_a_non_zip_input_fails_cleanly() -> None:
    result = verify_bundle(b"not a zip archive")
    assert not result.passed
    assert any("unreadable" in check.detail for check in result.checks)
