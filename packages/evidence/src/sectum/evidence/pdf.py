"""Audit-pack renderer: an EvidencePack rendered to an auditor-facing PDF.

The engineering spec, sections 8.3 and 18. v1 uses reportlab (pure Python, no
system libraries). ADR-0002 keeps the renderer theme-pluggable; a richer,
HTML-templated theme is a later refinement.
"""

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from sectum.evidence.chain import run_digest
from sectum.evidence.controls import COVERAGE_DISCLAIMER
from sectum.spec import ControlMapping, EvidencePack, Finding, FindingStatus


def _finding_controls(finding: Finding) -> str:
    """Return a finding's mapped control IDs as ``OWASP ...; ATLAS ...; NIST ...``.

    The engineering spec, section 18: each finding carries the controls its
    probe maps to. Empty frameworks are omitted - an erasure finding has no
    ATLAS technique, and an unclassified finding has no OWASP class - so a
    finding carrying no control IDs at all yields ``""`` (no suffix is rendered).
    """
    parts: list[str] = []
    if finding.owasp_llm:
        parts.append(f"OWASP {finding.owasp_llm}")
    if finding.atlas:
        parts.append(f"ATLAS {', '.join(finding.atlas)}")
    if finding.nist:
        parts.append(f"NIST {', '.join(finding.nist)}")
    return "; ".join(parts)


def _finding_lines(findings: tuple[Finding, ...]) -> list[str]:
    """Return one escaped summary line per finding, or a single 'none' line.

    Each line ends with the finding's mapped control IDs (OWASP / ATLAS / NIST)
    when it carries any, so an auditor reads per-finding control coverage inline.
    """
    if not findings:
        return ["No findings were recorded for this run."]
    lines: list[str] = []
    for finding in findings:
        line = (
            f"<b>{escape(finding.severity.value)}</b> - {escape(finding.probe_id)} "
            f"on {escape(finding.surface.value)}: marker "
            f"{escape(finding.marker_id or 'n/a')} ({escape(finding.status.value)})"
        )
        controls = _finding_controls(finding)
        if controls:
            line += f" [{escape(controls)}]"
        lines.append(line)
    return lines


def _control_lines(mappings: tuple[ControlMapping, ...]) -> list[str]:
    """Return one escaped line per compliance control mapping."""
    return [
        f"<b>{escape(mapping.framework)}</b> "
        f"({escape(', '.join(mapping.control_ids))}): {escape(mapping.assertion)}"
        for mapping in mappings
    ]


def render_audit_pack(pack: EvidencePack, output: Path) -> None:
    """Render an ``EvidencePack`` to an auditor-facing PDF at ``output``."""
    styles = getSampleStyleSheet()
    heading = styles["Heading2"]
    body = styles["BodyText"]
    run = pack.run_result
    confirmed = sum(1 for finding in run.findings if finding.status is FindingStatus.CONFIRMED)

    flow: list[Any] = [
        Paragraph("Sectum AI - Verification Evidence Pack", styles["Title"]),
        Paragraph(f"Run {escape(run.run_id)}", body),
        Spacer(1, 16),
        Paragraph("Verification summary", heading),
    ]
    summary = (
        ("Run started", run.started_at.isoformat()),
        ("Run finished", run.finished_at.isoformat()),
        ("Findings recorded", str(len(run.findings))),
        ("Confirmed cross-tenant findings", str(confirmed)),
    )
    flow += [
        Paragraph(f"<b>{escape(label)}:</b> {escape(value)}", body) for label, value in summary
    ]

    flow += [Spacer(1, 12), Paragraph("Findings", heading)]
    flow += [Paragraph(line, body) for line in _finding_lines(run.findings)]

    flow += [Spacer(1, 12), Paragraph("Compliance control coverage", heading)]
    flow += [Paragraph(line, body) for line in _control_lines(pack.control_mappings)]
    flow.append(Paragraph(f"<i>{escape(COVERAGE_DISCLAIMER)}</i>", body))

    flow += [Spacer(1, 12), Paragraph("Integrity and independent verification", heading)]
    integrity = (
        ("Run digest (SHA-256)", run_digest(run)),
        ("Manifest hash", pack.manifest_hash),
        ("Timestamp token", pack.tsa_token or "none"),
    )
    flow += [
        Paragraph(f"<b>{escape(label)}:</b> {escape(value)}", body) for label, value in integrity
    ]
    flow.append(
        Paragraph(
            "Verify this pack independently by recomputing the run digest and "
            "checking it against the timestamp token (the sectum verify command).",
            body,
        )
    )

    document = SimpleDocTemplate(str(output), pagesize=LETTER, title="Sectum AI Evidence Pack")
    document.build(flow)
