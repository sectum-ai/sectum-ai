"""Tests for the in-toto attestation wrapping (the engineering spec, section 13)."""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from sectum_ai.evidence import (
    PREDICATE_TYPE,
    STATEMENT_TYPE,
    build_evidence_pack,
    control_mappings,
    run_digest,
    to_in_toto_statement,
    verify_in_toto_statement,
)
from sectum_ai.spec import (
    ControlMapping,
    EvidenceError,
    EvidencePack,
    Finding,
    FindingStatus,
    GroundTruthManifest,
    RunMetrics,
    RunResult,
    Severity,
    Surface,
    canonical_hash,
)


def _manifest() -> GroundTruthManifest:
    return GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())


def _run_result(manifest: GroundTruthManifest) -> RunResult:
    finding = Finding(
        finding_id="f-1",
        probe_id="rag-entity-bleed",
        severity=Severity.CRITICAL,
        confidence=1.0,
        status=FindingStatus.CONFIRMED,
        owner_tenant_id=UUID(int=0xB),
        observed_in_tenant_id=UUID(int=0xA),
        surface=Surface.VECTOR_DB,
    )
    moment = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
    return RunResult(
        run_id="run-1",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(manifest),
        started_at=moment,
        finished_at=moment,
        findings=(finding,),
        metrics=RunMetrics(confirmed_findings=1, retrieval_pivot_rate=0.5),
    )


def _pack() -> EvidencePack:
    manifest = _manifest()
    return build_evidence_pack(
        _run_result(manifest),
        manifest,
        control_mappings=(
            ControlMapping(
                framework="SOC 2", control_ids=("CC6.1",), assertion="logical access verified"
            ),
        ),
    )


def test_statement_has_the_in_toto_v1_shape() -> None:
    statement = to_in_toto_statement(_pack())
    assert statement["_type"] == STATEMENT_TYPE
    assert statement["predicateType"] == PREDICATE_TYPE
    assert isinstance(statement["subject"], list)
    subject = statement["subject"][0]
    assert subject["name"] == "run-1"
    assert subject["digest"]["sha256"] == run_digest(_pack().run_result)


def test_predicate_carries_the_verification_result() -> None:
    predicate = to_in_toto_statement(_pack())["predicate"]
    assert predicate["manifest_hash"] == _pack().manifest_hash
    assert predicate["finding_count"] == 1
    assert predicate["metrics"]["confirmed_findings"] == 1
    assert predicate["control_mappings"][0]["control_ids"] == ["CC6.1"]
    # The default LocalTimestamper emits a JSON token verify_pack treats as
    # unanchored, so the predicate's timestamp anchor is False (the dedicated
    # local-dev / real-token tests below pin both sides).
    assert predicate["anchors"] == {"timestamp": False, "transparency_log": False}


def test_the_statement_is_json_serializable() -> None:
    # The whole point of the in-toto format is a portable JSON artifact.
    dumped = json.dumps(to_in_toto_statement(_pack()))
    assert json.loads(dumped)["_type"] == STATEMENT_TYPE


def test_a_freshly_built_statement_verifies_against_its_pack() -> None:
    pack = _pack()
    verify_in_toto_statement(to_in_toto_statement(pack), pack)  # no raise


def test_a_statement_for_a_different_run_is_rejected() -> None:
    pack = _pack()
    statement = to_in_toto_statement(pack)
    other = pack.model_copy(
        update={"run_result": pack.run_result.model_copy(update={"run_id": "other"})}
    )
    with pytest.raises(EvidenceError, match="subject does not match"):
        verify_in_toto_statement(statement, other)


def test_a_statement_with_the_wrong_type_is_rejected() -> None:
    pack = _pack()
    statement = to_in_toto_statement(pack)
    statement["_type"] = "https://in-toto.io/Statement/v0.1"
    with pytest.raises(EvidenceError, match="not an in-toto v1 statement"):
        verify_in_toto_statement(statement, pack)


def test_a_statement_with_a_foreign_predicate_type_is_rejected() -> None:
    pack = _pack()
    statement = to_in_toto_statement(pack)
    statement["predicateType"] = "https://example.com/other/v1"
    with pytest.raises(EvidenceError, match="not a Sectum attestation"):
        verify_in_toto_statement(statement, pack)


def test_anchors_reflect_a_transparency_log_when_present() -> None:
    pack = _pack().model_copy(update={"rekor_proof": "{}"})
    predicate = to_in_toto_statement(pack)["predicate"]
    assert predicate["anchors"]["transparency_log"] is True


def test_anchors_timestamp_is_false_for_a_local_dev_token() -> None:
    # The default LocalTimestamper emits a JSON token that verify_pack binds but
    # reports as *unanchored* (not an independent RFC 3161 / Rekor anchor). The
    # in-toto predicate must agree, so its timestamp anchor reads False.
    predicate = to_in_toto_statement(_pack())["predicate"]
    assert predicate["anchors"]["timestamp"] is False


def test_anchors_timestamp_is_true_for_a_real_binary_token() -> None:
    # A genuine RFC 3161 TSA returns a signed *binary* token (not JSON) - a real
    # external anchor, so the predicate's timestamp flag is True.
    pack = _pack().model_copy(update={"tsa_token": "MIIB-binary-rfc3161-token"})
    predicate = to_in_toto_statement(pack)["predicate"]
    assert predicate["anchors"]["timestamp"] is True


@pytest.mark.parametrize(
    "statement",
    [
        {"_type": STATEMENT_TYPE, "predicateType": PREDICATE_TYPE, "subject": "not-a-list"},
        {"_type": STATEMENT_TYPE, "predicateType": PREDICATE_TYPE, "subject": [None, 5, "x"]},
        {"_type": STATEMENT_TYPE, "predicateType": PREDICATE_TYPE, "subject": [{"digest": "x"}]},
        {"_type": STATEMENT_TYPE, "predicateType": PREDICATE_TYPE, "subject": [{"digest": {}}]},
        {"_type": STATEMENT_TYPE, "predicateType": PREDICATE_TYPE},
    ],
)
def test_a_malformed_statement_is_rejected_not_crashed(statement: dict[str, object]) -> None:
    # A hostile statement (subject not a list, digest not a map, missing keys)
    # must raise a typed error, never an uncaught exception.
    with pytest.raises(EvidenceError):
        verify_in_toto_statement(statement, _pack())


def test_a_rewritten_predicate_does_not_bind_the_pack() -> None:
    # The predicate IS the verification result a downstream policy engine reads:
    # finding count, metrics, control mappings, and which anchors are present. The
    # subject digest covers only the run record, so a sidecar that keeps a truthful
    # subject while rewriting its predicate to "0 findings, fully anchored" was
    # itemized as binding this pack. Every predicate field is recomputable from the
    # pack, so any divergence must be rejected.
    manifest = _manifest()
    pack = build_evidence_pack(_run_result(manifest), manifest, control_mappings=control_mappings())
    honest = json.loads(json.dumps(to_in_toto_statement(pack)))
    verify_in_toto_statement(honest, pack)  # premise: the honest sidecar verifies

    forgeries: tuple[tuple[str, object], ...] = (
        ("finding_count", 0),
        ("anchors", {"timestamp": True, "transparency_log": True}),
        ("metrics", dict.fromkeys(honest["predicate"]["metrics"], 0)),
        ("scenario_hash", "forged"),
    )
    for key, value in forgeries:
        forged = json.loads(json.dumps(honest))
        forged["predicate"][key] = value
        with pytest.raises(EvidenceError, match="predicate"):
            verify_in_toto_statement(forged, pack)
