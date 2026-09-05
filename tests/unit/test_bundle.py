"""Tests for the single-archive evidence bundle (the engineering spec, section 8.2 step 5)."""

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sectum_ai.cli.app import app
from sectum_ai.evidence import (
    EVIDENCE_MEMBER,
    MANIFEST_MEMBER,
    RUN_MEMBER,
    Check,
    VerificationResult,
    build_bundle,
    build_dsse_envelope,
    build_evidence_pack,
    to_in_toto_statement,
    verify_bundle,
)
from sectum_ai.spec import (
    EvidencePack,
    GroundTruthManifest,
    RunMetrics,
    RunResult,
    canonical_hash,
    sha256_hex,
)

_PDF = b"%PDF-1.4 audit pack bytes"


def _pack(run_id: str = "run-1") -> EvidencePack:
    manifest = GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())
    moment = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    run = RunResult(
        run_id=run_id,
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(manifest),
        started_at=moment,
        finished_at=moment,
        metrics=RunMetrics(),
    )
    # Bind the audit PDF into the pack so the bundle's audit-pdf check is exercised.
    return build_evidence_pack(run, manifest, pdf_ref=sha256_hex(_PDF))


def _members(pack: EvidencePack | None = None) -> dict[str, bytes]:
    """A realistic `report --bundle` member set: the pack, its audit PDF, and the
    in-toto + DSSE sidecars that actually bind it."""
    pack = pack or _pack()
    return {
        EVIDENCE_MEMBER: pack.model_dump_json().encode("utf-8"),
        "audit-pack.pdf": _PDF,
        "attestation.intoto.json": json.dumps(to_in_toto_statement(pack)).encode("utf-8"),
        "evidence.dsse.json": json.dumps(build_dsse_envelope(pack)).encode("utf-8"),
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


def _check(result: VerificationResult, name: str) -> Check:
    return next(c for c in result.checks if c.name == name)


def test_a_freshly_built_bundle_verifies() -> None:
    result = verify_bundle(build_bundle(_members()))
    assert result.passed
    assert all(check.ok for check in result.checks)
    # The audit-PDF binding and both sidecar bindings actually ran (not absent).
    names = {check.name for check in result.checks}
    assert {"audit-pdf", "in-toto-attestation", "dsse-envelope"} <= names


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


def test_an_unlisted_member_smuggled_into_the_archive_fails_verification() -> None:
    # The free-ride the member-digest loop alone misses: inject a forged member that
    # bundle-manifest.json does not list. The loop only iterates manifest-listed
    # names, so without reconciling the archive against the manifest this forged
    # erasure attestation (the wedge deliverable) rides inside a PASSing bundle - and
    # the raw-ZIP sidecar/PDF selection could even deliver it. It must fail.
    smuggled = _swap_member(
        build_bundle(_members()),
        "erasure-attestation.pdf",
        b"%PDF-1.4 FORGED erasure attestation: all data erased, zero residue",
    )
    result = verify_bundle(smuggled)
    assert not result.passed
    assert any(
        not check.ok and "not covered by the digest manifest" in check.detail
        for check in result.checks
    )


def test_rebuilt_bundle_with_a_forged_audit_pdf_fails_the_pdf_binding() -> None:
    # The attack the member-digest check alone misses: rewrite audit-pack.pdf to a
    # forged "zero leakage" PDF and REBUILD the bundle, so bundle-manifest.json
    # records the forged bytes and every member digest matches. The pack still
    # binds the real PDF's pdf_ref, so the audit-pdf check must catch the swap.
    forged = dict(_members())
    forged["audit-pack.pdf"] = b"%PDF-1.4 FORGED AUDIT PACK: zero leakage, fully isolated"
    result = verify_bundle(build_bundle(forged))
    assert not result.passed
    assert all(c.ok for c in result.checks if c.name.startswith("member:"))  # digests consistent
    assert not _check(result, "audit-pdf").ok


def test_pack_binding_a_pdf_ref_but_missing_the_pdf_member_fails() -> None:
    members = _members()
    del members["audit-pack.pdf"]
    result = verify_bundle(build_bundle(members))
    assert not result.passed
    assert not _check(result, "audit-pdf").ok


def test_a_bundled_sidecar_binding_a_different_run_fails() -> None:
    # The in-toto / DSSE sidecars must bind THIS pack's run digest. A bundle whose
    # sidecars attest a different run (rebuilt so member digests match) must fail.
    pack = _pack()
    other = _pack(run_id="run-other")
    members = _members(pack)
    members["attestation.intoto.json"] = json.dumps(to_in_toto_statement(other)).encode("utf-8")
    members["evidence.dsse.json"] = json.dumps(build_dsse_envelope(other)).encode("utf-8")
    result = verify_bundle(build_bundle(members))
    assert not result.passed
    assert not _check(result, "in-toto-attestation").ok
    assert not _check(result, "dsse-envelope").ok


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


def test_bundle_with_duplicate_member_names_is_refused() -> None:
    # A hostile ZIP can carry two members with the same name; readers disagree on
    # which copy wins, so the bundle cannot attest "exactly the manifest's member
    # set" and must be refused outright.
    bundle = build_bundle(_members())
    buffer = io.BytesIO(bundle)
    with zipfile.ZipFile(buffer, "a") as archive:
        archive.writestr(EVIDENCE_MEMBER, b"duplicate copy of the evidence member")
    result = verify_bundle(buffer.getvalue())
    assert not result.passed
    assert any(
        check.name == "bundle-members" and "duplicate" in check.detail for check in result.checks
    )


def test_bundle_result_reports_unanchored_for_a_local_pack() -> None:
    # The bundle verdict carries the contained pack's anchoring, and requiring an
    # anchor refuses a local-dev-only bundle the same way it refuses a bare pack.
    bundle = build_bundle(_members())
    result = verify_bundle(bundle)
    assert result.passed
    assert not result.anchored
    assert not verify_bundle(bundle, require_anchored=True).passed


def test_a_forged_bundled_run_record_fails_verification() -> None:
    # run.json is the detailed record the auditor reads - findings and evidence
    # spans - and the member-digest loop only proves it matches
    # bundle-manifest.json, which a forger rebuilds along with it. The pack already
    # carries the same record, so the binding is free: without it a run pack whose
    # findings were deleted verified clean, printing an affirmative "digest matches".
    pack = _pack()
    members = dict(_members(pack))
    members[RUN_MEMBER] = pack.run_result.model_dump_json(indent=2).encode("utf-8")
    honest = json.loads(members[RUN_MEMBER])
    assert honest == json.loads(pack.run_result.model_dump_json())  # premise
    assert verify_bundle(build_bundle(members)).passed

    forged_run = dict(honest)
    forged_run["run_id"] = "forged-run"
    forged = {**members, RUN_MEMBER: json.dumps(forged_run, indent=2).encode("utf-8")}
    result = verify_bundle(build_bundle(forged))
    assert not result.passed
    check = next(c for c in result.checks if c.name == "bundled-run")
    assert not check.ok and "altered or replaced" in check.detail


def _bundle_with_manifest(manifest_obj: object) -> bytes:
    """A ZIP whose bundle-manifest.json is ``manifest_obj``, plus one other member."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(MANIFEST_MEMBER, json.dumps(manifest_obj))
        archive.writestr(EVIDENCE_MEMBER, b"{}")
    return buffer.getvalue()


@pytest.mark.parametrize(
    "manifest_obj",
    [
        [1, 2, 3],  # manifest is a list -> reached .get
        "hello",  # manifest is a string -> reached .get
        7,  # manifest is a number -> reached .get
        {"members": None},  # -> reached sorted(None)
        {"members": "evidence.json"},  # -> iterated a string's characters
        {"members": ["evidence.json"]},  # -> a list where a mapping was assumed
        {"members": {}, "evidence": ["evidence.json"]},  # -> unhashable dict key
        {"members": {}, "evidence": None},
    ],
)
def test_a_hostile_bundle_manifest_is_refused_not_crashed(manifest_obj: object) -> None:
    # bundle-manifest.json is attacker-controlled JSON, so its SHAPE is a claim to
    # check. Read unchecked, these shapes raised AttributeError/TypeError out of
    # verify_bundle: `sectum-ai verify` then exited 1 on a traceback instead of 4
    # (VERIFICATION FAILED). A tamper-evidence tool that crashes on a hostile
    # artifact has not refused it - a caller keying on exit 4 reads the crash as
    # the tool breaking rather than the bundle being bad. Same standard the in-toto
    # sidecar already holds: a malformed input raises a typed error, never an
    # uncaught exception.
    result = verify_bundle(_bundle_with_manifest(manifest_obj))
    assert not result.passed
    assert not result.anchored  # a refused bundle asserts nothing about anchoring
    assert any(not check.ok for check in result.checks)


def test_a_refused_bundle_exits_four_not_a_traceback(tmp_path: Path) -> None:
    # The exit code IS the contract for a CI gate or delivery pipeline: 4 means the
    # evidence failed verification, and anything else means the tool did not answer.
    bundle = tmp_path / "evidence-bundle.zip"
    bundle.write_bytes(_bundle_with_manifest([1, 2, 3]))
    result = CliRunner().invoke(app, ["verify", str(bundle)])
    assert result.exit_code == 4
    assert "VERIFICATION FAILED" in result.output


def test_a_manifest_pointing_at_another_member_is_refused() -> None:
    # The manifest is unsigned, so it must not choose which member is "the pack":
    # a genuine, anchored pack under real.json plus arbitrary bytes under
    # evidence.json (the file the README and the CLI call the canonical record)
    # verified on the strength of the member the manifest pointed at.
    pack = _pack()
    genuine = pack.model_dump_json().encode("utf-8")
    forged = {
        EVIDENCE_MEMBER: b'{"this is": "not even a pack"}',
        "real.json": genuine,
        "audit-pack.pdf": _PDF,
    }
    digests = {name: sha256_hex(data) for name, data in forged.items()}
    manifest = json.dumps({"evidence": "real.json", "members": digests}).encode("utf-8")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in forged.items():
            archive.writestr(name, data)
        archive.writestr(MANIFEST_MEMBER, manifest)
    result = verify_bundle(out.getvalue(), require_anchored=False, require_live=False)
    assert not result.passed
    refusal = _check(result, "bundle-manifest")
    assert "real.json" in refusal.detail and EVIDENCE_MEMBER in refusal.detail


def test_an_unsigned_dsse_sidecar_is_reported_as_unsigned() -> None:
    # `report` writes `signatures: []`; the check name reads like a signature
    # check, so its detail must say no signature was verified.
    result = verify_bundle(build_bundle(_members()), require_anchored=False, require_live=False)
    assert "unsigned envelope" in _check(result, "dsse-envelope").detail


def test_a_member_name_cannot_forge_a_verify_line(tmp_path: Path) -> None:
    # `member:<name>` checks carry the archive's own member names, which the
    # bundle being verified controls; a newline in one forged whole `[ok]` lines
    # of the verifier's output.
    forged_name = "notes.txt\n[ok] independent-anchor: RFC 3161 timestamp verified"
    bundle = build_bundle({**_members(), forged_name: b"x"})
    path = tmp_path / "evidence-bundle.zip"
    path.write_bytes(bundle)
    result = CliRunner().invoke(
        app, ["verify", str(path), "--allow-unanchored", "--allow-synthetic"]
    )
    lines = result.output.splitlines()
    assert not any(line.startswith("[ok] independent-anchor") for line in lines), result.output
    assert any("member:notes.txt\\x0a[ok]" in line for line in lines), result.output
