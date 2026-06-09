"""SARIF 2.1.0 projection of a run's findings.

GitHub code scanning (and most SAST dashboards) ingest SARIF, so emitting it
lets a Sectum AI run surface cross-tenant findings directly in a repository's
Security tab — the adoption path for the regression-gate use case. This is a
projection of :class:`~sectum_ai.spec.RunResult` findings onto the SARIF result
model for *visibility*; the canonical, signed, tamper-evident record remains
``evidence.json`` (the SARIF is derived and unsigned).

Mapping choices:
- one SARIF *rule* per distinct probe id (the catalog class that produced it);
- one SARIF *result* per :class:`~sectum_ai.spec.Finding`;
- the SARIF ``level`` is severity-driven for ``CONFIRMED`` findings, but an
  ``UNVERIFIED`` candidate is always ``note``;
- ``properties["security-severity"]`` (GitHub's 0-10 bucket, which badges the
  alert *independently of* ``level``) tracks the highest ``CONFIRMED`` severity;
  an ``UNVERIFIED`` candidate — and a probe that produced only candidates — is
  floored to the informational bucket. Capping both ``level`` and
  ``security-severity`` keeps the manifest-grounded, zero-false-positive headline
  from being overstated in the Security tab.
"""

from __future__ import annotations

from typing import Any

from sectum_ai.spec import Finding, FindingStatus, RunResult, Severity

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"
_INFORMATION_URI = "https://sectum.ai"
_HELP_URI = "https://docs.sectum.ai/attack-catalog/"

# SARIF's result level vocabulary is error|warning|note|none.
_LEVEL_BY_SEVERITY: dict[Severity, str] = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}

# GitHub code scanning buckets an alert from the rule's numeric security-severity.
_SECURITY_SEVERITY: dict[Severity, str] = {
    Severity.CRITICAL: "9.5",
    Severity.HIGH: "8.0",
    Severity.MEDIUM: "5.5",
    Severity.LOW: "3.0",
    Severity.INFO: "1.0",
}

# Highest-first ordering so a rule reports the worst severity it produced.
_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.INFO: 0,
}

# GitHub buckets a security alert by ``security-severity`` (numeric → Critical/
# High/Medium/Low badge), independently of the SARIF ``level``. So capping an
# unverified candidate's ``level`` at ``note`` is not enough on its own — its
# ``security-severity`` must also be floored, or the candidate would still render
# as a high-severity alert. An unverified candidate is informational until
# confirmed, so it takes the lowest (INFO) bucket — the anti-over-claim cap.
_UNVERIFIED_SECURITY_SEVERITY = _SECURITY_SEVERITY[Severity.INFO]


def _result_level(finding: Finding) -> str:
    """SARIF level for a finding; unverified candidates never exceed ``note``."""
    if finding.status is not FindingStatus.CONFIRMED:
        return "note"
    return _LEVEL_BY_SEVERITY[finding.severity]


def _security_severity(finding: Finding) -> str:
    """GitHub ``security-severity`` for a finding; unverified candidates are floored.

    A CONFIRMED finding reports its severity bucket. An UNVERIFIED candidate is
    floored to the informational bucket so GitHub never renders it as a high-
    severity alert — the same anti-over-claim cap :func:`_result_level` applies to
    the ``level``, kept consistent because GitHub badges security alerts by
    ``security-severity``, not ``level``.
    """
    if finding.status is not FindingStatus.CONFIRMED:
        return _UNVERIFIED_SECURITY_SEVERITY
    return _SECURITY_SEVERITY[finding.severity]


def _rule(probe_id: str, findings: list[Finding]) -> dict[str, Any]:
    """Build the SARIF reporting descriptor (rule) for one probe id.

    The rule's ``security-severity`` and default ``level`` track the worst
    *confirmed* finding the probe produced. A probe that produced only unverified
    candidates advertises the informational bucket + ``note``, so an
    unverified-only rule never renders as a high-severity GitHub alert (which is
    badged by the rule's ``security-severity``, not its ``level``).
    """
    confirmed = [f for f in findings if f.status is FindingStatus.CONFIRMED]
    if confirmed:
        worst = max(confirmed, key=lambda f: _SEVERITY_ORDER[f.severity])
        level = _LEVEL_BY_SEVERITY[worst.severity]
        security_severity = _SECURITY_SEVERITY[worst.severity]
    else:
        level = "note"
        security_severity = _UNVERIFIED_SECURITY_SEVERITY
    owasp = next((f.owasp_llm for f in findings if f.owasp_llm), "")
    tags = ["security", "multi-tenant-isolation"]
    if owasp:
        tags.append(owasp)
    return {
        "id": probe_id,
        "name": probe_id.replace("-", "_"),
        "shortDescription": {"text": f"Cross-tenant finding from the {probe_id} probe"},
        "helpUri": _HELP_URI,
        "defaultConfiguration": {"level": level},
        "properties": {
            "tags": tags,
            "security-severity": security_severity,
        },
    }


def _result(finding: Finding) -> dict[str, Any]:
    """Build the SARIF result for a single finding."""
    detail = finding.evidence_span or (
        f"marker {finding.marker_id} owned by tenant {finding.owner_tenant_id} "
        f"observed in tenant {finding.observed_in_tenant_id}"
    )
    return {
        "ruleId": finding.probe_id,
        "level": _result_level(finding),
        "message": {
            "text": (
                f"{finding.severity.value.upper()} cross-tenant leak on "
                f"{finding.surface.value}: {detail}"
            )
        },
        "locations": [{"logicalLocations": [{"name": finding.surface.value, "kind": "namespace"}]}],
        "partialFingerprints": {"sectumFindingId": finding.finding_id},
        "properties": {
            "status": finding.status.value,
            "confidence": finding.confidence,
            "surface": finding.surface.value,
            "ownerTenantId": str(finding.owner_tenant_id),
            "observedInTenantId": str(finding.observed_in_tenant_id),
            "markerId": finding.marker_id,
            "owaspLlm": finding.owasp_llm,
            "atlas": list(finding.atlas),
            "nist": list(finding.nist),
            "security-severity": _security_severity(finding),
        },
    }


def run_to_sarif(run: RunResult, *, tool_version: str = "0") -> dict[str, Any]:
    """Project a :class:`~sectum_ai.spec.RunResult` into a SARIF 2.1.0 log.

    Args:
        run: the completed run whose findings to export.
        tool_version: the Sectum AI version to stamp as the SARIF driver version.

    Returns:
        A SARIF 2.1.0 log as a JSON-serialisable ``dict`` — one run, one rule per
        distinct probe id, one result per finding. The canonical signed record is
        still ``evidence.json``; this projection is for code-scanning visibility.
    """
    findings = list(run.findings)
    by_probe: dict[str, list[Finding]] = {}
    for finding in findings:
        by_probe.setdefault(finding.probe_id, []).append(finding)
    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Sectum AI",
                        "informationUri": _INFORMATION_URI,
                        "version": tool_version,
                        "rules": [_rule(pid, fs) for pid, fs in by_probe.items()],
                    }
                },
                "results": [_result(finding) for finding in findings],
                "properties": {
                    "runId": run.run_id,
                    "scenarioHash": run.scenario_hash,
                    "manifestHash": run.manifest_hash,
                },
            }
        ],
    }
