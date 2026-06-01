"""in-toto attestation wrapping for the evidence chain (the engineering spec, section 13).

An :class:`~sectum.spec.EvidencePack` can be re-expressed as an
`in-toto Attestation <https://github.com/in-toto/attestation>`_ Statement (v1):
a standard, tool-agnostic envelope that binds a *subject* (here, the run,
identified by its canonical digest) to a *predicate* (here, the verification
result - the test conditions, metrics, control mappings, and which integrity
anchors the pack carries).

The Statement is a derived view of the pack: it is produced from the pack and
verified back against it, so it adds an interoperable format without changing
the pack's own schema. It carries no new trust - the pack's timestamp and
transparency-log anchors remain the cryptographic root. The Statement can be
wrapped in a DSSE envelope and logged to Rekor (the ``dsse`` entry type) for
signed distribution; that envelope is left to the caller.

This module is standard-library only.
"""

import json
from collections.abc import Mapping
from typing import Any

from sectum.evidence.chain import run_digest
from sectum.spec import EvidenceError, EvidencePack

# The in-toto Attestation Framework v1 statement type.
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
# Sectum AI's predicate type: a multi-tenant isolation verification result.
PREDICATE_TYPE = "https://sectum.ai/attestation/multi-tenant-verification/v1"


def _is_external_timestamp_anchor(token: str | None) -> bool:
    """True only for a real external RFC 3161 timestamp anchor.

    A genuine TSA returns a signed *binary* token (not JSON); the local
    development timestamper returns a JSON token that ``sectum verify`` binds to
    the digest but reports as *unanchored* (no independent time or authority).
    The predicate's anchor flags must match ``verify_pack``, so a JSON token -
    the local-dev token, or anything impersonating a TSA - does not count as an
    external anchor; only a non-JSON binary token does.
    """
    if token is None:
        return False
    try:
        json.loads(token)
    except (json.JSONDecodeError, ValueError):
        return True
    return False


def to_in_toto_statement(pack: EvidencePack) -> dict[str, Any]:
    """Wrap an evidence pack as an in-toto Statement (v1).

    The subject is the run, bound by the SHA-256 of its canonical form - the run
    identifier. (The timestamp and transparency-log anchors bind the broader
    whole-pack ``attested_digest``, a superset that also covers the manifest
    hash, control mappings, PDF reference, and log flag; see ADR-0016.) The
    predicate is the verification result: the scenario and manifest hashes, the
    run metrics, the finding count, the control mappings, and which integrity
    anchors are present.
    """
    run = pack.run_result
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": run.run_id, "digest": {"sha256": run_digest(run)}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "schema_version": pack.schema_version,
            "scenario_hash": run.scenario_hash,
            "manifest_hash": pack.manifest_hash,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat(),
            "metrics": run.metrics.model_dump(mode="json"),
            "finding_count": len(run.findings),
            "control_mappings": [
                mapping.model_dump(mode="json") for mapping in pack.control_mappings
            ],
            "anchors": {
                "timestamp": _is_external_timestamp_anchor(pack.tsa_token),
                "transparency_log": pack.rekor_proof is not None,
            },
        },
    }


def verify_in_toto_statement(statement: Mapping[str, Any], pack: EvidencePack) -> None:
    """Verify an in-toto Statement binds ``pack``'s run digest.

    Checks the statement is a Sectum v1 attestation whose subject digest equals
    the pack's recomputed run digest. Raises :class:`~sectum.spec.EvidenceError`
    if the statement is the wrong type or attests a different run.
    """
    if statement.get("_type") != STATEMENT_TYPE:
        raise EvidenceError(f"not an in-toto v1 statement: {statement.get('_type')!r}")
    if statement.get("predicateType") != PREDICATE_TYPE:
        raise EvidenceError(f"not a Sectum attestation: {statement.get('predicateType')!r}")
    digest = run_digest(pack.run_result)
    subjects = statement.get("subject", [])
    if not isinstance(subjects, list) or not _subject_binds_digest(subjects, digest):
        raise EvidenceError("the attestation subject does not match the pack's run digest")


def _subject_binds_digest(subjects: list[Any], digest: str) -> bool:
    for subject in subjects:
        if isinstance(subject, Mapping):
            recorded = subject.get("digest")
            if isinstance(recorded, Mapping) and recorded.get("sha256") == digest:
                return True
    return False
