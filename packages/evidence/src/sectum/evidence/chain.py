"""The evidence chain: canonicalize a run, hash it, and timestamp the digest.

The engineering spec, section 8. An ``EvidencePack`` is tamper-evident:
``sectum verify`` recomputes the pack digest and checks it against the timestamp
token, so any edit to the attested content is detected.

The anchored digest binds the *whole* attested pack - the run record, the
manifest hash, the control mappings, the PDF reference, and whether the pack was
recorded in a transparency log - not just the run record. Editing the compliance
claims, repointing the PDF, or stripping the Rekor proof therefore all change
the digest and fail verification (ADR-0012).

The RFC 3161 TSA and Sigstore Rekor anchors are pluggable behind the
``Timestamper`` protocol; this module ships a deterministic local timestamper
for offline and development use. Production runs configure a real TSA and Rekor.
"""

import json
from datetime import UTC, datetime
from typing import Any, Protocol

from sectum.spec import (
    ControlMapping,
    EvidencePack,
    GroundTruthManifest,
    RunResult,
    canonical_hash,
)


class Timestamper(Protocol):
    """Produces a verifiable timestamp token for a digest."""

    def timestamp(self, digest: str) -> str:
        """Return a token attesting that ``digest`` existed at a point in time."""
        ...


class TransparencyLog(Protocol):
    """Records a digest in an append-only transparency log and returns its proof."""

    def record(self, digest: str) -> str:
        """Return a verifiable proof that ``digest`` was recorded in the log."""
        ...


class LocalTimestamper:
    """A deterministic, offline timestamper for development and tests.

    It records the digest and a wall-clock time as a JSON token; it is not an
    external anchor. ``sectum verify`` treats a ``local-dev`` token as binding
    the digest (so tampering is still caught) but marks it as *unanchored* - it
    does not attest an independent time or authority. Production configures an
    RFC 3161 TSA and Sigstore Rekor (the engineering spec, section 8.2).
    """

    tsa = "local-dev"

    def timestamp(self, digest: str) -> str:
        """Return a JSON token recording ``digest`` and the current time."""
        token = {
            "tsa": self.tsa,
            "digest": digest,
            "timestamped_at": datetime.now(UTC).isoformat(),
        }
        return json.dumps(token, sort_keys=True, separators=(",", ":"))


def run_digest(run_result: RunResult) -> str:
    """Return the SHA-256 of the run result's canonical JSON form.

    This identifies the run (the in-toto attestation subject, the human-readable
    PDF). The cryptographic anchors bind :func:`attested_digest`, which covers
    the whole pack, not just the run.
    """
    return canonical_hash(run_result)


def _attested_content(
    run_result: RunResult,
    manifest_hash: str,
    control_mappings: tuple[ControlMapping, ...],
    pdf_ref: str | None,
    anchored_in_log: bool,
) -> dict[str, Any]:
    """The full set of pack fields the anchored digest binds.

    Everything a verifier or auditor relies on - the run record, the manifest
    binding, the compliance claims, the audit-pack pointer, and whether the pack
    claims a transparency-log anchor - is included, so mutating any of it changes
    the digest.
    """
    return {
        "run_result": run_result.model_dump(mode="json"),
        "manifest_hash": manifest_hash,
        "control_mappings": [mapping.model_dump(mode="json") for mapping in control_mappings],
        "pdf_ref": pdf_ref,
        "anchored_in_log": anchored_in_log,
    }


def attested_digest(pack: EvidencePack) -> str:
    """Return the SHA-256 the anchors bind: the canonical hash of the whole pack.

    Recomputed by ``sectum verify`` from the pack's own fields and checked
    against the timestamp token and any Rekor proof. Any edit to the run record,
    manifest hash, control mappings, PDF reference, or transparency-log flag
    changes this digest and fails verification.
    """
    return canonical_hash(
        _attested_content(
            pack.run_result,
            pack.manifest_hash,
            pack.control_mappings,
            pack.pdf_ref,
            pack.anchored_in_log,
        )
    )


def build_evidence_pack(
    run_result: RunResult,
    manifest: GroundTruthManifest,
    *,
    control_mappings: tuple[ControlMapping, ...] = (),
    pdf_ref: str | None = None,
    timestamper: Timestamper | None = None,
    transparency_log: TransparencyLog | None = None,
) -> EvidencePack:
    """Assemble a tamper-evident ``EvidencePack`` for a completed run.

    The pack digest (:func:`attested_digest`, over the whole attested content)
    is timestamped (``timestamper``; the local timestamper by default) and, when
    a ``transparency_log`` is given, also recorded in it - the Sigstore Rekor
    anchor (the engineering spec, section 8.2). ``anchored_in_log`` records
    whether a transparency log was used and is itself bound into the digest, so a
    later attempt to strip the Rekor proof and skip the check is detected.
    """
    stamper = timestamper if timestamper is not None else LocalTimestamper()
    manifest_hash = canonical_hash(manifest)
    anchored_in_log = transparency_log is not None
    digest = canonical_hash(
        _attested_content(run_result, manifest_hash, control_mappings, pdf_ref, anchored_in_log)
    )
    return EvidencePack(
        run_result=run_result,
        manifest_hash=manifest_hash,
        tsa_token=stamper.timestamp(digest),
        rekor_proof=transparency_log.record(digest) if transparency_log is not None else None,
        control_mappings=control_mappings,
        pdf_ref=pdf_ref,
        anchored_in_log=anchored_in_log,
    )
