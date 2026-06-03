"""Independent verification of an ``EvidencePack`` (the engineering spec, section 8.2).

``sectum verify`` recomputes the pack digest from the pack's attested content -
the run record, manifest hash, control mappings, PDF reference, and
transparency-log flag - and checks it against the timestamp token; any edit to
that content changes the digest and fails verification (ADR-0016).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass

from sectum_ai.evidence.chain import LocalTimestamper, attested_digest
from sectum_ai.spec import (
    SCHEMA_VERSION,
    EvidenceError,
    EvidencePack,
    GroundTruthManifest,
    canonical_hash,
    sha256_hex,
)


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
    pack: EvidencePack,
    manifest: GroundTruthManifest | None = None,
    *,
    tsa_certificate: bytes | None = None,
    tsa_root: bytes | None = None,
    rekor_keyring: Mapping[str, bytes] | None = None,
    pdf_bytes: bytes | None = None,
) -> VerificationResult:
    """Verify an evidence pack; return a PASS/FAIL verdict with per-check detail.

    Recomputes the pack digest over the whole attested content, validates that
    the timestamp token attests it, and checks that the run and the pack agree on
    the manifest hash. A pack that claims a transparency-log anchor
    (``anchored_in_log``) must carry a valid Rekor inclusion proof - stripping it
    is a downgrade and fails. When ``manifest`` is given, its canonical hash must
    also match the pack.

    For an RFC 3161 timestamp token, ``tsa_certificate``/``tsa_root`` override
    the built-in FreeTSA leaf/root to pin a customer's own TSA. When the pack
    carries a Rekor inclusion proof, it is verified too; ``rekor_keyring``
    (log id -> PEM key) overrides the built-in Rekor keys for a private instance.

    ``pdf_bytes`` are the bytes of the audit PDF when it sits alongside the pack;
    when given (and the pack binds a ``pdf_ref``) they are re-hashed and checked
    against that bound digest, so a swapped audit PDF fails verification.
    """
    digest = attested_digest(pack)
    checks = [
        _check_schema_version(pack),
        _check_token(pack.tsa_token, digest, tsa_certificate, tsa_root),
        _check_consistency(pack),
    ]
    if pack.anchored_in_log and pack.rekor_proof is None:
        checks.append(
            Check(
                "rekor-inclusion",
                ok=False,
                detail=(
                    "the pack claims a transparency-log anchor but carries no Rekor "
                    "inclusion proof; the proof was stripped (a downgrade)"
                ),
            )
        )
    elif pack.rekor_proof is not None:
        checks.append(_check_rekor(pack.rekor_proof, digest, rekor_keyring))
    if manifest is not None:
        checks.append(_check_manifest(manifest, pack.manifest_hash))
    if pack.pdf_ref is not None and pdf_bytes is not None:
        checks.append(_check_pdf(pack.pdf_ref, pdf_bytes))
    return VerificationResult(passed=all(check.ok for check in checks), checks=tuple(checks))


def _check_pdf(pdf_ref: str, pdf_bytes: bytes) -> Check:
    """Re-hash the audit PDF and check it against the digest bound in the pack."""
    name = "audit-pdf"
    if sha256_hex(pdf_bytes) != pdf_ref:
        return Check(
            name,
            ok=False,
            detail=(
                "the audit PDF does not match the SHA-256 bound into the attested "
                "digest; it was altered or replaced after signing"
            ),
        )
    return Check(
        name, ok=True, detail="the audit PDF matches the SHA-256 bound into the attested digest"
    )


def _check_rekor(proof: str, digest: str, rekor_keyring: Mapping[str, bytes] | None) -> Check:
    name = "rekor-inclusion"
    from sectum_ai.evidence.rekor import verify_rekor_proof

    try:
        integrated_at = verify_rekor_proof(proof, digest, keyring=rekor_keyring)
    except EvidenceError as error:
        return Check(name, ok=False, detail=str(error))
    return Check(
        name,
        ok=True,
        detail=f"pack digest recorded in the Rekor transparency log at {integrated_at.isoformat()}",
    )


def _check_token(
    token: str | None,
    digest: str,
    tsa_certificate: bytes | None = None,
    tsa_root: bytes | None = None,
) -> Check:
    name = "timestamp-token"
    if not token:
        return Check(name, ok=False, detail="the pack carries no timestamp token")
    try:
        parsed = json.loads(token)
    except json.JSONDecodeError:
        # Not JSON: a base64 RFC 3161 token from a real TSA. Verify its signature
        # and message imprint against an independently pinned root.
        return _check_rfc3161_token(token, digest, tsa_certificate, tsa_root)
    if not isinstance(parsed, dict) or parsed.get("digest") != digest:
        return Check(
            name,
            ok=False,
            detail="the timestamp token attests a different digest; the evidence pack was altered",
        )
    tsa = parsed.get("tsa")
    if tsa != LocalTimestamper.tsa:
        # A real TSA returns a signed binary RFC 3161 token (handled above as a
        # non-JSON token), never a plain JSON object. A JSON token naming some
        # other authority is forged to impersonate one, so it is refused.
        return Check(
            name,
            ok=False,
            detail=(
                "unrecognized JSON timestamp token; a real RFC 3161 TSA returns a "
                "signed binary token, not JSON, so this token is rejected"
            ),
        )
    return Check(
        name,
        ok=True,
        detail=(
            "pack digest bound by a local development timestamp (unanchored: not an "
            "independent RFC 3161 / Rekor anchor)"
        ),
    )


def _check_rfc3161_token(
    token: str, digest: str, tsa_certificate: bytes | None, tsa_root: bytes | None
) -> Check:
    name = "timestamp-token"
    from sectum_ai.evidence.tsa import verify_rfc3161_token

    try:
        timestamped_at = verify_rfc3161_token(
            token, digest, tsa_certificate=tsa_certificate, tsa_root=tsa_root
        )
    except EvidenceError as error:
        return Check(name, ok=False, detail=str(error))
    return Check(
        name,
        ok=True,
        detail=f"pack digest timestamped by an RFC 3161 TSA at {timestamped_at.isoformat()}",
    )


def _schema_major_minor(version: str) -> tuple[str, str]:
    """The ``(major, minor)`` of a ``major.minor.patch`` schema version."""
    parts = version.split(".")
    return (parts[0], parts[1] if len(parts) > 1 else "0")


def _check_schema_version(pack: EvidencePack) -> Check:
    """Refuse a pack whose schema version this verifier cannot interpret.

    The attested digest is recomputed under a canonical-serialization scheme tied
    to the schema version; a pack from an incompatible ``major.minor`` may hash
    under different rules or carry different fields, so it is refused rather than
    silently mis-verified. A patch-level difference is compatible (the spec, §9 -
    every aggregate model is ``schema_version``-stamped).
    """
    ok = _schema_major_minor(pack.schema_version) == _schema_major_minor(SCHEMA_VERSION)
    detail = (
        f"pack schema_version {pack.schema_version} is supported by this verifier"
        if ok
        else (
            f"pack schema_version {pack.schema_version!r} is incompatible with this verifier "
            f"(supports {SCHEMA_VERSION!r}); verify with a matching sectum version"
        )
    )
    return Check("schema-version", ok=ok, detail=detail)


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
