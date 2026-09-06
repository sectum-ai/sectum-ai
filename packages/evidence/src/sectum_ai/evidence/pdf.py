"""Audit-pack renderer: an EvidencePack rendered to an auditor-facing PDF.

The engineering spec, sections 8.3 and 18. v1 uses reportlab (pure Python, no
system libraries). ADR-0002 keeps the renderer theme-pluggable; a richer,
HTML-templated theme is a later refinement.
"""

import io
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from sectum_ai.evidence.chain import run_digest
from sectum_ai.evidence.controls import COVERAGE_DISCLAIMER
from sectum_ai.evidence.labels import backing_surface, leak_label
from sectum_ai.spec import (
    ControlMapping,
    CoverageVerdict,
    EvidencePack,
    Finding,
    FindingStatus,
    RunResult,
    SurfaceProvenance,
    rate_from_counts,
    sha256_hex,
    wilson_interval,
)

# Canonical erasure-surface order for the coverage matrix, kept here (rather than
# importing from sectum_ai.probes) because the evidence package sits below probes
# in the acyclic package graph (ADR-0004) and must not depend on it. It mirrors
# ``sectum_ai.probes.ERASURE_SURFACES``; the erasure run writes a verdict for each
# of these into ``RunMetrics.erasure_coverage``.
_ERASURE_SURFACE_ORDER: tuple[str, ...] = (
    "vector_db",
    "tracing",
    "agent_memory",
    "semantic_cache",
    "model_adapter",
    "search_index",
    "eval_set",
    "backup",
)

# A short, DPO-facing gloss for each coverage verdict rendered in the matrix.
_COVERAGE_VERDICT_GLOSS: dict[str, str] = {
    CoverageVerdict.ERASED.value: (
        "verified clean - no marker retrievable through the tenant's own read path after erasure"
    ),
    CoverageVerdict.RESIDUAL.value: "erasure failed - a marker survived",
    CoverageVerdict.ATTESTABLE_WITH_CAVEAT.value: (
        "no per-tenant erasure API - data presumed retained"
    ),
    CoverageVerdict.NOT_COVERED.value: "not verified by this attestation",
}

# The standing caveat for the coverage matrix: an honest attestation states what
# it did NOT verify, so a NOT_COVERED surface is never read as erased.
_COVERAGE_CAVEAT = (
    "Coverage states what this attestation verified, surface by surface. A "
    "NOT_COVERED surface was out of scope, had no configured adapter, showed "
    "no pre-erasure baseline, or was scanned without establishing the markers' "
    "absence (the backend returned a full page of results without them, which a "
    "marker still stored but ranked below the page produces too) - it is "
    "explicitly not evidence of erasure and must "
    "not be read as erased. ERASED is measured through the erased tenant's own read "
    "path: a backend that retains the data while revoking that path is "
    "indistinguishable from one that purged it, from outside. ATTESTABLE WITH "
    "CAVEAT means the backend exposes no "
    "per-tenant erasure API, so the data is presumed retained until it ages out "
    "of the backend's retention window (a backend limitation, not a flow failure)."
)


def provenance_statement(run: RunResult) -> str:
    """The audit pack's first scope sentence: which systems these findings are about.

    An auditor reads this document to learn what was tested. Sectum falls back to
    an in-memory fake for every adapter family it cannot reach, and before this
    the pack rendered a run against eight of them identically to a production
    assessment - the words *synthetic*, *live*, and *adapter* appeared nowhere in
    it. Stated first, because every sentence after it is conditional on it.

    Shared by both PDF engines (ReportLab and WeasyPrint) so the two cannot
    disagree about the one paragraph that fixes the document's subject.
    """
    provenance = run.surface_provenance
    if not provenance:
        return (
            "Surface provenance: not recorded. This run predates Sectum's provenance "
            "block, so whether it exercised live backends or the built-in synthetic "
            "stores cannot be established from this pack."
        )
    live = sorted(s for s, p in provenance.items() if p == SurfaceProvenance.LIVE.value)
    synthetic = sorted(s for s, p in provenance.items() if p != SurfaceProvenance.LIVE.value)
    if not synthetic:
        return (
            "Surface provenance: every surface exercised by this run was a live, "
            f"configured backend ({', '.join(live)}). These findings describe those "
            "systems."
        )
    if not live:
        return (
            "Surface provenance: NO live backend was configured. Every surface in this "
            f"run ({', '.join(synthetic)}) was Sectum's built-in synthetic store, so "
            "the findings, metrics, and any clean result below describe that synthetic "
            "stack and NOT a production system. This pack is a demonstration, not an "
            "attestation."
        )
    return (
        f"Surface provenance: {len(live)} of {len(provenance)} surfaces were live, "
        f"configured backends ({', '.join(live)}). The remaining surfaces "
        f"({', '.join(synthetic)}) were Sectum's built-in synthetic stores; results "
        "attributed to them describe that fake and not a production system."
    )


def confirmed_by_kind(run: RunResult) -> str:
    """``"16 (residual-data 16)"``: confirmed findings, and what each is.

    The summary row read "Confirmed cross-tenant findings: 16" for an erasure
    attestation whose sixteen findings were all the target tenant's own residual
    markers - a DPO-facing document asserting a breach the run never saw.
    """
    confirmed = [f for f in run.findings if f.status is FindingStatus.CONFIRMED]
    counts = Counter(
        leak_label(f).removesuffix(" finding").removesuffix(" leak") for f in confirmed
    )
    if not confirmed:
        return "0"
    parts = ", ".join(f"{kind} {count}" for kind, count in sorted(counts.items()))
    # How many describe the operator's systems: an auditor read "226 confirmed
    # cross-tenant findings" beside asserted controls while the same record's
    # OSCAL said none was confirmed on a live surface.
    live = sum(
        1
        for f in confirmed
        if run.surface_provenance.get(backing_surface(f)) == SurfaceProvenance.LIVE.value
    )
    # Always, including - especially - when the answer is zero: gating it on the
    # run having a live surface dropped it from the one pack where it is the whole
    # point. Three-valued, like every label beside it: a run that records no
    # provenance at all cannot be said to have zero live-surface findings, and
    # saying so contradicted the scope paragraph below it in the same document.
    parts += (
        f"; on live surfaces {live}"
        if run.surface_provenance
        else "; live-surface attribution not recorded"
    )
    return f"{len(confirmed)} ({parts})"


def probes_exercised(run: RunResult) -> str:
    """The probe ids this run records, for the summary block of both PDF engines.

    "Scope is limited to the probes ... exercised in this run" is only checkable
    when the run names them: a one-probe pack and a twelve-probe pack rendered
    identically apart from the digest.
    """
    if not run.probe_versions:
        return "none recorded"
    ids = sorted(run.probe_versions)
    text = f"{len(ids)}: {', '.join(ids)}"
    dropped = sorted(p for p, n in run.metrics.user_steps_dropped.items() if n)
    if dropped:
        text += f"; user-level steps not run (tenant-level steps only) for: {', '.join(dropped)}"
    return text


def _coverage_rows(run: RunResult) -> list[tuple[str, str]]:
    """Return ``(surface, verdict)`` coverage rows in canonical order, or ``[]``.

    Reads ``RunResult.metrics.erasure_coverage`` (written only by a Class 11
    erasure run). Surfaces are ordered by :data:`_ERASURE_SURFACE_ORDER`; any
    extra surface key (forward-compatibility) is appended in sorted order so the
    matrix is total and deterministic. Returns ``[]`` for a non-erasure run, so
    the section is omitted entirely.
    """
    coverage = run.metrics.erasure_coverage
    if not coverage:
        return []
    ordered = [s for s in _ERASURE_SURFACE_ORDER if s in coverage]
    extra = sorted(s for s in coverage if s not in _ERASURE_SURFACE_ORDER)
    return [(surface, coverage[surface]) for surface in (*ordered, *extra)]


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
    "semantic similarity, then a calibrated judge. Confirmation requires the "
    "observed content to trace back to a specific marker in the ground-truth "
    "manifest, so a candidate that cannot be tied to a manifest marker is "
    "recorded as unverified rather than confirmed. An exact canary match is "
    "decided by the observation itself; a semantic match also depends on the "
    "configured judge. Confirmed findings are therefore manifest-grounded - "
    "they are not asserted to be free of error, and this pack does not rate "
    "their exploitability.",
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
    "Verify this pack independently by running 'sectum-ai verify' on it. That "
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
        owasp = f"OWASP {finding.owasp_llm}"
        # The spec §18 maps a primary OWASP class plus optional secondary ones
        # ("LLM08:2025 primary; LLM02/LLM06 secondary"). evidence.json already
        # carries them; render them in the audit pack too, rather than dropping
        # the secondary classes silently.
        if finding.owasp_secondary:
            owasp += f" (secondary: {', '.join(finding.owasp_secondary)})"
        parts.append(owasp)
    elif finding.owasp_secondary:
        parts.append(f"OWASP secondary: {', '.join(finding.owasp_secondary)}")
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


def synthetic_prefix(run: RunResult, finding: Finding) -> str:
    """``"[synthetic surface] "`` when this finding describes a built-in fake.

    Keyed on an explicit LIVE, like every sibling that answers this question.
    SARIF floors such a finding's severity and OSCAL prefixes its observation;
    both PDF engines rendered one identically to a live CRITICAL - in the one
    document an auditor actually reads.
    """
    recorded = run.surface_provenance.get(backing_surface(finding))
    if recorded == SurfaceProvenance.LIVE.value:
        return ""
    if recorded is None:
        return "[surface provenance not recorded - not evidence of a live backend] "
    return "[synthetic surface - Sectum's built-in fake, not your stack] "


def _finding_lines(findings: tuple[Finding, ...], run: RunResult | None = None) -> list[str]:
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
        marker = escape(synthetic_prefix(run, finding)) if run is not None else ""
        line = (
            f"{marker}<b>{escape(finding.severity.value)}</b> - {escape(finding.probe_id)} "
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


def _retrieval_pivot_summary(run: RunResult) -> str | None:
    """Render the Retrieval-Pivot Rate row for the summary, or ``None`` if absent.

    The flagship Class-2 metric is a binomial proportion, so it is presented with
    its 95% Wilson confidence interval and sample size - for example
    ``95.4% (95% CI 92.1-97.3%, n=350)`` - so an auditor reads the rate's
    precision, not a bare point estimate (the spec's "avoid over-claiming").
    Returns ``None`` for a run with no Class-2 steps (the rate is ``None``), so the
    row is omitted rather than shown empty.

    Args:
        run: The run result whose metrics carry the rate, its counts, and the
            confidence interval.

    Returns:
        The formatted rate string, or ``None`` when the run recorded no rate.
    """
    metrics = run.metrics
    # Recomputed from the record's binomial COUNTS, never relayed from the rate and
    # interval the record asserts about itself - the rule `score._headline` already
    # follows, and for the same reason: the counts are the evidence, the rate and
    # interval are bookkeeping. Relaying them let a record whose counts said 334 of
    # 350 print `2.0% (95% CI 1.9%-2.1%, n=350)` into the auditor's signed PDF,
    # while `score` read the same record as 95.4%. Refusing to invent an interval
    # while faithfully relaying a fabricated one reads identically to the auditor.
    rate = rate_from_counts(
        metrics.retrieval_pivot_k, metrics.retrieval_pivot_n, metrics.retrieval_pivot_rate
    )
    # The record contradicts its own counts, so there is nothing here to state.
    if rate is None:
        return None
    if metrics.retrieval_pivot_n > 0:
        low, high = wilson_interval(metrics.retrieval_pivot_k, metrics.retrieval_pivot_n)
        return f"{rate:.1%} (95% CI {low:.1%}-{high:.1%}, n={metrics.retrieval_pivot_n})"
    if metrics.retrieval_pivot_rate is None:
        return None
    # No counts, so the rate is all the record has, and any interval it asserts is
    # uncheckable - there is no sample size to compute one from. Shown bare.
    return f"{metrics.retrieval_pivot_rate:.1%}"


def _render_reportlab(pack: EvidencePack) -> bytes:
    """Render an ``EvidencePack`` to auditor-facing PDF bytes via reportlab.

    Renders only digest-stable content (run digest, manifest hash, control
    mappings, findings) - never the post-sign timestamp token - so the bytes are
    a pure function of the pack's bound content and re-hash deterministically for
    the ``pdf_ref`` binding (ADR-0016).
    """
    styles = getSampleStyleSheet()
    heading = styles["Heading2"]
    body = styles["BodyText"]
    run = pack.run_result

    flow: list[Any] = [
        Paragraph("Sectum AI - Verification Evidence Pack", styles["Title"]),
        Paragraph(f"Run {escape(run.run_id)}", body),
        Spacer(1, 16),
        Paragraph("Verification summary", heading),
    ]
    summary: list[tuple[str, str]] = [
        ("Run started", run.started_at.isoformat()),
        ("Run finished", run.finished_at.isoformat()),
        ("Probes exercised", probes_exercised(run)),
        ("Findings recorded", str(len(run.findings))),
        ("Confirmed findings", confirmed_by_kind(run)),
    ]
    rpr_line = _retrieval_pivot_summary(run)
    if rpr_line is not None:
        summary.append(("Retrieval-Pivot Rate", rpr_line))
    flow += [
        Paragraph(f"<b>{escape(label)}:</b> {escape(value)}", body) for label, value in summary
    ]

    flow += [Spacer(1, 12), Paragraph("Scope and methodology", heading)]
    flow += [Paragraph(escape(provenance_statement(run)), body)]
    flow += [Paragraph(escape(text), body) for text in _SCOPE_METHODOLOGY]

    flow += [Spacer(1, 12), Paragraph("Findings", heading)]
    flow += [Paragraph(line, body) for line in _finding_lines(run.findings, run)]

    coverage_rows = _coverage_rows(run)
    if coverage_rows:
        flow += [Spacer(1, 12), Paragraph("Coverage &amp; caveats", heading)]
        table_data: list[list[Any]] = [
            [
                Paragraph("<b>Surface</b>", body),
                Paragraph("<b>Verdict</b>", body),
                Paragraph("<b>Meaning</b>", body),
            ]
        ]
        for surface, verdict in coverage_rows:
            gloss = _COVERAGE_VERDICT_GLOSS.get(verdict, "")
            table_data.append(
                [
                    Paragraph(escape(surface), body),
                    Paragraph(f"<b>{escape(verdict)}</b>", body),
                    Paragraph(escape(gloss), body),
                ]
            )
        coverage_table = Table(table_data, colWidths=[110, 150, 230], hAlign="LEFT")
        coverage_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d8dee6")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        flow.append(coverage_table)
        flow.append(Paragraph(f"<i>{escape(_COVERAGE_CAVEAT)}</i>", body))

    flow += [Spacer(1, 12), Paragraph("Compliance control coverage", heading)]
    # Say it, rather than leaving a bare heading: the weasyprint engine does, and
    # an empty section reads as "not rendered" where the other reads "none".
    control_lines = _control_lines(pack.control_mappings) or ["No control mappings were recorded."]
    flow += [Paragraph(line, body) for line in control_lines]
    flow.append(Paragraph(f"<i>{escape(COVERAGE_DISCLAIMER)}</i>", body))

    flow += [Spacer(1, 12), Paragraph("Integrity and independent verification", heading)]
    integrity = (
        ("Run digest (SHA-256, run identifier)", run_digest(run)),
        ("Manifest hash", pack.manifest_hash),
    )
    flow += [
        Paragraph(f"<b>{escape(label)}:</b> {escape(value)}", body) for label, value in integrity
    ]
    flow.append(Paragraph(escape(_VERIFICATION_INSTRUCTION), body))

    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=LETTER, title="Sectum AI Evidence Pack")
    document.build(flow)
    return buffer.getvalue()


def render_audit_pack(
    pack: EvidencePack, output: Path, *, engine: PdfEngine = PdfEngine.REPORTLAB
) -> bytes:
    """Render an ``EvidencePack`` to an auditor-facing PDF at ``output``; return its bytes.

    ``engine`` selects the renderer (the engineering spec, section 21). The
    default ``reportlab`` is pure Python and always available; ``weasyprint`` is
    the HTML/CSS-templated alternative and needs the ``weasyprint`` extra - it
    raises :class:`~sectum_ai.spec.EvidenceError` with an install hint when the
    extra is absent. Both engines render the same (digest-stable) content. The
    returned bytes are exactly what was written to ``output``, so a caller can
    hash them for the ``pdf_ref`` binding.
    """
    if engine is PdfEngine.WEASYPRINT:
        # Imported lazily so the base install never pulls in weasyprint.
        from sectum_ai.evidence.pdf_weasyprint import render_weasyprint

        data = render_weasyprint(pack)
    else:
        data = _render_reportlab(pack)
    output.write_bytes(data)
    return data


def render_audit_pack_and_hash(
    run_result: RunResult,
    manifest_hash: str,
    control_mappings: tuple[ControlMapping, ...],
    output: Path,
    *,
    engine: PdfEngine = PdfEngine.REPORTLAB,
) -> str:
    """Render the audit pack to ``output`` and return the SHA-256 of its bytes.

    Breaks the bind cycle: the audit PDF must be hashed *before* the pack is
    signed (so ``pdf_ref`` can enter the attested digest), yet the renderer takes
    a pack. The PDF renders only digest-stable content (no post-sign timestamp
    token), so it is rendered here from a throwaway unsigned pack carrying just
    the run, manifest hash, and control mappings; the written file re-hashes to
    the returned digest, which the caller binds as ``pdf_ref``.
    """
    render_only = EvidencePack(
        run_result=run_result,
        manifest_hash=manifest_hash,
        tsa_token="",
        control_mappings=control_mappings,
    )
    return sha256_hex(render_audit_pack(render_only, output, engine=engine))
