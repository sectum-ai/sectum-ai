"""Audit-pack renderer: an EvidencePack rendered to an auditor-facing PDF.

The engineering spec, sections 8.3 and 18. v1 uses reportlab (pure Python, no
system libraries). ADR-0002 keeps the renderer theme-pluggable; a richer,
HTML-templated theme is a later refinement.
"""

from enum import StrEnum
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from sectum.evidence.chain import run_digest
from sectum.evidence.controls import COVERAGE_DISCLAIMER
from sectum.spec import ControlMapping, EvidencePack, Finding, FindingStatus


class PdfEngine(StrEnum):
    """Which renderer produces the audit-pack PDF (the engineering spec, section 21).

    ``reportlab`` is the default: pure Python, no system libraries, always
    available. ``weasyprint`` is an HTML/CSS-templated alternative with a richer
    auditor-facing layout; it needs the ``weasyprint`` extra (and its system
    libraries) and is selected explicitly. Both engines render the same content.
    """

    REPORTLAB = "reportlab"
    WEASYPRINT = "weasyprint"


# Static scope/methodology narrative (the engineering spec, sections 8.3, 6.4,
# and 8.4). Factual and anti-hype (section 20): what was tested, how detection
# works, and the explicit limits (no remediation, test coverage not legal
# certification).
_SCOPE_METHODOLOGY: tuple[str, ...] = (
    "Sectum AI provisions synthetic tenants seeded with cryptographic canary "
    "markers, recorded in a hashed ground-truth manifest. Probes run from each "
    "tenant's session against the configured surfaces; this pack attests the "
    "isolation of those surfaces under the run's scenario.",
    "Each observation passes a layered detector - exact canary match, then "
    "semantic similarity, then a calibrated judge. A confirmed finding is a "
    "marker owned by one tenant observed in another, traceable to the manifest, "
    "so confirmed findings carry no false positives; a candidate that cannot be "
    "tied to a manifest marker is recorded as unverified rather than confirmed.",
    "Scope is limited to the probes and surfaces exercised in this run, against "
    "the test condition fixed by the manifest hash below. Sectum verifies and "
    "attests; it does not remediate - findings carry remediation pointers, not "
    "changes - and this pack asserts test coverage, not legal certification.",
)

# The verification instruction rendered by both PDF engines. The cryptographic
# anchor is the whole-pack attested digest, NOT the run digest (ADR-0016): the
# timestamp token attests a hash over the run record, the manifest hash, the
# control mappings, the PDF reference, and the transparency-log flag. The run
# digest shown above is only a run identifier, so the instruction must not tell
# the reader to check it against the token (mirrors docs/evidence-chain.md).
_VERIFICATION_INSTRUCTION: str = (
    "Verify this pack independently by running 'sectum verify' on it. That "
    "recomputes the whole-pack attested digest - over the run record, the "
    "manifest hash, the control mappings, and the PDF reference - and checks it "
    "against the timestamp token (and the Rekor inclusion proof when present). "
    "The run digest above is the run's identifier, not the value checked against "
    "the token; any edit to the attested content changes the attested digest and "
    "fails verification."
)


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


def _evidence_line(finding: Finding) -> str | None:
    """Return the escaped italic ``<i>Evidence: "..."</i>`` line for a finding.

    The engineering spec, section 6.4: the detector pipeline captures the span
    of observed text that proves the leak (the canary substring, the semantic
    candidate, or the judge's evidence_span). Showing it in the auditor pack
    IS the proof. Returns ``None`` when the finding carries no evidence span
    (the default), so no line is rendered.
    """
    if not finding.evidence_span:
        return None
    return f'<i>Evidence: "{escape(finding.evidence_span)}"</i>'


def _remediation_line(finding: Finding) -> str | None:
    """Return the escaped italic ``<i>Remediation: ...</i>`` line for a finding.

    Returns ``None`` when the finding carries no remediation pointer (the
    default), so no line is rendered.
    """
    if not finding.remediation_pointer:
        return None
    return f"<i>Remediation: {escape(finding.remediation_pointer)}</i>"


def _finding_lines(findings: tuple[Finding, ...]) -> list[str]:
    """Return escaped finding lines, or a single 'none' line for an empty run.

    Each finding contributes a summary line - ending with its mapped control IDs
    (OWASP / ATLAS / NIST) when it carries any - then, when present, an
    italic evidence-span line (the proof) and an italic remediation line (the
    pointer). The order is proof, then pointer, mirroring how an auditor reads
    each finding.
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
        evidence = _evidence_line(finding)
        if evidence:
            lines.append(evidence)
        remediation = _remediation_line(finding)
        if remediation:
            lines.append(remediation)
    return lines


def _control_lines(mappings: tuple[ControlMapping, ...]) -> list[str]:
    """Return one escaped line per compliance control mapping."""
    return [
        f"<b>{escape(mapping.framework)}</b> "
        f"({escape(', '.join(mapping.control_ids))}): {escape(mapping.assertion)}"
        for mapping in mappings
    ]


def _render_reportlab(pack: EvidencePack, output: Path) -> None:
    """Render an ``EvidencePack`` to an auditor-facing PDF via reportlab."""
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

    flow += [Spacer(1, 12), Paragraph("Scope and methodology", heading)]
    flow += [Paragraph(escape(text), body) for text in _SCOPE_METHODOLOGY]

    flow += [Spacer(1, 12), Paragraph("Findings", heading)]
    flow += [Paragraph(line, body) for line in _finding_lines(run.findings)]

    flow += [Spacer(1, 12), Paragraph("Compliance control coverage", heading)]
    flow += [Paragraph(line, body) for line in _control_lines(pack.control_mappings)]
    flow.append(Paragraph(f"<i>{escape(COVERAGE_DISCLAIMER)}</i>", body))

    flow += [Spacer(1, 12), Paragraph("Integrity and independent verification", heading)]
    integrity = (
        ("Run digest (SHA-256, run identifier)", run_digest(run)),
        ("Manifest hash", pack.manifest_hash),
        ("Timestamp token", pack.tsa_token or "none"),
    )
    flow += [
        Paragraph(f"<b>{escape(label)}:</b> {escape(value)}", body) for label, value in integrity
    ]
    flow.append(Paragraph(escape(_VERIFICATION_INSTRUCTION), body))

    document = SimpleDocTemplate(str(output), pagesize=LETTER, title="Sectum AI Evidence Pack")
    document.build(flow)


def render_audit_pack(
    pack: EvidencePack, output: Path, *, engine: PdfEngine = PdfEngine.REPORTLAB
) -> None:
    """Render an ``EvidencePack`` to an auditor-facing PDF at ``output``.

    ``engine`` selects the renderer (the engineering spec, section 21). The
    default ``reportlab`` is pure Python and always available; ``weasyprint`` is
    the HTML/CSS-templated alternative and needs the ``weasyprint`` extra - it
    raises :class:`~sectum.spec.EvidenceError` with an install hint when the
    extra is absent. Both engines render the same content.
    """
    if engine is PdfEngine.WEASYPRINT:
        # Imported lazily so the base install never pulls in weasyprint.
        from sectum.evidence.pdf_weasyprint import render_weasyprint

        render_weasyprint(pack, output)
        return
    _render_reportlab(pack, output)
