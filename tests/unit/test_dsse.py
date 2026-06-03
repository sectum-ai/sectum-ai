"""Tests for the DSSE in-toto envelope (the engineering spec, sections 8 and 13)."""

import base64
import json
from datetime import UTC, datetime

import pytest

from sectum_ai.evidence import (
    PAYLOAD_TYPE,
    build_dsse_envelope,
    build_evidence_pack,
    envelope_statement,
    pae,
    verify_dsse_envelope,
)
from sectum_ai.spec import (
    EvidenceError,
    EvidencePack,
    GroundTruthManifest,
    RunMetrics,
    RunResult,
    canonical_hash,
)


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
    return build_evidence_pack(run, manifest)


def test_pae_matches_the_dsse_spec_encoding() -> None:
    # PAE("application/vnd.in-toto+json", b"x") per the DSSE spec.
    assert pae("ty", b"body") == b"DSSEv1 2 ty 4 body"


def test_build_envelope_carries_the_statement() -> None:
    envelope = build_dsse_envelope(_pack())
    assert envelope["payloadType"] == PAYLOAD_TYPE
    statement = json.loads(base64.b64decode(envelope["payload"]))
    assert statement["_type"] == "https://in-toto.io/Statement/v1"
    assert envelope_statement(envelope) == statement


def test_envelope_round_trips_through_verify() -> None:
    pack = _pack()
    verify_dsse_envelope(build_dsse_envelope(pack), pack)  # no raise == pass


def test_an_envelope_for_another_run_fails_verification() -> None:
    # An envelope whose statement binds a different run digest must not verify
    # against this pack (a re-pointed/swapped envelope).
    other_envelope = build_dsse_envelope(_pack(run_id="run-other"))
    with pytest.raises(EvidenceError, match="subject"):
        verify_dsse_envelope(other_envelope, _pack(run_id="run-1"))


def test_a_wrong_payload_type_is_rejected() -> None:
    envelope = build_dsse_envelope(_pack())
    envelope["payloadType"] = "application/json"
    with pytest.raises(EvidenceError, match="in-toto DSSE envelope"):
        envelope_statement(envelope)


def test_a_corrupt_payload_is_rejected() -> None:
    envelope = build_dsse_envelope(_pack())
    envelope["payload"] = "not-base64!!!"
    with pytest.raises(EvidenceError):
        envelope_statement(envelope)
