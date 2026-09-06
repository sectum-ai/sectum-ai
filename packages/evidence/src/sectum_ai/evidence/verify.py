"""Independent verification of an ``EvidencePack`` (the engineering spec, section 8.2).

``sectum-ai verify`` recomputes the pack digest from the pack's attested content -
the run record, manifest hash, control mappings, PDF reference, and
transparency-log flag - and checks it against the timestamp token; any edit to
that content changes the digest and fails verification (ADR-0016).

Integrity vs. anchoring: the digest checks above prove *internal consistency*,
but they are only tamper-EVIDENT when the digest is bound by an independent
anchor (a real RFC 3161 timestamp or a Rekor inclusion proof). A local-dev
token is reproducible by anyone over any digest, so an attacker who edits a
pack can simply re-stamp it; ``require_anchored=True`` refuses that downgrade
by failing any pack whose digest no verified independent anchor binds.

Integrity vs. subject: every check above concerns the *bytes*. A run against
Sectum's own in-memory fakes passes all of them, so "the signature is valid" and
"this describes a real system" were unrelated facts and only the first was
checked. ``require_live=True`` closes that: a pack whose run touched no live backend
is refused rather than read as an attestation. The CLI turns it on by default; the
library defaults to ``False`` (it reports, the CLI decides).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass

from sectum_ai.evidence.chain import LocalTimestamper, attested_digest
from sectum_ai.evidence.controls import control_mappings
from sectum_ai.spec import (
    SCHEMA_VERSION,
    ControlMapping,
    EvidenceError,
    EvidencePack,
    GroundTruthManifest,
    SurfaceProvenance,
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
    """The outcome of verifying an ``EvidencePack``: a verdict plus per-check detail.

    ``anchored`` is ``True`` only when a verified *independent* anchor binds the
    pack digest - a real RFC 3161 timestamp token or a Rekor inclusion proof
    that checked out. A pack whose only timestamp is a local-dev token verifies
    as internally consistent but ``anchored=False``: that result is NOT
    independent tamper evidence (the token is reproducible by anyone).
    """

    passed: bool
    checks: tuple[Check, ...]
    anchored: bool = False


def verify_pack(
    pack: EvidencePack,
    manifest: GroundTruthManifest | None = None,
    *,
    tsa_certificate: bytes | None = None,
    tsa_root: bytes | None = None,
    rekor_keyring: Mapping[str, bytes] | None = None,
    pdf_bytes: bytes | None = None,
    require_anchored: bool = False,
    require_live: bool = False,
) -> VerificationResult:
    """Verify an evidence pack; return a PASS/FAIL verdict with per-check detail.

    Recomputes the pack digest over the whole attested content, validates that
    the timestamp token attests it, and checks that the run and the pack agree on
    the manifest hash. A pack that claims a transparency-log anchor
    (``anchored_in_log``) must carry a valid Rekor inclusion proof, and a pack that
    claims a real RFC 3161 timestamp anchor (``anchored_with_timestamp``) must
    carry a real RFC 3161 token, not a local-dev one - stripping either anchor is a
    downgrade and fails. When ``manifest`` is given, its canonical hash must also
    match the pack.

    Those flag-based downgrade guards cannot stop an attacker who recomputes the
    digest with both anchor flags false and re-stamps the tampered pack with a
    fresh local-dev token (the token is reproducible by anyone). Set
    ``require_anchored=True`` to refuse that: verification then fails unless a
    verified independent anchor - a real RFC 3161 token or a Rekor inclusion
    proof - binds the digest. The result's ``anchored`` field reports which case
    held either way.

    For an RFC 3161 timestamp token, ``tsa_certificate``/``tsa_root`` override
    the built-in FreeTSA leaf/root to pin a customer's own TSA. When the pack
    carries a Rekor inclusion proof, it is verified too; ``rekor_keyring``
    (log id -> PEM key) overrides the built-in Rekor keys for a private instance.

    ``require_live=True`` refuses a pack whose run touched no live backend at
    all: every other check here concerns the integrity of the bytes, and all of
    them pass just as cleanly for a run against Sectum's own in-memory fakes. It
    defaults off for the same reason as ``require_anchored`` - the library reports,
    the CLI decides - and ``sectum-ai verify`` turns it on unless the caller passes
    ``--allow-synthetic``. The ``run-scope`` check states the provenance either way.

    ``pdf_bytes`` are the bytes of the audit PDF when it sits alongside the pack;
    when given (and the pack binds a ``pdf_ref``) they are re-hashed and checked
    against that bound digest, so a swapped audit PDF fails verification.
    """
    digest = attested_digest(pack)
    token_check, token_anchored = _check_token(
        pack.tsa_token,
        digest,
        tsa_certificate,
        tsa_root,
        require_rfc3161=pack.anchored_with_timestamp,
    )
    checks = [
        _check_schema_version(pack),
        token_check,
        _check_consistency(pack),
        _check_control_mappings(pack),
        _check_run_scope(pack, require_live),
    ]
    rekor_anchored = False
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
        rekor_check = _check_rekor(pack.rekor_proof, digest, rekor_keyring)
        checks.append(rekor_check)
        rekor_anchored = rekor_check.ok
    if manifest is not None:
        checks.append(_check_manifest(manifest, pack.manifest_hash))
    if pack.pdf_ref is not None and pdf_bytes is not None:
        checks.append(_check_pdf(pack.pdf_ref, pdf_bytes))
    elif pack.pdf_ref is not None:
        # A standalone pack legitimately verifies without its companion PDF, so
        # this is not a failure - but omitting the check entirely left the verdict
        # SILENT about a binding it never checked: every line `[ok]`, exit 0, and
        # a reader concluding the PDF had been matched. Said plainly instead, the
        # way the unanchored-timestamp check states its own limitation.
        checks.append(
            Check(
                "audit-pdf",
                ok=True,
                detail=(
                    "the pack binds an audit PDF that was not supplied, so this "
                    "verification says nothing about it; put the PDF beside the pack, "
                    "or verify the run-pack bundle, to check the binding"
                ),
            )
        )
    anchored = token_anchored or rekor_anchored
    if require_anchored and not anchored:
        checks.append(
            Check(
                "independent-anchor",
                ok=False,
                detail=(
                    "no verified independent anchor binds the pack digest: its "
                    "timestamp is a local-dev token, which anyone can regenerate over "
                    "an edited pack, or an external token this verifier could not "
                    "check - so this verification is not tamper evidence. "
                    "Re-create the pack with `report --tsa`/`--rekor`, or accept "
                    "integrity-only verification explicitly"
                ),
            )
        )
    return VerificationResult(
        passed=all(check.ok for check in checks), checks=tuple(checks), anchored=anchored
    )


def _check_pdf(pdf_ref: str, pdf_bytes: bytes, *, name: str = "audit-pdf") -> Check:
    """Re-hash the audit PDF and check it against the digest bound in the pack."""
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
    # The inclusion proof binds the digest; the integration time is a bare field
    # of the entry that nothing verified here signs (the signed entry timestamp
    # is not stored), so it is reported as the log's claim, not as a checked fact.
    return Check(
        name,
        ok=True,
        detail=(
            "pack digest included in the Rekor transparency log (inclusion proof "
            f"verified); the log reports integration at {integrated_at.isoformat()}, "
            "which this verifier does not independently check"
        ),
    )


def _check_token(
    token: str | None,
    digest: str,
    tsa_certificate: bytes | None = None,
    tsa_root: bytes | None = None,
    *,
    require_rfc3161: bool = False,
) -> tuple[Check, bool]:
    """Check the timestamp token; return ``(check, is_independent_anchor)``.

    The second element is ``True`` only when a real RFC 3161 token verified OK -
    a local-dev JSON token never anchors, even when its check passes, because
    anyone can regenerate one over an edited pack's recomputed digest.
    """
    name = "timestamp-token"
    if not token:
        return Check(name, ok=False, detail="the pack carries no timestamp token"), False
    try:
        parsed = json.loads(token)
    except json.JSONDecodeError:
        # Not JSON: a base64 RFC 3161 token from a real TSA. Verify its signature
        # and message imprint against an independently pinned root.
        rfc3161_check = _check_rfc3161_token(token, digest, tsa_certificate, tsa_root)
        return rfc3161_check, rfc3161_check.ok
    if not isinstance(parsed, dict) or parsed.get("digest") != digest:
        return Check(
            name,
            ok=False,
            detail="the timestamp token attests a different digest; the evidence pack was altered",
        ), False
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
        ), False
    if require_rfc3161:
        # The pack declares it was anchored by a real RFC 3161 TSA
        # (``anchored_with_timestamp``, bound into the digest), yet it carries only
        # a local-dev JSON token. The independent timestamp anchor was stripped -
        # the same downgrade shape the Rekor ``anchored_in_log`` guard refuses.
        return Check(
            name,
            ok=False,
            detail=(
                "the pack claims a real RFC 3161 timestamp anchor "
                "(anchored_with_timestamp) but carries only a local-dev token; the "
                "independent timestamp anchor was stripped (a downgrade)"
            ),
        ), False
    return Check(
        name,
        ok=True,
        detail=(
            "pack digest bound by a local development timestamp (unanchored: "
            "reproducible by anyone, NOT independent tamper evidence)"
        ),
    ), False


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


def check_raw_schema_stamps(raw: str | bytes) -> Check | None:
    """Refuse a pack whose JSON omits a schema stamp, or names another line.

    ``_check_schema_version`` reads the *parsed* pack, where a missing
    ``schema_version`` has already become the current version by default - and
    deleting the key leaves the parsed model, and therefore the attested digest,
    byte-identical, so no other check sees it either. Only the bytes can tell
    "stamped 0.7.0" from "unstamped", so this reads them; it returns ``None``
    when both stamps are present and on this line.
    """
    try:
        data = json.loads(raw)
    except ValueError:
        return None  # the parser below reports an unreadable pack
    if not isinstance(data, dict):
        return None
    run = data.get("run_result")
    for label, stamp in (
        ("pack", data.get("schema_version")),
        ("run record", run.get("schema_version") if isinstance(run, dict) else None),
    ):
        if not isinstance(stamp, str) or _schema_major_minor(stamp) != _schema_major_minor(
            SCHEMA_VERSION
        ):
            return Check(
                "schema-version",
                ok=False,
                detail=(
                    f"the {label}'s schema_version is {stamp!r}; this verifier reads "
                    f"{SCHEMA_VERSION!r} records, and an unstamped record is not a "
                    "current one"
                ),
            )
    return None


def _check_schema_version(pack: EvidencePack) -> Check:
    """Refuse a pack whose schema version this verifier cannot interpret.

    The attested digest is recomputed under a canonical-serialization scheme tied
    to the schema version; a pack from an incompatible ``major.minor`` may hash
    under different rules or carry different fields, so it is refused rather than
    silently mis-verified. A patch-level difference is compatible (the spec, §9 -
    every aggregate model is ``schema_version``-stamped).
    """
    supported = _schema_major_minor(SCHEMA_VERSION)
    # The run record inside carries its own stamp, and its fields are what every
    # other check reads: a 0.6.x run (which recorded every adapter slot) under a
    # current pack stamp passed the run-scope gate on a live slot no probe drove.
    ok = (
        supported
        == _schema_major_minor(pack.schema_version)
        == _schema_major_minor(pack.run_result.schema_version)
    )
    detail = (
        # `!r` (as the incompatible branch already does) is load-bearing, not cosmetic:
        # the pack supplies schema_version, `_schema_major_minor` reads only the major and
        # minor, and `_attested_content` does not bind the field - so text smuggled after
        # the patch digit passed the gate, was rendered raw, and forged `[ok]` lines
        # asserting the RFC 3161 and Rekor anchoring this command exists to establish.
        f"pack schema_version {pack.schema_version!r} is supported by this verifier"
        if ok
        else (
            f"pack schema_version {pack.schema_version!r} (run record "
            f"{pack.run_result.schema_version!r}) is incompatible with this verifier "
            f"(supports {SCHEMA_VERSION!r}); verify with a matching sectum version"
        )
    )
    return Check("schema-version", ok=ok, detail=detail)


def _check_run_scope(pack: EvidencePack, require_live: bool) -> Check:
    """Report which stack this pack's verdicts describe, and refuse a synthetic one.

    Every other check here answers a question about the *bytes* - that they are
    intact, that an anchor binds them, that the PDF matches. All of them pass just
    as cleanly for a run that touched nothing real, which is precisely the pack a
    third party must not accept as an attestation. Sectum ships an in-memory fake
    for every adapter family and falls back to one silently, so "the signature is
    valid" and "this describes your vendor's production systems" were unrelated
    facts and only the first was checked.

    Fails closed, like ``independent-anchor``: the reader of a pack is the party
    least able to notice what is missing from it.
    """
    provenance = pack.run_result.surface_provenance
    if not provenance:
        return Check(
            "run-scope",
            ok=not require_live,
            detail=(
                "the run records no surface provenance (it predates the block), so "
                "whether it touched live backends cannot be established from this pack"
                + ("" if require_live else "; accepted by --allow-synthetic")
            ),
        )
    # Only an exact LIVE counts as live: the block's values are validated on the
    # way in, but a gate that fails open on anything unexpected is still wrong.
    live = sum(1 for p in provenance.values() if p == SurfaceProvenance.LIVE.value)
    synthetic = sorted(s for s, p in provenance.items() if p != SurfaceProvenance.LIVE.value)
    if not synthetic:
        return Check(
            "run-scope",
            ok=True,
            detail="every surface this run exercised was a live backend",
        )
    if live:
        return Check(
            "run-scope",
            ok=True,
            detail=(
                f"{live} of {len(provenance)} surfaces were live; these ran against "
                f"Sectum's built-in fake and describe no real system: {', '.join(synthetic)}"
            ),
        )
    return Check(
        "run-scope",
        ok=not require_live,
        detail=(
            "NO surface was live - every verdict in this pack describes Sectum's "
            "built-in synthetic stack, not any production system. A grade, a metric, "
            "or a clean result here is not evidence about the operator's systems"
            + (
                ". Re-run against configured adapters, or accept a demo pack explicitly"
                if require_live
                else "; accepted by --allow-synthetic"
            )
        ),
    )


def _check_consistency(pack: EvidencePack) -> Check:
    ok = pack.run_result.manifest_hash == pack.manifest_hash
    detail = (
        "the run and the pack agree on the manifest hash"
        if ok
        else "the run's manifest hash does not match the pack's"
    )
    return Check("manifest-consistency", ok=ok, detail=detail)


def _check_control_mappings(pack: EvidencePack) -> Check:
    """Whether the compliance claims in the pack are ones its own run earned.

    The digest binds the mappings, so they cannot be edited after signing - but
    nothing asked whether the run supports them in the first place, and a pack
    built by any other tool carries whatever table its author chose. A clean
    isolation run over an empty `erasure_coverage`, packed with the unfiltered
    11-row table, therefore verified `[ok]` on every line while asserting GDPR
    Article 17 "Erasure across the AI surfaces verified" - the exact over-claim
    `controls.control_mappings`' filter exists to prevent, applied only at build
    time. The OSCAL export re-derives from the run and emitted 9 rows for the
    same pack; that divergence is the tell.

    `control_mappings(run)` is a pure function of the run, so the verifier can
    simply ask it again. A SUBSET, not an equality: asserting fewer controls than
    the evidence earns is honest under-claiming, and `report` without the
    compliance table produces exactly that. Only the other direction is the
    over-claim this product exists to refuse, and it fails closed.

    The comparison is over the whole mapping, so the live-surface list the
    assertion names is bound too: "verified" over surfaces the run never
    exercised live is the same claim one clause further in.
    """
    earned = {_canonical_mapping(mapping) for mapping in control_mappings(pack.run_result)}
    unearned = [
        mapping for mapping in pack.control_mappings if _canonical_mapping(mapping) not in earned
    ]
    named = ", ".join(
        f"{mapping.framework} {'/'.join(mapping.control_ids)}" for mapping in unearned
    )
    detail = (
        f"every one of the pack's {len(pack.control_mappings)} control mapping(s) is one "
        "this run's evidence supports"
        if not unearned
        else (
            f"the pack asserts {len(unearned)} control mapping(s) this run's evidence does "
            f"not support ({named}); a compliance claim the run did not earn is not made "
            "true by being signed"
        )
    )
    return Check("control-mappings", ok=not unearned, detail=detail)


def _canonical_mapping(mapping: ControlMapping) -> str:
    return json.dumps(mapping.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _check_manifest(manifest: GroundTruthManifest, expected_hash: str) -> Check:
    ok = canonical_hash(manifest) == expected_hash
    detail = (
        "the supplied manifest matches the pack"
        if ok
        else "the supplied manifest does not match the pack's recorded hash"
    )
    return Check("manifest-hash", ok=ok, detail=detail)
