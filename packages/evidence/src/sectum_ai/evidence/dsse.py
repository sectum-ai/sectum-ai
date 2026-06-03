"""DSSE envelopes for the in-toto attestation (the engineering spec, sections 8 and 13).

The in-toto Statement (:mod:`sectum_ai.evidence.intoto`) is a tool-agnostic view of an
evidence pack. A DSSE envelope (Dead Simple Signing Envelope) is the standard
container that carries that Statement together with one or more signatures over
its Pre-Authentication Encoding (PAE), and is the body of a Sigstore Rekor
``dsse`` log entry.

This module is standard-library only: it builds and reads the envelope and
computes the PAE that a signer signs. Keyless Sigstore signing of that PAE lives
in :mod:`sectum_ai.evidence.sigstore` behind the optional ``[sigstore]`` extra; an
unsigned envelope is still a valid, verifiable carrier of the Statement (its
trust root remains the pack's own timestamp/transparency anchors, per ADR-0016).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

from sectum_ai.evidence.intoto import to_in_toto_statement, verify_in_toto_statement
from sectum_ai.spec import EvidenceError, EvidencePack

# DSSE payloadType for an in-toto Statement (the in-toto spec's registered type).
PAYLOAD_TYPE = "application/vnd.in-toto+json"


def pae(payload_type: str, payload: bytes) -> bytes:
    """Return the DSSE Pre-Authentication Encoding of ``payload``.

    ``PAE(type, body) = "DSSEv1" SP len(type) SP type SP len(body) SP body`` with
    lengths in ASCII decimal. Signing the PAE (not the raw payload) binds the
    payload to its type, so a signature cannot be replayed under a different type.
    """
    return b"DSSEv1 %d %s %d %s" % (
        len(payload_type),
        payload_type.encode("utf-8"),
        len(payload),
        payload,
    )


def build_dsse_envelope(pack: EvidencePack) -> dict[str, Any]:
    """Build an (unsigned) DSSE envelope carrying the pack's in-toto Statement.

    The envelope's ``payload`` is the base64 of the canonical Statement JSON and
    its ``payloadType`` is the in-toto type. ``signatures`` is empty here; a
    Sigstore signer fills it by signing :func:`pae` of the payload.
    """
    statement = to_in_toto_statement(pack)
    payload = json.dumps(statement, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "payloadType": PAYLOAD_TYPE,
        "payload": base64.b64encode(payload).decode("ascii"),
        "signatures": [],
    }


def envelope_statement(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Decode and return the in-toto Statement carried by a DSSE envelope.

    Raises :class:`~sectum_ai.spec.EvidenceError` if the envelope is malformed or its
    payload is not the in-toto type.
    """
    if envelope.get("payloadType") != PAYLOAD_TYPE:
        raise EvidenceError(f"not an in-toto DSSE envelope: {envelope.get('payloadType')!r}")
    raw = envelope.get("payload")
    if not isinstance(raw, str):
        raise EvidenceError("DSSE envelope has no base64 payload")
    try:
        decoded = base64.b64decode(raw, validate=True)
        statement = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as error:
        raise EvidenceError(f"DSSE envelope payload is not valid JSON: {error}") from error
    if not isinstance(statement, dict):
        raise EvidenceError("DSSE envelope payload is not a JSON object")
    return statement


def verify_dsse_envelope(envelope: Mapping[str, Any], pack: EvidencePack) -> None:
    """Verify a DSSE envelope carries an in-toto Statement that binds ``pack``.

    Decodes the envelope payload and re-runs :func:`verify_in_toto_statement`, so a
    swapped or re-pointed envelope that no longer attests this pack's run digest is
    rejected. Signature verification (when the envelope is Sigstore-signed) is the
    additional concern of :mod:`sectum_ai.evidence.sigstore`.
    """
    verify_in_toto_statement(envelope_statement(envelope), pack)
