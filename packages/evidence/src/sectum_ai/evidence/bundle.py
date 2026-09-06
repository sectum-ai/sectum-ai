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
from collections.abc import Callable, Mapping
from typing import Any

from sectum_ai.evidence.dsse import dsse_binding_detail, verify_dsse_envelope
from sectum_ai.evidence.intoto import verify_in_toto_statement
from sectum_ai.evidence.verify import (
    Check,
    VerificationResult,
    _check_pdf,
    check_raw_schema_stamps,
    verify_pack,
)
from sectum_ai.spec import EvidenceError, EvidencePack

EVIDENCE_MEMBER = "evidence.json"
"""The bundled evidence-pack JSON; every bundle must contain it."""

MANIFEST_MEMBER = "bundle-manifest.json"
"""The reserved member recording each other member's SHA-256."""

# Sidecar members ``report``/``erasure`` write into a bundle. The bundle path
# must re-bind these to the pack exactly as the standalone ``sectum-ai verify`` binds
# the on-disk siblings - otherwise a rebuilt bundle with a forged audit PDF or a
# re-pointed attestation would pass on the member-digest checks alone.
_PDF_MEMBERS = ("audit-pack.pdf", "erasure-attestation.pdf")
_INTOTO_MEMBERS = ("attestation.intoto.json", "erasure-attestation.intoto.json")
DSSE_MEMBER = "evidence.dsse.json"
# The detailed run record a run pack ships beside the evidence. Bound to the pack
# in `verify_bundle`, so it cannot be edited independently of what was signed.
RUN_MEMBER = "run.json"
# Members that ride unbound: covered by the (unsigned) digest manifest only.
_UNBOUND_MEMBERS = (
    "PACK-README.md",
    "sectum-ai.config.redacted.yaml",
    "ground-truth-manifest.json.aes",
)
# Everything `report --bundle` / `pack` / `erasure` can write. The manifest is
# unsigned, so a member it lists is not thereby vouched for: a bundle carrying a
# genuine pack plus a forged `erasure-attestation.pdf` and an arbitrary
# `summary-for-auditor.pdf`, each listed, printed `[ok] ... digest matches` for
# every one and passed. Only these names are admitted, every present PDF and
# in-toto member is bound to the pack, and the rest are named as unbound.
_KNOWN_MEMBERS = frozenset(
    {EVIDENCE_MEMBER, RUN_MEMBER, DSSE_MEMBER, *_PDF_MEMBERS, *_INTOTO_MEMBERS, *_UNBOUND_MEMBERS}
)

# ZIP's epoch floor (1980-01-01). Fixing the member timestamps makes a bundle
# byte-reproducible for identical inputs instead of embedding the build time.
_ZIP_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _refused(name: str, detail: str) -> VerificationResult:
    """A bundle refused outright, before any member could be checked.

    Refusals happen before the pack is read, so ``anchored`` keeps its default:
    a refused bundle asserts nothing about anchoring.
    """
    return VerificationResult(passed=False, checks=(Check(name, False, detail),))


def _check_sidecar(
    name: str,
    raw: bytes,
    bind: Callable[[Any], None],
    detail: Callable[[Any], str] = lambda _obj: "sidecar binds this pack's run digest",
) -> Check:
    """Re-bind a JSON sidecar (in-toto / DSSE) to the pack; FAIL if it no longer binds.

    Mirrors the standalone ``sectum-ai verify`` sidecar re-checks: a swapped or
    re-pointed statement/envelope that no longer attests this pack's run digest is
    itemized as a failed check rather than silently trusted.
    """
    try:
        obj = json.loads(raw)
        bind(obj)
    except (ValueError, TypeError, AttributeError, EvidenceError) as error:
        return Check(name, False, f"sidecar does not bind this pack: {error}")
    return Check(name, True, detail(obj))


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
    bundle: bytes,
    *,
    tsa_certificate: bytes | None = None,
    tsa_root: bytes | None = None,
    rekor_keyring: Mapping[str, bytes] | None = None,
    require_anchored: bool = False,
    require_live: bool = False,
) -> VerificationResult:
    """Verify a bundle end to end and return a PASS/FAIL verdict with per-check detail.

    Every member's SHA-256 must match the recorded manifest digest, the archive's
    member set must equal the manifest's (no unlisted member may ride along, no
    duplicate names), and the contained evidence pack must pass
    :func:`verify_pack` - with ``tsa_certificate``/``tsa_root``/``rekor_keyring``
    threaded through so a customer-pinned TSA or a private Rekor instance
    verifies, and ``require_anchored``/``require_live`` enforced the same way as
    on a bare pack.
    A missing, extra, or mismatched member, or a failed pack verification, fails
    the result - so editing a bundled artifact, smuggling an unlisted one in, or
    altering the pack is caught. The result's ``anchored`` reflects the contained
    pack's anchoring.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                # A hostile ZIP can carry two members with the same name; readers
                # disagree on which wins, so a duplicate-name archive cannot
                # attest "exactly the manifest's member set" - refuse it outright.
                return _refused(
                    "bundle-members",
                    "the archive contains duplicate member names; readers "
                    "disagree on which copy wins, so the bundle is refused",
                )
            if MANIFEST_MEMBER not in names:
                return _refused("bundle-manifest", f"missing {MANIFEST_MEMBER}")
            manifest = json.loads(archive.read(MANIFEST_MEMBER))
            # Every field below is attacker-controlled JSON, so its SHAPE is a
            # claim to check, not a fact to assume. Reading them unchecked let a
            # hostile bundle crash verification - `[1,2,3]` reached `.get`,
            # `"members": null` reached `sorted`, a list `evidence` reached a dict
            # lookup - so `verify` exited 1 on a traceback instead of 4
            # (VERIFICATION FAILED). A tamper-evidence tool that crashes on a
            # hostile artifact has not refused it: a caller keying on exit 4 reads
            # the crash as the tool breaking, not as the bundle being bad.
            if not isinstance(manifest, dict):
                return _refused("bundle-manifest", f"{MANIFEST_MEMBER} is not a JSON object")
            # The manifest is unsigned, so it cannot be allowed to choose which
            # member is "the pack": a bundle carrying a genuine, anchored pack under
            # some other name and arbitrary bytes under evidence.json - the file the
            # README and the CLI call the canonical record - verified on the
            # strength of the member it pointed at.
            evidence_member = manifest.get("evidence", EVIDENCE_MEMBER)
            if evidence_member != EVIDENCE_MEMBER:
                return _refused(
                    "bundle-manifest",
                    f"{MANIFEST_MEMBER} names {evidence_member!r} as the evidence "
                    f"member; a bundle attests {EVIDENCE_MEMBER!r} and nothing else",
                )
            member_digests = manifest.get("members", {})
            if not isinstance(member_digests, dict):
                return _refused(
                    "bundle-manifest",
                    f"{MANIFEST_MEMBER} carries a non-object member-digest map",
                )
            member_bytes = {name: archive.read(name) for name in names if name != MANIFEST_MEMBER}
    except (zipfile.BadZipFile, KeyError, ValueError) as error:
        return VerificationResult(
            passed=False, checks=(Check("bundle", False, f"unreadable bundle: {error}"),)
        )

    checks: list[Check] = []
    for name in sorted(member_digests):
        present = member_bytes.get(name)
        if name not in _KNOWN_MEMBERS:
            checks.append(
                Check(
                    f"member:{name}",
                    False,
                    "not a member Sectum writes; the manifest is unsigned, so a listed "
                    "digest vouches for nothing - refused",
                )
            )
        elif present is None:
            checks.append(Check(f"member:{name}", False, "listed in manifest but missing"))
        elif _sha256(present) != member_digests[name]:
            checks.append(Check(f"member:{name}", False, "digest mismatch (member altered)"))
        elif name in _UNBOUND_MEMBERS:
            checks.append(
                Check(
                    f"member:{name}",
                    True,
                    "digest matches the unsigned manifest; this member is not bound to the pack",
                )
            )
        else:
            checks.append(Check(f"member:{name}", True, "digest matches the unsigned manifest"))

    # Reconcile the archive against the manifest. The loop above only covers
    # manifest-LISTED names, so a member physically present in the ZIP but absent
    # from bundle-manifest.json is otherwise uncovered by every digest check - and
    # the sidecar/PDF selection below reads the raw archive, so an unlisted forged
    # artifact (e.g. a fake erasure-attestation.pdf) would ride inside an otherwise
    # passing bundle and could even be delivered. Fail on any unlisted member so a
    # bundle attests EXACTLY its manifest's member set (the spec, section 8.1).
    for name in sorted(member_bytes):
        if name not in member_digests:
            checks.append(
                Check(
                    f"member:{name}",
                    False,
                    "present in the archive but not covered by the digest manifest",
                )
            )

    evidence_raw = member_bytes.get(evidence_member)
    if evidence_raw is None:
        checks.append(Check("evidence-pack", False, f"missing evidence member {evidence_member!r}"))
        return VerificationResult(passed=False, checks=tuple(checks))
    stamped = check_raw_schema_stamps(evidence_raw)
    if stamped is not None:
        checks.append(stamped)
        return VerificationResult(passed=False, checks=tuple(checks))
    try:
        pack = EvidencePack.model_validate_json(evidence_raw)
    except ValueError as error:
        checks.append(Check("evidence-pack", False, f"unparsable evidence pack: {error}"))
        return VerificationResult(passed=False, checks=tuple(checks))

    # Bind the bundled audit PDF and attestation sidecars to the pack, exactly as
    # the standalone ``sectum-ai verify`` binds the on-disk siblings. Without this a
    # rebuilt bundle whose ``audit-pack.pdf`` was swapped for a forged "zero
    # leakage" PDF (its digest re-recorded in bundle-manifest.json) - or whose
    # sidecar attests a different run - would pass on the member-digest checks
    # alone, breaking the tamper-evidence guarantee (the spec, section 8.1; ADR-0016).
    # Bind the bundled run record to the attested pack. run.json is the detailed
    # record the auditor actually reads - findings and evidence spans - and the
    # member-digest loop above only proves it matches bundle-manifest.json, which a
    # forger rebuilds along with it. The pack already carries the same record, so
    # the binding is free: a run.json whose findings were deleted no longer earns
    # an affirmative "digest matches" (the spec, section 8.1).
    run_raw = member_bytes.get(RUN_MEMBER)
    if run_raw is not None:
        try:
            bundled_run = json.loads(run_raw)
        except ValueError as error:
            checks.append(Check("bundled-run", False, f"unparsable {RUN_MEMBER}: {error}"))
        else:
            attested_run = json.loads(pack.run_result.model_dump_json())
            if bundled_run == attested_run:
                checks.append(Check("bundled-run", True, f"{RUN_MEMBER} matches the attested run"))
            else:
                checks.append(
                    Check(
                        "bundled-run",
                        False,
                        f"{RUN_MEMBER} does not match the run this pack attests; it was "
                        "altered or replaced after signing",
                    )
                )

    # Every present PDF is bound, not the first one found: a second, forged PDF
    # beside the genuine one used to ride on the first one's binding.
    present_pdfs = [name for name in _PDF_MEMBERS if name in member_bytes]
    pdf_bytes = member_bytes[present_pdfs[0]] if present_pdfs else None
    pack_result = verify_pack(
        pack,
        tsa_certificate=tsa_certificate,
        tsa_root=tsa_root,
        rekor_keyring=rekor_keyring,
        pdf_bytes=pdf_bytes,
        require_anchored=require_anchored,
        require_live=require_live,
    )
    # A bundle that binds a PDF and does not carry it FAILs below. `verify_pack`
    # emits its own, non-failing "not supplied" note for the standalone case, which
    # is the right answer there and the wrong one here - drop it so the bundle's
    # verdict is the only `audit-pdf` line.
    checks.extend(
        check
        for check in pack_result.checks
        if not (check.name == "audit-pdf" and pdf_bytes is None)
    )
    for name in present_pdfs:
        if pack.pdf_ref is None:
            # verify_pack checks a PDF only when the pack binds one; a bundled PDF
            # the pack does not bind is a delivered, unverified auditor document.
            checks.append(
                Check(
                    f"audit-pdf:{name}", False, "the pack binds no pdf_ref, so this PDF is unbound"
                )
            )
        elif name != present_pdfs[0]:
            checks.append(_check_pdf(pack.pdf_ref, member_bytes[name], name=f"audit-pdf:{name}"))
    if pack.pdf_ref is not None and pdf_bytes is None:
        checks.append(
            Check(
                "audit-pdf",
                False,
                "the pack binds a pdf_ref but the bundle has no audit PDF member",
            )
        )
    for name in _INTOTO_MEMBERS:
        if name in member_bytes:
            checks.append(
                _check_sidecar(
                    f"in-toto-attestation:{name}",
                    member_bytes[name],
                    lambda obj: verify_in_toto_statement(obj, pack),
                )
            )
    dsse_raw = member_bytes.get(DSSE_MEMBER)
    if dsse_raw is not None:
        checks.append(
            _check_sidecar(
                "dsse-envelope",
                dsse_raw,
                lambda obj: verify_dsse_envelope(obj, pack),
                dsse_binding_detail,
            )
        )
    return VerificationResult(
        passed=all(check.ok for check in checks),
        checks=tuple(checks),
        anchored=pack_result.anchored,
    )
