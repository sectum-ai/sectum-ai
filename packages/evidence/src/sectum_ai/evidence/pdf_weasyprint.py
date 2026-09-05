"""Audit-pack renderer: an EvidencePack rendered to PDF via weasyprint (HTML/CSS).

The engineering spec, sections 8.3, 18, and 21. This is the optional,
HTML-templated alternative to the default reportlab renderer (``pdf.py``):
weasyprint gives an auditor-grade, CSS-styled layout (severity badges, page
footers, typographic tables) at the cost of system libraries (pango/cairo), so
it ships behind the ``weasyprint`` extra rather than as a base dependency.

The HTML is built by :func:`build_audit_html`, which is pure and has no
weasyprint dependency, so the template logic is fully unit-testable without the
system libraries. Only :func:`render_weasyprint` imports weasyprint, lazily, and
raises a clear :class:`EvidenceError` when it is not installed.

Both engines render the SAME content - the shared methodology narrative, control
formatting, and coverage disclaimer are imported from ``pdf.py`` - so an audit
pack asserts identical facts whichever engine produced it.
"""

from html import escape

from sectum_ai.evidence.chain import run_digest
from sectum_ai.evidence.controls import COVERAGE_DISCLAIMER
from sectum_ai.evidence.pdf import (
    _COVERAGE_CAVEAT,
    _COVERAGE_VERDICT_GLOSS,
    _SCOPE_METHODOLOGY,
    _VERIFICATION_INSTRUCTION,
    _coverage_rows,
    _finding_controls,
    probes_exercised,
    provenance_statement,
)
from sectum_ai.spec import EvidenceError, EvidencePack, Finding, FindingStatus

# Severity -> CSS accent colour for the finding badge. A muted, print-safe
# palette (no neon); unknown severities fall back to the neutral grey.
_SEVERITY_COLOURS: dict[str, str] = {
    "critical": "#8b1a1a",
    "high": "#b4531f",
    "medium": "#8a6d1b",
    "low": "#2f5d50",
    "info": "#3a4a5a",
}
_NEUTRAL = "#3a4a5a"

_CSS = """
@page {
  size: Letter;
  margin: 2.2cm 2cm 2.4cm 2cm;
  @bottom-center {
    content: "Sectum AI - Verification Evidence Pack";
    font: 8pt 'Helvetica', sans-serif;
    color: #888;
  }
  @bottom-right {
    content: "Page " counter(page) " of " counter(pages);
    font: 8pt 'Helvetica', sans-serif;
    color: #888;
  }
}
body {
  font-family: 'Helvetica', 'Arial', sans-serif;
  color: #1c1c1c; font-size: 10pt; line-height: 1.45;
}
h1 { font-size: 20pt; margin: 0 0 2pt 0; color: #14233a; }
h2 {
  font-size: 13pt; margin: 18pt 0 6pt 0; color: #14233a;
  border-bottom: 1px solid #d8dee6; padding-bottom: 3pt;
}
.run-id { color: #5a6675; font-size: 9pt; margin: 0 0 4pt 0; }
table.kv { border-collapse: collapse; width: 100%; margin: 4pt 0; }
table.kv td { padding: 3pt 6pt; vertical-align: top; border-bottom: 1px solid #eef1f5; }
table.kv td.label { font-weight: bold; width: 42%; color: #2d3a4a; }
td.mono, .mono { font-family: 'Courier New', monospace; font-size: 8.5pt; word-break: break-all; }
p.method { margin: 4pt 0; text-align: justify; }
.finding { margin: 8pt 0; padding: 7pt 9pt; border-left: 3px solid #ccc; background: #fafbfc; }
.finding .head { font-weight: bold; }
.badge { display: inline-block; color: #fff; font-size: 7.5pt; font-weight: bold;
         text-transform: uppercase; padding: 1pt 6pt; border-radius: 3px; margin-right: 6pt; }
.controls { color: #5a6675; font-size: 8.5pt; margin-top: 2pt; }
.evidence { font-style: italic; color: #333; margin-top: 3pt; }
.remediation { font-style: italic; color: #2f5d50; margin-top: 2pt; }
.none { color: #5a6675; font-style: italic; }
.control { margin: 4pt 0; }
.control .fw { font-weight: bold; }
.disclaimer { font-style: italic; color: #5a6675; font-size: 8.5pt; margin-top: 6pt; }
.verify { margin-top: 6pt; }
table.coverage { border-collapse: collapse; width: 100%; margin: 4pt 0; }
table.coverage th, table.coverage td {
  padding: 3pt 6pt; border: 0.5px solid #d8dee6; text-align: left; vertical-align: top;
}
table.coverage th { background: #eef1f5; color: #2d3a4a; }
table.coverage td.verdict { font-weight: bold; }
"""


def _kv_table(rows: tuple[tuple[str, str], ...], *, mono_values: bool = False) -> str:
    """Render label/value pairs as an escaped two-column table."""
    value_class = ' class="mono"' if mono_values else ""
    cells = "".join(
        f'<tr><td class="label">{escape(label)}</td><td{value_class}>{escape(value)}</td></tr>'
        for label, value in rows
    )
    return f'<table class="kv">{cells}</table>'


def _finding_html(finding: Finding) -> str:
    """Render one finding as an escaped, severity-accented HTML block."""
    severity = finding.severity.value
    colour = _SEVERITY_COLOURS.get(severity, _NEUTRAL)
    head = (
        f'<span class="badge" style="background:{colour}">{escape(severity)}</span>'
        f"{escape(finding.probe_id)} on {escape(finding.surface.value)}: "
        f"marker {escape(finding.marker_id or 'n/a')} ({escape(finding.status.value)})"
    )
    parts = [f'<div class="head">{head}</div>']
    controls = _finding_controls(finding)
    if controls:
        parts.append(f'<div class="controls">{escape(controls)}</div>')
    if finding.evidence_span:
        parts.append(f'<div class="evidence">Evidence: "{escape(finding.evidence_span)}"</div>')
    if finding.remediation_pointer:
        parts.append(
            f'<div class="remediation">Remediation: {escape(finding.remediation_pointer)}</div>'
        )
    return f'<div class="finding" style="border-left-color:{colour}">{"".join(parts)}</div>'


def _coverage_html(pack: EvidencePack) -> str:
    """Render the per-surface erasure coverage matrix as an escaped HTML table.

    Returns ``""`` for a non-erasure pack (no ``erasure_coverage`` metric), so
    the section is omitted there. Mirrors the reportlab engine's matrix so both
    engines surface the same NOT_COVERED rows to a DPO/auditor.
    """
    rows = _coverage_rows(pack.run_result)
    if not rows:
        return ""
    cells = "".join(
        f"<tr><td>{escape(surface)}</td>"
        f'<td class="verdict">{escape(verdict)}</td>'
        f"<td>{escape(_COVERAGE_VERDICT_GLOSS.get(verdict, ''))}</td></tr>"
        for surface, verdict in rows
    )
    table = (
        '<table class="coverage"><thead><tr><th>Surface</th><th>Verdict</th>'
        f"<th>Meaning</th></tr></thead><tbody>{cells}</tbody></table>"
    )
    return (
        "<h2>Coverage &amp; caveats</h2>"
        f"{table}"
        f'<p class="disclaimer">{escape(_COVERAGE_CAVEAT)}</p>'
    )


def build_audit_html(pack: EvidencePack) -> str:
    """Build the full auditor-facing HTML document for ``pack``.

    Pure and dependency-free (no weasyprint import), so the template is unit
    -testable without the system libraries. Mirrors the reportlab renderer's
    sections and reuses its shared content (methodology, control formatting,
    coverage disclaimer) so both engines assert the same facts.
    """
    run = pack.run_result
    confirmed = sum(1 for f in run.findings if f.status is FindingStatus.CONFIRMED)

    summary = (
        ("Run started", run.started_at.isoformat()),
        ("Run finished", run.finished_at.isoformat()),
        ("Probes exercised", probes_exercised(run)),
        ("Findings recorded", str(len(run.findings))),
        ("Confirmed cross-tenant findings", str(confirmed)),
    )
    integrity = (
        ("Run digest (SHA-256, run identifier)", run_digest(run)),
        ("Manifest hash", pack.manifest_hash),
    )

    # The provenance statement leads: every sentence after it is conditional on it.
    methodology = f'<p class="method">{escape(provenance_statement(run))}</p>' + "".join(
        f'<p class="method">{escape(text)}</p>' for text in _SCOPE_METHODOLOGY
    )

    if run.findings:
        findings_html = "".join(_finding_html(f) for f in run.findings)
    else:
        findings_html = '<p class="none">No findings were recorded for this run.</p>'

    if pack.control_mappings:
        controls_html = "".join(
            f'<div class="control"><span class="fw">{escape(m.framework)}</span> '
            f"({escape(', '.join(m.control_ids))}): {escape(m.assertion)}</div>"
            for m in pack.control_mappings
        )
    else:
        controls_html = '<p class="none">No control mappings were recorded.</p>'

    body = (
        "<h1>Sectum AI - Verification Evidence Pack</h1>"
        f'<p class="run-id">Run {escape(run.run_id)}</p>'
        "<h2>Verification summary</h2>"
        f"{_kv_table(summary)}"
        "<h2>Scope and methodology</h2>"
        f"{methodology}"
        "<h2>Findings</h2>"
        f"{findings_html}"
        f"{_coverage_html(pack)}"
        "<h2>Compliance control coverage</h2>"
        f"{controls_html}"
        f'<p class="disclaimer">{escape(COVERAGE_DISCLAIMER)}</p>'
        "<h2>Integrity and independent verification</h2>"
        f"{_kv_table(integrity, mono_values=True)}"
        f'<p class="verify">{escape(_VERIFICATION_INSTRUCTION)}</p>'
    )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Sectum AI Evidence Pack</title>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


def render_weasyprint(pack: EvidencePack) -> bytes:
    """Render ``pack`` to auditor-facing PDF bytes via weasyprint.

    Imports weasyprint lazily so the base install (reportlab only) never pulls
    it in. Raises :class:`EvidenceError` with an install hint when the
    ``weasyprint`` extra is not installed. Renders the same digest-stable content
    as the reportlab engine (no post-sign timestamp token).
    """
    try:
        from weasyprint import HTML
    except ImportError as error:  # pragma: no cover - exercised only without the extra
        raise EvidenceError(
            "the weasyprint PDF engine requires the 'weasyprint' extra: "
            "pip install 'sectum-ai[weasyprint]'"
        ) from error
    pdf: bytes = HTML(string=build_audit_html(pack)).write_pdf()
    return pdf
