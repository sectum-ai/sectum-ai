"""Tests for the SARIF 2.1.0 findings export (``sectum_ai.evidence.sarif``)."""

from datetime import UTC, datetime
from uuid import UUID

from sectum_ai.evidence import SARIF_VERSION, run_to_sarif
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


def _run(*findings: Finding) -> RunResult:
    moment = datetime(2026, 5, 18, tzinfo=UTC)
    return RunResult(
        run_id="run-1",
        scenario_hash="scenario-hash",
        manifest_hash="manifest-hash",
        started_at=moment,
        finished_at=moment,
        findings=tuple(findings),
        metrics=RunMetrics(),
    )


def test_emits_a_valid_2_1_0_envelope() -> None:
    sarif = run_to_sarif(_run(_finding("f-1")), tool_version="9.9.9")
    assert sarif["version"] == SARIF_VERSION == "2.1.0"
    assert str(sarif["$schema"]).endswith("sarif-2.1.0.json")
    (run,) = sarif["runs"]
    driver = run["tool"]["driver"]
    assert driver["name"] == "Sectum AI"
    assert driver["version"] == "9.9.9"
    assert run["properties"]["runId"] == "run-1"


def test_one_result_per_finding_and_one_rule_per_probe() -> None:
    findings = (
        _finding("f-1", probe_id="rag-entity-bleed"),
        _finding("f-2", probe_id="rag-entity-bleed"),
        _finding("f-3", probe_id="tenant-boundary-fetch"),
    )
    (run,) = run_to_sarif(_run(*findings))["runs"]
    assert len(run["results"]) == 3
    assert {rule["id"] for rule in run["tool"]["driver"]["rules"]} == {
        "rag-entity-bleed",
        "tenant-boundary-fetch",
    }
    first = run["results"][0]
    assert first["ruleId"] == "rag-entity-bleed"
    assert first["partialFingerprints"]["sectumFindingId"] == "f-1"


def test_level_is_severity_driven_for_confirmed_findings() -> None:
    (run,) = run_to_sarif(_run(_finding("f-1", severity=Severity.CRITICAL)))["runs"]
    assert run["results"][0]["level"] == "error"


def test_unverified_candidate_never_exceeds_note() -> None:
    # The manifest-grounded, zero-FP headline must not be overstated in a Security
    # tab: an unverified candidate — even at CRITICAL severity — is only a `note`.
    finding = _finding("f-1", severity=Severity.CRITICAL, status=FindingStatus.UNVERIFIED)
    (run,) = run_to_sarif(_run(finding))["runs"]
    result = run["results"][0]
    assert result["level"] == "note"
    assert result["properties"]["status"] == "unverified"
    # GitHub badges a security alert by security-severity (not level), so an
    # unverified candidate's security-severity is ALSO floored to the Low band —
    # otherwise a critical candidate would still render as a Critical alert.
    assert float(result["properties"]["security-severity"]) < 4.0


def test_rule_security_severity_tracks_the_worst_confirmed_finding() -> None:
    findings = (
        _finding("f-1", probe_id="p", severity=Severity.LOW),
        _finding("f-2", probe_id="p", severity=Severity.CRITICAL),
    )
    (run,) = run_to_sarif(_run(*findings))["runs"]
    (rule,) = run["tool"]["driver"]["rules"]
    assert rule["properties"]["security-severity"] == "9.5"  # critical, not low


def test_rule_with_only_unverified_findings_is_floored_to_low() -> None:
    # A probe that produced only unverified candidates must not advertise a
    # high-severity rule: GitHub badges the alert by the rule's security-severity,
    # so an unverified-only rule stays in the Low band with a `note` default.
    finding = _finding(
        "f-1", probe_id="p", severity=Severity.CRITICAL, status=FindingStatus.UNVERIFIED
    )
    (rule,) = run_to_sarif(_run(finding))["runs"][0]["tool"]["driver"]["rules"]
    assert float(rule["properties"]["security-severity"]) < 4.0
    assert rule["defaultConfiguration"]["level"] == "note"


def test_empty_run_has_no_results_or_rules() -> None:
    (run,) = run_to_sarif(_run())["runs"]
    assert run["results"] == []
    assert run["tool"]["driver"]["rules"] == []
