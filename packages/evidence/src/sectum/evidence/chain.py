"""The evidence chain: canonicalize a run, hash it, and timestamp the digest.

The engineering spec, section 8. An ``EvidencePack`` is tamper-evident:
``sectum verify`` recomputes the run digest and checks it against the timestamp
token, so any edit to the run record is detected.

The RFC 3161 TSA and Sigstore Rekor anchors are pluggable behind the
``Timestamper`` protocol; this module ships a deterministic local timestamper
for offline and development use. Production runs configure a real TSA and Rekor.
"""

import json
from datetime import UTC, datetime
from typing import Protocol

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


class LocalTimestamper:
    """A deterministic, offline timestamper for development and tests.

    It records the digest and a wall-clock time as a JSON token; it is not an
    external anchor. Production configures an RFC 3161 TSA and Sigstore Rekor
    (the engineering spec, section 8.2).
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
    """Return the SHA-256 of the run result's canonical JSON form."""
    return canonical_hash(run_result)


def build_evidence_pack(
    run_result: RunResult,
    manifest: GroundTruthManifest,
    *,
    control_mappings: tuple[ControlMapping, ...] = (),
    timestamper: Timestamper | None = None,
) -> EvidencePack:
    """Assemble a tamper-evident ``EvidencePack`` for a completed run."""
    stamper = timestamper if timestamper is not None else LocalTimestamper()
    return EvidencePack(
        run_result=run_result,
        manifest_hash=canonical_hash(manifest),
        tsa_token=stamper.timestamp(run_digest(run_result)),
        control_mappings=control_mappings,
    )
