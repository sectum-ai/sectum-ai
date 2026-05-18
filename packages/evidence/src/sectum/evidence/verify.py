"""Independent verification of an ``EvidencePack`` (the engineering spec, section 8.2).

``sectum verify`` recomputes the run digest from the pack's run record and
checks it against the timestamp token; any edit to the run record changes the
digest and fails verification.
"""

import json
from dataclasses import dataclass

from sectum.evidence.chain import run_digest
from sectum.spec import EvidencePack, GroundTruthManifest, canonical_hash


@dataclass(frozen=True)
class Check:
    """One verification check and its outcome."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class VerificationResult:
    """The outcome of verifying an ``EvidencePack``: a verdict plus per-check detail."""

    passed: bool
    checks: tuple[Check, ...]


def verify_pack(
    pack: EvidencePack, manifest: GroundTruthManifest | None = None
) -> VerificationResult:
    """Verify an evidence pack; return a PASS/FAIL verdict with per-check detail.

    Recomputes the run digest, validates that the timestamp token attests it,
    and checks that the run and the pack agree on the manifest hash. When
    ``manifest`` is given, its canonical hash must also match the pack.
    """
    digest = run_digest(pack.run_result)
    checks = [_check_token(pack.tsa_token, digest), _check_consistency(pack)]
    if manifest is not None:
        checks.append(_check_manifest(manifest, pack.manifest_hash))
    return VerificationResult(passed=all(check.ok for check in checks), checks=tuple(checks))


def _check_token(token: str | None, digest: str) -> Check:
    name = "timestamp-token"
    if not token:
        return Check(name, ok=False, detail="the pack carries no timestamp token")
    try:
        parsed = json.loads(token)
    except json.JSONDecodeError:
        return Check(name, ok=False, detail="the timestamp token is not valid JSON")
    if not isinstance(parsed, dict) or parsed.get("digest") != digest:
        return Check(
            name,
            ok=False,
            detail="the timestamp token attests a different digest; the run was altered",
        )
    tsa = parsed.get("tsa", "unknown")
    return Check(name, ok=True, detail=f"run digest timestamped by {tsa}")


def _check_consistency(pack: EvidencePack) -> Check:
    ok = pack.run_result.manifest_hash == pack.manifest_hash
    detail = (
        "the run and the pack agree on the manifest hash"
        if ok
        else "the run's manifest hash does not match the pack's"
    )
    return Check("manifest-consistency", ok=ok, detail=detail)


def _check_manifest(manifest: GroundTruthManifest, expected_hash: str) -> Check:
    ok = canonical_hash(manifest) == expected_hash
    detail = (
        "the supplied manifest matches the pack"
        if ok
        else "the supplied manifest does not match the pack's recorded hash"
    )
    return Check("manifest-hash", ok=ok, detail=detail)
