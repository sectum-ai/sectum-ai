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

from sectum_ai.evidence.controls import _ERASURE_PROBE_IDS, live_surfaces
from sectum_ai.evidence.labels import backing_surface, leak_label
from sectum_ai.spec import Finding, FindingStatus, RunResult, Severity, SurfaceProvenance

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


def _scope_prefix(recorded: str | None) -> str:
    """The message prefix stating which stack a result describes.

    Three-valued, like the property beside it: the prose stayed two-valued when
    the label went three-valued, so an UNRECORDED surface was told it "describes
    Sectum's built-in fake" - stating something the record does not.
    """
    if recorded == SurfaceProvenance.LIVE.value:
        return ""
    if recorded is None:
        return "[surface provenance not recorded - not evidence of a live backend] "
    return "[synthetic surface - describes Sectum's built-in fake, not your stack] "


def _describes_a_fake(finding: Finding, live: frozenset[str]) -> bool:
    """Whether this finding's backing surface was anything but a live backend.

    Keyed on an explicit LIVE, like every sibling that answers this question
    (`confirmed_on_live_surfaces` in the JSON summary, `live_surfaces` in the
    control mappings and the OSCAL projection): a surface whose provenance the
    record does not state is not evidence that it was live.

    GitHub renders one alert per result, so a run-level provenance property is
    invisible where it matters: an all-synthetic demo raised 229 `error` alerts
    (177 of them at `security-severity: 9.5`), indistinguishable from a
    production scan's.
    Every other renderer says so inline - the text summary warns, the JSON
    carries `confirmed_on_live_surfaces`, OSCAL asserts nothing, the PDF says
    "a demonstration, not an attestation".
    """
    return backing_surface(finding) not in live


def _result_level(finding: Finding, live: frozenset[str] = frozenset()) -> str:
    """SARIF level for a finding; unverified and fake-backed never exceed ``note``."""
    if finding.status is not FindingStatus.CONFIRMED:
        return "note"
    if _describes_a_fake(finding, live):
        return "note"
    return _LEVEL_BY_SEVERITY[finding.severity]


def _security_severity(finding: Finding, live: frozenset[str] = frozenset()) -> str:
    """GitHub ``security-severity`` for a finding; unverified candidates are floored.

    A CONFIRMED finding reports its severity bucket. An UNVERIFIED candidate is
    floored to the informational bucket so GitHub never renders it as a high-
    severity alert — the same anti-over-claim cap :func:`_result_level` applies to
    the ``level``, kept consistent because GitHub badges security alerts by
    ``security-severity``, not ``level``.
    """
    if finding.status is not FindingStatus.CONFIRMED:
        return _UNVERIFIED_SECURITY_SEVERITY
    if _describes_a_fake(finding, live):
        return _UNVERIFIED_SECURITY_SEVERITY
    return _SECURITY_SEVERITY[finding.severity]


def _rule(
    probe_id: str, findings: list[Finding], live: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """Build the SARIF reporting descriptor (rule) for one probe id.

    The rule's ``security-severity`` and default ``level`` track the worst
    *confirmed* finding the probe produced. A probe that produced only unverified
    candidates advertises the informational bucket + ``note``, so an
    unverified-only rule never renders as a high-severity GitHub alert (which is
    badged by the rule's ``security-severity``, not its ``level``).
    """
    # A rule whose every confirmed finding sits on a fake advertises the
    # informational bucket, for the same reason an unverified-only rule does.
    confirmed = [
        f
        for f in findings
        if f.status is FindingStatus.CONFIRMED and not _describes_a_fake(f, live)
    ]
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
        "shortDescription": {
            "text": (
                f"Residual-data finding from the {probe_id} probe"
                if probe_id in _ERASURE_PROBE_IDS
                else f"Cross-principal leak finding from the {probe_id} probe"
            )
        },
        "helpUri": _HELP_URI,
        "defaultConfiguration": {"level": level},
        "properties": {
            "tags": tags,
            "security-severity": security_severity,
        },
    }


def _result(
    finding: Finding,
    live: frozenset[str] = frozenset(),
    run_provenance: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the SARIF result for a single finding."""
    run_provenance = run_provenance or {}
    detail = finding.evidence_span or (
        f"marker {finding.marker_id} owned by tenant {finding.owner_tenant_id} "
        f"observed in tenant {finding.observed_in_tenant_id}"
    )
    return {
        "ruleId": finding.probe_id,
        "level": _result_level(finding, live),
        "message": {
            "text": (
                _scope_prefix(run_provenance.get(backing_surface(finding)))
                + f"{finding.severity.value.upper()} {leak_label(finding)} on "
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
            "security-severity": _security_severity(finding, live),
            "backingSurface": backing_surface(finding),
            # Three-valued, like every sibling: `verify`'s run-scope, `score`'s
            # UNRECORDED scope, the PDF's "Surface provenance: not recorded" and
            # OSCAL all distinguish "the record does not say" from "the record says
            # SYNTHETIC". Labelling an unstated surface SYNTHETIC would state
            # something the record does not.
            "surfaceProvenance": run_provenance.get(backing_surface(finding), "UNRECORDED"),
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
    live = live_surfaces(run)
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
                        "rules": [_rule(pid, fs, live) for pid, fs in by_probe.items()],
                    }
                },
                "results": [
                    _result(finding, live, dict(run.surface_provenance)) for finding in findings
                ],
                "properties": {
                    "runId": run.run_id,
                    "scenarioHash": run.scenario_hash,
                    "manifestHash": run.manifest_hash,
                    # Which stack the results describe. Absent from the projection,
                    # an all-synthetic demo read exactly like a production scan.
                    "surfaceProvenance": dict(run.surface_provenance),
                },
            }
        ],
    }
