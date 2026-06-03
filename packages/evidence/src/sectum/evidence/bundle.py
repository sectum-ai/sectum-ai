"""Single-archive evidence bundle (the engineering spec, section 8.2 step 5).

Section 8.2 step 5 bundles a run's attested artifacts - the evidence JSON, the
audit PDF, the in-toto attestation, and (optionally, sealed) the ground-truth
manifest - into one pack. This assembles those members into a deterministic ZIP
carrying a ``bundle-manifest.json`` of per-member SHA-256 digests, and verifies a
bundle by recomputing every digest and re-running :func:`verify_pack` on the
contained evidence JSON.

The bundler is content-agnostic: the caller chooses the members and may seal a
sensitive one (the ground-truth manifest) before adding it, so this module takes
on no crypto dependency and stays within the evidence layer - it must not import
``sectum`` core, which depends on it.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping

from sectum.evidence.verify import Check, VerificationResult, verify_pack
from sectum.spec import EvidencePack

EVIDENCE_MEMBER = "evidence.json"
"""The bundled evidence-pack JSON; every bundle must contain it."""

MANIFEST_MEMBER = "bundle-manifest.json"
"""The reserved member recording each other member's SHA-256."""

# ZIP's epoch floor (1980-01-01). Fixing the member timestamps makes a bundle
# byte-reproducible for identical inputs instead of embedding the build time.
_ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_bundle(members: Mapping[str, bytes]) -> bytes:
    """Return a deterministic ZIP of ``members`` plus a SHA-256 digest manifest.

    ``members`` maps an archive name to its bytes and must include
    ``evidence.json``. A ``bundle-manifest.json`` recording each member's SHA-256
    is added so a verifier can prove no member was altered. Identical inputs
    yield identical bytes (members sorted, fixed timestamps).
    """
    if EVIDENCE_MEMBER not in members:
        raise ValueError(f"an evidence bundle must include {EVIDENCE_MEMBER!r}")
    if MANIFEST_MEMBER in members:
        raise ValueError(f"{MANIFEST_MEMBER!r} is reserved for the digest manifest")
    digests = {name: _sha256(members[name]) for name in sorted(members)}
    manifest = json.dumps(
        {"evidence": EVIDENCE_MEMBER, "members": digests}, indent=2, sort_keys=True
    )
    payload: dict[str, bytes] = {**members, MANIFEST_MEMBER: (manifest + "\n").encode("utf-8")}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payload):
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload[name])
    return buffer.getvalue()


def verify_bundle(
    bundle: bytes, *, rekor_keyring: Mapping[str, bytes] | None = None
) -> VerificationResult:
    """Verify a bundle end to end and return a PASS/FAIL verdict with per-check detail.

    Every member's SHA-256 must match the recorded manifest digest, and the
    contained evidence pack must pass :func:`verify_pack`. A missing or mismatched
    member, or a failed pack verification, fails the result - so editing any
    bundled artifact (or the pack itself) is caught.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            names = archive.namelist()
            if MANIFEST_MEMBER not in names:
                return VerificationResult(
                    passed=False,
                    checks=(Check("bundle-manifest", False, f"missing {MANIFEST_MEMBER}"),),
                )
            manifest = json.loads(archive.read(MANIFEST_MEMBER))
            evidence_member = manifest.get("evidence", EVIDENCE_MEMBER)
            member_digests: dict[str, str] = manifest.get("members", {})
            member_bytes = {name: archive.read(name) for name in names if name != MANIFEST_MEMBER}
    except (zipfile.BadZipFile, KeyError, ValueError) as error:
        return VerificationResult(
            passed=False, checks=(Check("bundle", False, f"unreadable bundle: {error}"),)
        )

    checks: list[Check] = []
    for name in sorted(member_digests):
        present = member_bytes.get(name)
        if present is None:
            checks.append(Check(f"member:{name}", False, "listed in manifest but missing"))
        elif _sha256(present) == member_digests[name]:
            checks.append(Check(f"member:{name}", True, "digest matches"))
        else:
            checks.append(Check(f"member:{name}", False, "digest mismatch (member altered)"))

    evidence_raw = member_bytes.get(evidence_member)
    if evidence_raw is None:
        checks.append(Check("evidence-pack", False, f"missing evidence member {evidence_member!r}"))
        return VerificationResult(passed=False, checks=tuple(checks))
    try:
        pack = EvidencePack.model_validate_json(evidence_raw)
    except ValueError as error:
        checks.append(Check("evidence-pack", False, f"unparsable evidence pack: {error}"))
        return VerificationResult(passed=False, checks=tuple(checks))
    checks.extend(verify_pack(pack, rekor_keyring=rekor_keyring).checks)
    return VerificationResult(passed=all(check.ok for check in checks), checks=tuple(checks))
