"""Tests for the OSCAL 1.1.x assessment-results export (``sectum_ai.evidence.oscal``)."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sectum_ai.evidence import OSCAL_VERSION, run_to_oscal
from sectum_ai.evidence.controls import COVERAGE_DISCLAIMER, control_mappings
from sectum_ai.spec import (
    Finding,
    FindingStatus,
    RunMetrics,
    RunResult,
    Severity,
    Surface,
)

_OWNER = UUID(int=0xB)
_OBSERVED = UUID(int=0xA)


def _finding(
    finding_id: str,
    *,
    probe_id: str = "rag-entity-bleed",
    severity: Severity = Severity.CRITICAL,
    status: FindingStatus = FindingStatus.CONFIRMED,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        probe_id=probe_id,
        severity=severity,
        confidence=1.0,
        status=status,
        owner_tenant_id=_OWNER,
        observed_in_tenant_id=_OBSERVED,
        surface=Surface.VECTOR_DB,
        marker_id="marker-1",
        evidence_span="canary surfaced in the wrong tenant",
        owasp_llm="LLM08:2025",
        atlas=("AML.T0024",),
        nist=("MEASURE 2.7",),
    )


def _run(*findings: Finding, run_id: str = "run-1") -> RunResult:
    moment = datetime(2026, 5, 18, 12, 30, tzinfo=UTC)
    return RunResult(
        run_id=run_id,
        scenario_hash="scenario-hash",
        manifest_hash="manifest-hash",
        started_at=moment,
        finished_at=moment,
        findings=tuple(findings),
        metrics=RunMetrics(),
    )


def _doc(run: RunResult) -> dict[str, Any]:
    result: dict[str, Any] = run_to_oscal(run)["assessment-results"]
    return result


def test_emits_a_valid_assessment_results_envelope() -> None:
    doc = run_to_oscal(_run(_finding("f-1")), tool_version="9.9.9")
    assert OSCAL_VERSION == "1.1.2"
    ar = doc["assessment-results"]
    # Top-level required fields of an OSCAL assessment-results document.
    assert UUID(ar["uuid"])  # parseable UUID
    metadata = ar["metadata"]
    assert metadata["oscal-version"] == "1.1.2"
    assert metadata["version"] == "9.9.9"
    assert metadata["last-modified"] == "2026-05-18T12:30:00+00:00"
    assert "run-1" in metadata["title"]
    # Exactly one results entry, carrying the required result fields.
    (result,) = ar["results"]
    for key in ("uuid", "title", "description", "start", "observations", "findings"):
        assert key in result, key
    assert result["start"] == "2026-05-18T12:30:00+00:00"


def test_coverage_disclaimer_is_embedded_in_metadata_remarks() -> None:
    # The OSCAL consumer must see the same caveat the audit PDF carries: the
    # mappings are test-coverage assertions, not legal certification.
    metadata = _doc(_run(_finding("f-1")))["metadata"]
    assert metadata["remarks"] == COVERAGE_DISCLAIMER


def test_one_observation_per_finding_with_marker_grounded_evidence() -> None:
    findings = (_finding("f-1"), _finding("f-2", probe_id="tenant-boundary-fetch"))
    (result,) = _doc(_run(*findings))["results"]
    observations = result["observations"]
    assert len(observations) == 2
    first = observations[0]
    # An observation records that Sectum TESTED and what it saw.
    assert first["methods"] == ["TEST"]
    assert "canary surfaced in the wrong tenant" in first["description"]
    # The Sectum finding id is carried so the OSCAL evidence is traceable back to
    # the signed evidence.json record.
    props = {(p["name"], p["value"]) for p in first["props"]}
    assert ("sectum-finding-id", "f-1") in props
    assert ("sectum-surface", "vector_db") in props
    assert ("sectum-status", "confirmed") in props


def test_findings_cover_every_mapped_control_and_link_observations() -> None:
    (result,) = _doc(_run(_finding("f-1")))["results"]
    findings = result["findings"]
    # One OSCAL finding per (framework, control id) from control_mappings().
    expected = sum(len(m.control_ids) for m in control_mappings())
    assert len(findings) == expected
    target_ids = {f["target"]["target-id"] for f in findings}
    assert "CC6.1" in target_ids  # SOC 2
    assert "Article 17" in target_ids  # GDPR erasure
    # Every control finding links back to the lone observation.
    observation_uuid = result["observations"][0]["uuid"]
    for finding in findings:
        linked = {ref["observation-uuid"] for ref in finding["related-observations"]}
        assert observation_uuid in linked
        assert finding["target"]["type"] == "objective-id"


def test_confirmed_leak_marks_controls_not_satisfied() -> None:
    (result,) = _doc(_run(_finding("f-1", status=FindingStatus.CONFIRMED)))["results"]
    states = {f["target"]["status"]["state"] for f in result["findings"]}
    assert states == {"not-satisfied"}


def test_unverified_candidate_does_not_flip_a_control_to_failed() -> None:
    # An UNVERIFIED Sectum candidate is recorded as evidence (an observation) but
    # must never on its own present as a confirmed control failure - the
    # anti-over-claim guarantee.
    (result,) = _doc(_run(_finding("f-1", status=FindingStatus.UNVERIFIED)))["results"]
    # The candidate is still observed (evidence is not lost)...
    props = {(p["name"], p["value"]) for p in result["observations"][0]["props"]}
    assert ("sectum-status", "unverified") in props
    # ...but every control reads satisfied because nothing was *confirmed*.
    states = {f["target"]["status"]["state"] for f in result["findings"]}
    assert states == {"satisfied"}


def test_zero_findings_run_is_a_valid_tested_clean_attestation() -> None:
    # A run with no confirmed leaks must be a valid AR reading "tested, no
    # confirmed cross-tenant leakage", not an empty/ambiguous document.
    (result,) = _doc(_run())["results"]
    assert result["observations"] == []
    # Controls are still present (the run tested them) and read satisfied.
    assert len(result["findings"]) == sum(len(m.control_ids) for m in control_mappings())
    states = {f["target"]["status"]["state"] for f in result["findings"]}
    assert states == {"satisfied"}
    assert "no cross-tenant leakage was confirmed" in result["description"].lower()


def test_uuids_are_deterministic_from_run_id_not_random() -> None:
    # Same run -> byte-identical document (no uuid4); different run id -> different
    # document uuid. Determinism is required by the reproducibility contract.
    first = run_to_oscal(_run(_finding("f-1")), tool_version="1.0.0")
    again = run_to_oscal(_run(_finding("f-1")), tool_version="1.0.0")
    assert json.dumps(first, sort_keys=True) == json.dumps(again, sort_keys=True)
    other = run_to_oscal(_run(_finding("f-1"), run_id="run-2"), tool_version="1.0.0")
    assert other["assessment-results"]["uuid"] != first["assessment-results"]["uuid"]


def test_document_is_json_serialisable() -> None:
    # The CLI dispatch json.dumps() the document; a stray datetime would break it.
    doc = run_to_oscal(_run(_finding("f-1")), tool_version="1.0.0")
    reloaded = json.loads(json.dumps(doc))
    assert reloaded["assessment-results"]["metadata"]["oscal-version"] == "1.1.2"
