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
    sarif = run_to_sarif(
        _run(_finding("f-1", severity=Severity.CRITICAL)).model_copy(
            update={"surface_provenance": {"vector_db": "LIVE"}}
        )
    )
    (run,) = sarif["runs"]
    assert run["results"][0]["level"] == "error"


def test_a_run_that_records_no_provenance_is_not_evidence_of_a_live_backend() -> None:
    # `confirmed_on_live_surfaces` and the control mappings both key on an
    # explicit LIVE. Keying on an explicit SYNTHETIC instead would have let an
    # unstated surface render as a critical production alert.
    (run,) = run_to_sarif(_run(_finding("f-1", severity=Severity.CRITICAL)))["runs"]
    assert run["results"][0]["level"] == "note"
    # And the label says what the record says - not SYNTHETIC, which would state
    # something the record does not. Three-valued, like every sibling renderer.
    assert run["results"][0]["properties"]["surfaceProvenance"] == "UNRECORDED"


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
    sarif = run_to_sarif(
        _run(*findings).model_copy(update={"surface_provenance": {"vector_db": "LIVE"}})
    )
    (run,) = sarif["runs"]
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


def test_messages_label_each_finding_by_what_it_is() -> None:
    # Every result said "cross-tenant leak": an erasure residual (same tenant on
    # both sides), a cross-user leak inside one tenant, and the informational
    # 200-empty candidate all read as a confirmed cross-tenant breach.
    from uuid import uuid4

    residual = _finding("r").model_copy(update={"observed_in_tenant_id": _OWNER})
    user_a, user_b = uuid4(), uuid4()
    cross_user = _finding("u").model_copy(
        update={
            "observed_in_tenant_id": _OWNER,
            "owner_user_id": user_a,
            "observed_in_user_id": user_b,
        }
    )
    candidate = _finding("c", severity=Severity.INFO, status=FindingStatus.UNVERIFIED)
    messages = {
        r["partialFingerprints"]["sectumFindingId"]: r["message"]["text"]
        for r in run_to_sarif(_run(residual, cross_user, candidate, _finding("t")))["runs"][0][
            "results"
        ]
    }
    assert "residual-data finding" in messages["r"]
    assert "cross-user leak" in messages["u"]
    assert "cross-tenant candidate" in messages["c"]
    assert "cross-tenant leak" in messages["t"]


def test_the_run_carries_its_surface_provenance() -> None:
    run = _run().model_copy(update={"surface_provenance": {"vector_db": "SYNTHETIC"}})
    assert run_to_sarif(run)["runs"][0]["properties"]["surfaceProvenance"] == {
        "vector_db": "SYNTHETIC"
    }


def test_rule_text_names_the_probe_kind() -> None:
    residual = _finding("r", probe_id="gdpr-erasure-verification").model_copy(
        update={"observed_in_tenant_id": _OWNER}
    )
    rules = {
        r["id"]: r["shortDescription"]["text"]
        for r in run_to_sarif(_run(residual, _finding("t")))["runs"][0]["tool"]["driver"]["rules"]
    }
    assert rules["gdpr-erasure-verification"].startswith("Residual-data finding")
    assert rules["rag-entity-bleed"].startswith("Cross-principal leak finding")


def _run_with_provenance(*findings: Finding, **provenance: str) -> RunResult:
    return _run(*findings).model_copy(update={"surface_provenance": provenance})


def test_a_finding_on_a_fake_surface_is_not_a_high_severity_alert() -> None:
    # GitHub renders one alert per RESULT, so the run-level provenance property is
    # invisible where it matters: the demo run raised 256 `error` alerts at
    # security-severity 9.5, indistinguishable from a production scan's. Every
    # other renderer says so inline - the text summary warns, the JSON carries
    # `confirmed_on_live_surfaces`, OSCAL asserts nothing, the PDF calls itself a
    # demonstration.
    sarif = run_to_sarif(_run_with_provenance(_finding("f-1"), vector_db="SYNTHETIC"))
    result = sarif["runs"][0]["results"][0]
    assert result["level"] == "note"
    assert result["properties"]["security-severity"] == "1.0"
    assert result["properties"]["surfaceProvenance"] == "SYNTHETIC"
    assert result["message"]["text"].startswith("[synthetic surface")
    rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
    assert rule["defaultConfiguration"]["level"] == "note"
    assert rule["properties"]["security-severity"] == "1.0"


def test_the_same_finding_on_a_live_surface_is_a_critical_alert() -> None:
    sarif = run_to_sarif(_run_with_provenance(_finding("f-1"), vector_db="LIVE"))
    result = sarif["runs"][0]["results"][0]
    assert result["level"] == "error"
    assert result["properties"]["security-severity"] == "9.5"
    assert result["properties"]["surfaceProvenance"] == "LIVE"
    assert not result["message"]["text"].startswith("[synthetic surface")
    rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
    assert rule["defaultConfiguration"]["level"] == "error"


def test_an_unrecorded_surface_is_not_told_it_describes_a_fake() -> None:
    # The property went three-valued and the PROSE stayed two-valued, so a result
    # on a surface the record does not describe was told it "describes Sectum's
    # built-in fake" - stating something the record does not.
    sarif = run_to_sarif(_run(_finding("f-1")))
    message = sarif["runs"][0]["results"][0]["message"]["text"]
    assert message.startswith("[surface provenance not recorded"), message
    assert "built-in fake" not in message
