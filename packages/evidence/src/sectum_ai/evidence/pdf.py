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
from sectum_ai.evidence.controls import (
    _ERASURE_PROBE_IDS,
    COVERAGE_DISCLAIMER,
    live_surfaces,
)
from sectum_ai.evidence.intoto import _is_external_timestamp_anchor
from sectum_ai.evidence.labels import backing_surface, leak_label, unaccounted_surfaces
from sectum_ai.spec import (
    ERASURE_SURFACES,
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

# The coverage matrix's row order, derived from the canonical set rather than
# transcribed. This was a third copy, kept here because `evidence` sits below
# `probes` in the acyclic package graph (ADR-0004) - which stopped being a reason
# once the set moved to `spec`, below both.
_ERASURE_SURFACE_ORDER: tuple[str, ...] = tuple(surface.value for surface in ERASURE_SURFACES)

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
    # The block is what the run ACCOUNTED for; the findings may rest on more. See
    # `labels.unaccounted_surfaces` for what shipped before this qualifier existed.
    unaccounted = unaccounted_surfaces(run)
    trailer = (
        ""
        if not unaccounted
        else (
            f" This run's findings also rest on {', '.join(unaccounted)}, which its "
            "provenance block never recorded: whether those were live backends or "
            "Sectum's built-in fakes cannot be established from this pack."
        )
    )
    if not synthetic:
        if unaccounted:
            return (
                "Surface provenance: every surface this run RECORDED was a live, "
                f"configured backend ({', '.join(live)}), and findings on those "
                f"surfaces describe those systems.{trailer}"
            )
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
            f"attestation.{trailer}"
        )
    return (
        f"Surface provenance: {len(live)} of {len(provenance)} surfaces were live, "
        f"configured backends ({', '.join(live)}). The remaining surfaces "
        f"({', '.join(synthetic)}) were Sectum's built-in synthetic stores; results "
        f"attributed to them describe that fake and not a production system.{trailer}"
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
    # "on live surfaces 0" reads as "we placed them, on a fake". An unaccounted
    # finding was not placed at all, and the two rendered byte-identically - the
    # same conflation `unaccounted_surfaces` exists to break one section above.
    unplaceable = sum(
        1 for finding in confirmed if backing_surface(finding) in unaccounted_surfaces(run)
    )
    if unplaceable:
        parts += (
            f"; {unplaceable} of them rest on a surface this run's provenance "
            "does not record and are placed on no stack at all"
        )
    return f"{len(confirmed)} ({parts})"


def probes_exercised(run: RunResult) -> str:
    """The probe ids this run records, for the summary block of both PDF engines.

    "Scope is limited to the probes ... exercised in this run" is only checkable
    when the run names them: a one-probe pack and a twelve-probe pack rendered
    identically apart from the digest.
    """
    # A finding is itself proof its probe executed - the reasoning
    # `score._confirmed_probe_ids`, `baseline._exercised_probes` and
    # `controls._run_supports` all apply. This renderer did not, so the auditor
    # PDF read "Probes exercised: none recorded" in the same signed pack that
    # grades that probe's class FAIL.
    exercised = set(run.probe_versions) | {finding.probe_id for finding in run.findings}
    if not exercised:
        return "none recorded"
    ids = sorted(exercised)
    text = f"{len(ids)}: {', '.join(ids)}"
    dropped = sorted(p for p, n in run.metrics.user_steps_dropped.items() if n)
    if dropped:
        text += f"; user-level steps not run (tenant-level steps only) for: {', '.join(dropped)}"
    # The sibling disclosure. A probe some of whose plants the backend swallowed
    # still ran and still graded, on less setup than it planned - and the pack said
    # so nowhere, so a class graded on half its setup read exactly like one graded
    # on all of it.
    unconfirmed = sorted(p for p, n in run.metrics.unconfirmed_plants.items() if n)
    if unconfirmed:
        text += (
            "; planted data could not be read back (the backend acknowledged the write "
            f"and did not serve it) for: {', '.join(unconfirmed)}"
        )
    return text


def _coverage_rows(run: RunResult) -> list[tuple[str, str]]:
    """Return ``(surface, verdict)`` coverage rows in canonical order, or ``[]``.

    Reads ``RunResult.metrics.erasure_coverage`` (written only by a Class 11
    erasure run). Surfaces are ordered by :data:`_ERASURE_SURFACE_ORDER`; any
    extra surface key (forward-compatibility) is appended in sorted order so the
    matrix is total and deterministic. Returns ``[]`` for a non-erasure run, so
    the section is omitted entirely.

    A LIVE erasure surface the block never mentions is rendered NOT_COVERED rather
    than omitted. Both siblings already default it that way - ``oscal`` and
    ``controls._erasure_assertion``, whose comment records the same defect: "it was
    neither verified nor unestablished - it simply vanished." This matrix is the
    DPO-facing one, promising coverage "surface by surface", and it was the copy
    that still vanished it: the row disappeared while the control assertion two
    pages on said absence could not be established there.
    """
    coverage = run.metrics.erasure_coverage
    if not coverage:
        return []
    rows = set(coverage) | (live_surfaces(run) & frozenset(_ERASURE_SURFACE_ORDER))
    ordered = [s for s in _ERASURE_SURFACE_ORDER if s in rows]
    extra = sorted(s for s in rows if s not in _ERASURE_SURFACE_ORDER)
    return [
        (surface, coverage.get(surface, CoverageVerdict.NOT_COVERED.value))
        for surface in (*ordered, *extra)
    ]


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
_ERASURE_METHODOLOGY: str = (
    "Sectum AI provisions synthetic tenants seeded with cryptographic canary "
    "markers, recorded in a hashed ground-truth manifest. This pack attests "
    "whether those markers are still retrievable after erasure on the surfaces "
    "scanned; it makes no claim about tenant isolation, which no probe in this "
    "run measured."
)

# The same sentence with the attestation claim removed, for the erasure branch.
# `scope_methodology` gained the provenance narrowing on its isolation arms only,
# so an all-synthetic erasure pack still read "This pack ATTESTS whether those
# markers are still retrievable" directly beneath `provenance_statement`'s "This
# pack is a demonstration, not an attestation." - present in both shipped erasure
# samples.
_ERASURE_SYNTHETIC: str = (
    "Sectum AI provisions synthetic tenants seeded with cryptographic canary "
    "markers, recorded in a hashed ground-truth manifest. This pack records "
    "whether those markers were still retrievable after erasure on the surfaces "
    "scanned, on the stack named above, which is not a production system; it "
    "makes no claim about tenant isolation, which no probe in this run measured."
)

_DETECTOR_TAIL = (
    "Confirmation requires the observed content to trace back to a specific "
    "marker in the ground-truth manifest, so a candidate that cannot be tied to "
    "a manifest marker is recorded as unverified rather than confirmed. "
    "Confirmed findings are therefore manifest-grounded - they are not asserted "
    "to be free of error, and this pack does not rate their exploitability."
)

# Which tiers ran is a property of the RUN, not of the product. Stated
# unconditionally, this paragraph promised an auditor "semantic similarity, then
# a calibrated judge" over three kinds of run that had neither: an `erasure`
# attestation, whose probe matches by exact substring and invokes no provider at
# all; a default `probe` run, since `sectum-ai init` scaffolds `embedder.kind:
# fake` and `judge.kind: fake` - an offline hashing vector its own docstring
# calls "not semantically meaningful beyond lexical overlap", and a token-order
# string matcher; and a run whose threshold gated the semantic tier shut. The
# record now carries `detection`, so the sentence can be true.
_DETECTOR_LAYERED = (
    "Each observation passes a layered detector - exact canary match, then "
    "semantic similarity against the configured embedding model, then the "
    "configured judge. An exact canary match is decided by the observation "
    "itself; a semantic match also depends on that judge. "
) + _DETECTOR_TAIL
# Composed per TIER, because the two are configured independently and
# `offline_only` collapsed them with `and`: one real provider flipped the whole
# paragraph to the fully-layered claim, so a run with a real embedder and the
# default `judge.kind: fake` told an auditor "then the configured judge" over a
# token-order string matcher. That is a documented setup - `EmbedderConfig`'s own
# `base_url` markets pointing the embedder at a local Ollama, while a judge needs
# a chat model.
_TIER_EMBEDDER = {
    True: (
        "an OFFLINE similarity stage - this run configured no embedding model, so "
        "the second tier was Sectum's hashing vector, which measures lexical "
        "overlap rather than meaning"
    ),
    False: "semantic similarity against the configured embedding model",
}
_TIER_JUDGE = {
    True: (
        "an OFFLINE adjudication stage - this run configured no judge, so the third "
        "tier was Sectum's token-order string matcher, which is not a calibrated "
        "judge"
    ),
    False: "the configured judge",
}


def _detector_tiers(embedder_offline: bool, judge_offline: bool) -> str:
    """The layered-detector sentence, naming each tier as it actually ran."""
    tail = (
        " A paraphrase an offline stage cannot see is not reported as absent - it "
        "is not reported at all; configure `detection.embedder` and "
        "`detection.judge` to exercise the semantic tiers. "
        if embedder_offline or judge_offline
        else " An exact canary match is decided by the observation itself; a "
        "semantic match also depends on that judge. "
    )
    return (
        "Each observation passes a layered detector - exact canary match, then "
        f"{_TIER_EMBEDDER[embedder_offline]}, then {_TIER_JUDGE[judge_offline]}."
        f"{tail}"
    ) + _DETECTOR_TAIL


_DETECTOR_OFFLINE = (
    "Each observation passes a layered detector - exact canary match, then an "
    "OFFLINE similarity and adjudication stage. This run configured no embedding "
    "model and no judge, so the second and third tiers were Sectum's built-in "
    "offline stubs: a hashing vector that measures lexical overlap rather than "
    "meaning, and a token-order string matcher. They are not an embedding model "
    "and not a calibrated judge, and a paraphrase they cannot see is not "
    "reported as absent - it is not reported at all. Configure "
    "`detection.embedder` and `detection.judge` to exercise the semantic tiers. "
) + _DETECTOR_TAIL
_DETECTOR_EXACT = (
    "Each observation is matched against the ground-truth manifest by exact "
    "content. This run invoked no embedding model and no judge - the erasure "
    "workflow reads each surface and checks the subject's own markers directly - "
    "so no semantic or adjudicated tier contributed to any verdict here. "
) + _DETECTOR_TAIL

# The same sentence, minus the attestation claim. `provenance_statement` already
# ends "This pack is a demonstration, not an attestation." for an all-synthetic
# run, and this paragraph is rendered directly beneath it - so the two read, back
# to back, "not an attestation" and "this pack attests the isolation of those
# surfaces". `scope_methodology` conditioned this paragraph on erasure-vs-isolation
# and never on provenance, and the renderer's own doctrine ("a run-level paragraph
# does not reach a reader tabulating rows") cuts both ways: a reader who lands on
# Scope and methodology carries away the second sentence.
_SCOPE_SYNTHETIC: str = (
    "Sectum AI provisions synthetic tenants seeded with cryptographic canary "
    "markers, recorded in a hashed ground-truth manifest. Probes run from each "
    "tenant's session against the configured surfaces; this pack records what "
    "those probes observed on the stack named above, which is not a production "
    "system."
)

_SCOPE_METHODOLOGY: tuple[str, ...] = (
    "Sectum AI provisions synthetic tenants seeded with cryptographic canary "
    "markers, recorded in a hashed ground-truth manifest. Probes run from each "
    "tenant's session against the configured surfaces; this pack attests the "
    "isolation of those surfaces under the run's scenario.",
    _DETECTOR_TAIL,
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
    "manifest hash, the control mappings, the PDF reference, and the two anchor "
    "flags - and checks it "
    "against the timestamp token (and the Rekor inclusion proof when present). "
    "The run digest above is the run's identifier, not the value checked against "
    "the token; any edit to the attested content changes the attested digest and "
    "fails verification."
)

# Whether THIS pack is independently anchored is the premise of the sentence
# above, and the PDF said nothing about it. Without an external anchor the
# timestamp is `LocalTimestamper`'s token, which its own docstring calls
# "reproducible by anyone over any digest ... an attacker who edits a pack can
# simply re-stamp it" - so "any edit fails verification" was an over-claim, and
# the reader following the instruction on a default pack gets
# `[FAIL] independent-anchor` and `VERIFICATION FAILED` at exit 4 over a pack
# nobody touched. Every other renderer makes the distinction - `_echo_verdict`,
# the `independent-anchor` check, the in-toto `anchors` block, and PACK-README
# inside the same deliverable - and the audit PDF, the artifact the auditor
# actually reads, was the one that did not.
_ANCHOR_NONE: str = (
    "Independent anchor: NONE. This pack's timestamp is Sectum's local "
    "development token - reproducible by anyone over any digest, so it binds the "
    "content but is not independent evidence of when, or by whom, it was "
    "produced. Verification of this pack is integrity-only and 'sectum-ai verify' "
    "requires --allow-unanchored to complete; without it the run above exits 4 on "
    "[FAIL] independent-anchor, which is a statement about the anchor and not "
    "about the content. Re-create the pack with 'report --tsa' and/or '--rekor' "
    "for a pack whose tamper evidence stands on its own."
)
_ANCHOR_PRESENT: str = (
    "Independent anchor: {anchors}. The attested digest is bound to an anchor "
    "outside this pack, so an edit cannot be covered up by re-stamping it."
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


def coverage_gloss(run: RunResult, surface: str, verdict: str) -> str:
    """The coverage row's plain-English verdict, scoped to the surface it is about.

    `verified clean - no marker retrievable...` over a surface that was Sectum's
    own in-memory fake is the same over-claim `synthetic_prefix` exists to stop
    one section above, and the coverage matrix was the only per-row artifact
    without it: SARIF prefixes and floors, OSCAL prefixes and tags the
    provenance, the finding rows prefix. A run-level paragraph does not reach a
    reader tabulating rows - OSCAL's own comment says so.

    NOT_COVERED needs no prefix: it already asserts nothing about the surface.
    """
    gloss = _COVERAGE_VERDICT_GLOSS.get(verdict, "")
    if not gloss or verdict == CoverageVerdict.NOT_COVERED.value:
        return gloss
    recorded = run.surface_provenance.get(surface)
    if recorded == SurfaceProvenance.LIVE.value:
        return gloss
    if recorded is None:
        return f"[surface provenance not recorded - not evidence of a live backend] {gloss}"
    return f"[synthetic surface - Sectum's built-in fake, not your stack] {gloss}"


def scope_methodology(run: RunResult) -> tuple[str, ...]:
    """The methodology paragraphs, with the isolation claim only where it is earned.

    The first paragraph asserted "this pack attests the isolation of those
    surfaces" on every pack - including an erasure attestation whose only probe
    was `gdpr-erasure-verification`. That is verbatim the claim
    `controls._run_supports` exists to refuse ("a run in which only
    gdpr-erasure-verification executed used to satisfy this test and ship SOC 2 /
    ISO / EU AI Act mappings ... in the artifact built for auditors"): the mapping
    table was fixed and the prose one section above it was not, so both shipped
    erasure samples carry it.
    """
    exercised = set(run.probe_versions) | {finding.probe_id for finding in run.findings}
    erasure_only = bool(exercised) and not exercised - _ERASURE_PROBE_IDS
    if erasure_only:
        # No detector ran at all, whatever the config says: the erasure workflow
        # never constructs one.
        detector = _DETECTOR_EXACT
    elif run.detection is None:
        # A record from before `detection` was recorded. Say what is known - the
        # first tier always runs - rather than assert the two that may not have.
        detector = _DETECTOR_TAIL
    else:
        detector = _detector_tiers(
            run.detection.embedder_kind == "fake", run.detection.judge_kind == "fake"
        )
    if erasure_only:
        head = _ERASURE_METHODOLOGY if live_surfaces(run) else _ERASURE_SYNTHETIC
    elif live_surfaces(run):
        head = _SCOPE_METHODOLOGY[0]
    else:
        # Nothing ran live, so there is no isolation of "those surfaces" to attest
        # - which is exactly what the paragraph above this one already says.
        head = _SCOPE_SYNTHETIC
    return (head, detector, *_SCOPE_METHODOLOGY[2:])


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
    # The record contradicts its own counts. There IS something to state: `score`
    # refuses to grade such a record outright, while returning None here omitted the
    # row - byte-identical to a run that took no Class-2 step at all, so the
    # auditor's PDF hid a corrupt record behind the same silence as an honest one.
    if metrics.retrieval_pivot_k > metrics.retrieval_pivot_n:
        return (
            f"not stated: this record reports {metrics.retrieval_pivot_k} of "
            f"{metrics.retrieval_pivot_n} retrieval pivots, which is impossible, so "
            "neither its counts nor the rate it asserts can be believed"
        )
    if rate is None:
        return None
    if metrics.retrieval_pivot_n > 0:
        low, high = wilson_interval(metrics.retrieval_pivot_k, metrics.retrieval_pivot_n)
        return f"{rate:.1%} (95% CI {low:.1%}-{high:.1%}, n={metrics.retrieval_pivot_n})"
    if metrics.retrieval_pivot_rate is None:
        return None
    # No counts, so the rate is all the record has and any interval it asserts is
    # uncheckable - there is no sample size to compute one from. Rendered bare it
    # was byte-identical to a measured rate beside its CI, which is the same
    # conflation the `k > n` branch above refuses: label it instead of hiding it,
    # and instead of presenting it as something it is not.
    return f"{metrics.retrieval_pivot_rate:.1%} (asserted by the record; no sample size recorded)"


def _render_reportlab(pack: EvidencePack, anchor: str) -> bytes:
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
    flow += [Paragraph(escape(text), body) for text in scope_methodology(run)]

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
            gloss = coverage_gloss(run, surface, verdict)
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
    flow.append(Paragraph(f"<b>{escape(anchor)}</b>", body))

    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=LETTER, title="Sectum AI Evidence Pack")
    document.build(flow)
    return buffer.getvalue()


def anchor_statement(pack: EvidencePack, *, anchors: tuple[bool, bool] | None = None) -> str:
    """What the PDF says about this pack's independent anchor.

    Derived from the pack by default, so the sample-regeneration guard - which
    re-renders a committed PDF from its committed pack and compares bytes - keeps
    holding. `render_audit_pack_and_hash` overrides it with the INTENT, because
    the PDF is rendered before the token that would prove it exists: its
    throwaway pack carries `tsa_token=""`, so deriving there would print "no
    anchor" into the PDF of a `--tsa` run and then disagree with the pack that
    binds it.
    """
    timestamped, logged = (
        anchors
        if anchors is not None
        else (
            _is_external_timestamp_anchor(pack.tsa_token),
            bool(pack.rekor_proof and pack.rekor_proof.strip()),
        )
    )
    named = [
        name
        for name, present in (
            ("RFC 3161 timestamp", timestamped),
            ("Rekor transparency log", logged),
        )
        if present
    ]
    if not named:
        return _ANCHOR_NONE
    return _ANCHOR_PRESENT.format(anchors=" and ".join(named))


def render_audit_pack(
    pack: EvidencePack,
    output: Path,
    *,
    engine: PdfEngine = PdfEngine.REPORTLAB,
    anchors: tuple[bool, bool] | None = None,
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
    anchor = anchor_statement(pack, anchors=anchors)
    if engine is PdfEngine.WEASYPRINT:
        # Imported lazily so the base install never pulls in weasyprint.
        from sectum_ai.evidence.pdf_weasyprint import render_weasyprint

        data = render_weasyprint(pack, anchor)
    else:
        data = _render_reportlab(pack, anchor)
    output.write_bytes(data)
    return data


def render_audit_pack_and_hash(
    run_result: RunResult,
    manifest_hash: str,
    control_mappings: tuple[ControlMapping, ...],
    output: Path,
    *,
    engine: PdfEngine = PdfEngine.REPORTLAB,
    anchors: tuple[bool, bool] = (False, False),
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
    return sha256_hex(render_audit_pack(render_only, output, engine=engine, anchors=anchors))
