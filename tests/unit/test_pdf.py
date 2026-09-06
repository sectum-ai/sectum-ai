"""Tests for the audit-pack PDF renderer."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sectum_ai.evidence import build_evidence_pack, control_mappings, render_audit_pack
from sectum_ai.evidence.pdf import (
    _COVERAGE_CAVEAT,
    _SCOPE_METHODOLOGY,
    _coverage_rows,
    _evidence_line,
    _finding_controls,
    _finding_lines,
    _remediation_line,
    _retrieval_pivot_summary,
)
from sectum_ai.evidence.pdf_weasyprint import build_audit_html
from sectum_ai.spec import (
    CoverageVerdict,
    EvidencePack,
    Finding,
    FindingStatus,
    GroundTruthManifest,
    RunMetrics,
    RunResult,
    Severity,
    Surface,
    canonical_hash,
)


def _run_result(manifest: GroundTruthManifest, *, with_finding: bool) -> RunResult:
    findings: tuple[Finding, ...] = ()
    if with_finding:
        findings = (
            Finding(
                finding_id="f-1",
                probe_id="rag-entity-bleed",
                severity=Severity.HIGH,
                confidence=0.9,
                status=FindingStatus.CONFIRMED,
                owner_tenant_id=UUID(int=0xB),
                observed_in_tenant_id=UUID(int=0xA),
                surface=Surface.VECTOR_DB,
                marker_id="marker-1",
            ),
        )
    moment = datetime(2026, 5, 18, tzinfo=UTC)
    return RunResult(
        run_id="run-1",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(manifest),
        started_at=moment,
        finished_at=moment,
        findings=findings,
        metrics=RunMetrics(),
    )


def _pack(*, with_finding: bool) -> EvidencePack:
    manifest = GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())
    return build_evidence_pack(
        _run_result(manifest, with_finding=with_finding),
        manifest,
        control_mappings=control_mappings(),
    )


def test_render_audit_pack_writes_a_pdf(tmp_path: Path) -> None:
    output = tmp_path / "audit-pack.pdf"
    render_audit_pack(_pack(with_finding=True), output)
    assert output.exists()
    assert output.stat().st_size > 0
    assert output.read_bytes().startswith(b"%PDF")


def test_render_audit_pack_handles_a_run_with_no_findings(tmp_path: Path) -> None:
    output = tmp_path / "clean.pdf"
    render_audit_pack(_pack(with_finding=False), output)
    assert output.read_bytes().startswith(b"%PDF")


def _classified_finding(
    *,
    owasp_llm: str = "LLM08:2025",
    owasp_secondary: tuple[str, ...] = (),
    atlas: tuple[str, ...] = ("AML.T0024", "AML.T0024.001"),
    nist: tuple[str, ...] = ("MEASURE 2.7",),
    remediation: str = "",
    evidence: str = "",
) -> Finding:
    return Finding(
        finding_id="f-controls",
        probe_id="rag-entity-bleed",
        severity=Severity.HIGH,
        confidence=0.9,
        status=FindingStatus.CONFIRMED,
        owner_tenant_id=UUID(int=0xB),
        observed_in_tenant_id=UUID(int=0xA),
        surface=Surface.VECTOR_DB,
        marker_id="marker-1",
        owasp_llm=owasp_llm,
        owasp_secondary=owasp_secondary,
        atlas=atlas,
        nist=nist,
        remediation_pointer=remediation,
        evidence_span=evidence,
    )


def test_finding_controls_lists_all_three_frameworks() -> None:
    assert (
        _finding_controls(_classified_finding())
        == "OWASP LLM08:2025; ATLAS AML.T0024, AML.T0024.001; NIST MEASURE 2.7"
    )


def test_finding_controls_renders_secondary_owasp_classes() -> None:
    # The spec §18 maps secondary OWASP classes (e.g. LLM06 for agent probes).
    # They live in evidence.json and must also reach the audit pack, in the OWASP
    # segment alongside the primary class.
    rendered = _finding_controls(_classified_finding(owasp_secondary=("LLM06:2025",)))
    assert rendered == (
        "OWASP LLM08:2025 (secondary: LLM06:2025); ATLAS AML.T0024, AML.T0024.001; NIST MEASURE 2.7"
    )


def test_finding_controls_renders_secondary_owasp_without_a_primary() -> None:
    rendered = _finding_controls(
        _classified_finding(owasp_llm="", owasp_secondary=("LLM02:2025", "LLM06:2025"), atlas=())
    )
    assert rendered == "OWASP secondary: LLM02:2025, LLM06:2025; NIST MEASURE 2.7"


def test_finding_controls_omits_empty_frameworks() -> None:
    # An erasure-style finding: an OWASP class and a NIST control, but no ATLAS
    # technique (erasure verification is a control check, not an attack).
    assert _finding_controls(_classified_finding(atlas=())) == "OWASP LLM08:2025; NIST MEASURE 2.7"


def test_finding_controls_empty_when_unclassified() -> None:
    # A finding with no control IDs at all (model defaults) renders no suffix.
    assert _finding_controls(_classified_finding(owasp_llm="", atlas=(), nist=())) == ""


def test_finding_lines_appends_control_ids_inline() -> None:
    [line] = _finding_lines((_classified_finding(atlas=("AML.T0024",)),))
    assert "[OWASP LLM08:2025; ATLAS AML.T0024; NIST MEASURE 2.7]" in line


def test_finding_lines_omits_suffix_for_unclassified_finding() -> None:
    [line] = _finding_lines((_classified_finding(owasp_llm="", atlas=(), nist=()),))
    assert "[" not in line


def test_finding_lines_includes_remediation_pointer() -> None:
    lines = _finding_lines((_classified_finding(remediation="rotate the shared index"),))
    assert len(lines) == 2
    assert "Remediation: rotate the shared index" in lines[1]


def test_finding_lines_omits_remediation_when_absent() -> None:
    lines = _finding_lines((_classified_finding(),))
    assert len(lines) == 1
    assert all("Remediation" not in line for line in lines)


def test_evidence_line_quotes_the_span() -> None:
    # The span (often a canary substring) is the auditor's proof, so the line
    # is rendered in quotes and italic.
    line = _evidence_line(_classified_finding(evidence="SECTUM-CANARY-ABC123"))
    assert line == '<i>Evidence: "SECTUM-CANARY-ABC123"</i>'


def test_evidence_line_omitted_when_absent() -> None:
    # An unconfirmed or pipeline finding may carry no span; render nothing.
    assert _evidence_line(_classified_finding()) is None


def test_remediation_line_helper() -> None:
    line = _remediation_line(_classified_finding(remediation="purge orphaned vectors"))
    assert line == "<i>Remediation: purge orphaned vectors</i>"
    assert _remediation_line(_classified_finding()) is None


def test_finding_lines_orders_summary_evidence_remediation() -> None:
    # Both evidence and remediation present: order is summary -> evidence -> remediation.
    lines = _finding_lines(
        (
            _classified_finding(
                evidence="leaked phrase here",
                remediation="rotate the shared index",
            ),
        )
    )
    assert len(lines) == 3
    assert "<b>high</b>" in lines[0]  # summary line
    assert lines[1] == '<i>Evidence: "leaked phrase here"</i>'
    assert lines[2] == "<i>Remediation: rotate the shared index</i>"


def test_scope_methodology_states_limits() -> None:
    # The scope/methodology narrative must carry the anti-hype limits (the
    # engineering spec, sections 18 and 20): no remediation, coverage not cert.
    text = " ".join(_SCOPE_METHODOLOGY)
    assert "does not remediate" in text
    assert "test coverage, not legal certification" in text


def test_scope_methodology_does_not_promise_zero_false_positives() -> None:
    # This narrative is rendered into the SIGNED pack an auditor reads. It stated
    # "confirmed findings carry no false positives" - a guarantee the pipeline
    # cannot make: an exact canary match is decided by the observation, but a
    # semantic confirmation also rests on the configured judge, and the
    # marker-traceability control bounds confirmations to the manifest's own
    # markers rather than proving each one correct. State the basis, claim no more.
    text = " ".join(_SCOPE_METHODOLOGY).lower()
    assert "no false positives" not in text
    assert "carry no false" not in text
    # ...and the honest basis is still stated, so the paragraph did not simply
    # lose the FP-control story it exists to explain.
    assert "trace back to a specific marker" in text
    assert "manifest-grounded" in text
    assert "unverified rather than confirmed" in text


# --- Retrieval-Pivot Rate confidence interval (Class 2 headline metric) -------


def _rpr_run(metrics: RunMetrics) -> RunResult:
    moment = datetime(2026, 5, 18, tzinfo=UTC)
    manifest = GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())
    return RunResult(
        run_id="rpr-1",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(manifest),
        started_at=moment,
        finished_at=moment,
        metrics=metrics,
    )


def test_retrieval_pivot_summary_renders_rate_interval_and_sample_size() -> None:
    # The flagship metric is shown with its 95% Wilson interval and n, so an
    # auditor reads the rate's precision rather than a bare point estimate.
    line = _retrieval_pivot_summary(
        _rpr_run(
            RunMetrics(
                retrieval_pivot_rate=334 / 350,
                retrieval_pivot_n=350,
                retrieval_pivot_k=334,
                retrieval_pivot_rate_ci=(0.9270, 0.9717),
            )
        )
    )
    assert line is not None
    assert line.startswith("95.4%")
    assert "95% CI" in line
    assert "n=350" in line


def test_retrieval_pivot_summary_absent_for_a_non_class2_run() -> None:
    # A run with no Class 2 steps records no rate, so the summary row is omitted.
    assert _retrieval_pivot_summary(_rpr_run(RunMetrics())) is None


def test_audit_pack_includes_the_retrieval_pivot_rate(tmp_path: Path) -> None:
    # End to end: a pack carrying the rate renders the labelled row into the PDF.
    manifest = GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())
    metrics = RunMetrics(
        retrieval_pivot_rate=0.5,
        retrieval_pivot_n=4,
        retrieval_pivot_k=2,
        retrieval_pivot_rate_ci=(0.15, 0.85),
    )
    pack = build_evidence_pack(_rpr_run(metrics), manifest, control_mappings=control_mappings())
    output = tmp_path / "rpr.pdf"
    render_audit_pack(pack, output)
    assert output.read_bytes().startswith(b"%PDF")


# --- Coverage & caveats matrix (erasure attestations) ------------------------


def _erasure_pack(coverage: dict[str, str]) -> EvidencePack:
    manifest = GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())
    moment = datetime(2026, 5, 18, tzinfo=UTC)
    run = RunResult(
        run_id="erasure-1",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(manifest),
        started_at=moment,
        finished_at=moment,
        metrics=RunMetrics(erasure_coverage=coverage),
    )
    return build_evidence_pack(run, manifest, control_mappings=control_mappings())


def test_coverage_rows_empty_for_a_non_erasure_run() -> None:
    # A run with no erasure_coverage metric (any non-erasure probe) yields no
    # rows, so the Coverage & caveats section is omitted entirely.
    assert _coverage_rows(_run_result(_manifest_only(), with_finding=False)) == []


def _manifest_only() -> GroundTruthManifest:
    return GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())


def test_coverage_rows_are_in_canonical_surface_order() -> None:
    # Rows follow the canonical erasure-surface order regardless of dict insertion
    # order, so the matrix is deterministic (the PDF is hashed into pdf_ref).
    coverage = {
        "backup": CoverageVerdict.NOT_COVERED.value,
        "vector_db": CoverageVerdict.ERASED.value,
        "tracing": CoverageVerdict.RESIDUAL.value,
    }
    rows = _coverage_rows(_erasure_pack(coverage).run_result)
    assert [surface for surface, _ in rows] == ["vector_db", "tracing", "backup"]


def test_reportlab_audit_pack_renders_a_coverage_run(tmp_path: Path) -> None:
    # A coverage-bearing erasure pack renders to a valid PDF (the matrix is a
    # reportlab Table; smoke-test that the build does not blow up).
    pack = _erasure_pack(
        {
            "vector_db": CoverageVerdict.ERASED.value,
            "tracing": CoverageVerdict.NOT_COVERED.value,
        }
    )
    output = tmp_path / "coverage.pdf"
    render_audit_pack(pack, output)
    assert output.read_bytes().startswith(b"%PDF")


def test_weasyprint_html_renders_the_coverage_matrix() -> None:
    # The weasyprint engine (pure-HTML build_audit_html) renders the coverage
    # matrix: a NOT_COVERED surface is visible to a DPO/auditor, and the standing
    # caveat is present. Both engines must surface the same NOT_COVERED rows.
    pack = _erasure_pack(
        {
            "vector_db": CoverageVerdict.ERASED.value,
            "tracing": CoverageVerdict.NOT_COVERED.value,
            "backup": CoverageVerdict.ATTESTABLE_WITH_CAVEAT.value,
        }
    )
    html = build_audit_html(pack)
    assert "Coverage &amp; caveats" in html
    assert "NOT_COVERED" in html
    assert "ATTESTABLE_WITH_CAVEAT" in html
    assert "vector_db" in html and "tracing" in html
    # The standing caveat is present (asserted on a substring with no HTML-special
    # characters, since build_audit_html escapes apostrophes etc.).
    assert "must not be read as erased" in _COVERAGE_CAVEAT
    assert "must not be read as erased" in html


def test_weasyprint_html_omits_coverage_for_a_non_erasure_pack() -> None:
    # A non-erasure pack (no coverage metric) has no Coverage section at all.
    html = build_audit_html(_pack(with_finding=True))
    assert "Coverage &amp; caveats" not in html


def test_the_pdf_recomputes_the_rate_from_the_counts_it_was_given() -> None:
    # The summary relayed `retrieval_pivot_rate` and its interval verbatim, so a
    # record whose own counts said 334 of 350 printed "2.0% (95% CI 1.9%-2.1%,
    # n=350)" into the signed, auditor-facing PDF - while `score`, which
    # recomputes, read the same record as 95.4%. Refusing to invent an interval
    # while faithfully relaying a fabricated one reads identically to the auditor.
    line = _retrieval_pivot_summary(
        _rpr_run(
            RunMetrics(
                retrieval_pivot_n=350,
                retrieval_pivot_k=334,
                retrieval_pivot_rate=0.02,
                retrieval_pivot_rate_ci=(0.019, 0.021),
            )
        )
    )
    assert line is not None
    assert line.startswith("95.4%"), line
    assert "1.9%" not in line and "2.1%" not in line

    # No counts: the rate is all the record has, and any interval it asserts is
    # uncheckable, so it is shown bare rather than dressed in one.
    bare = _retrieval_pivot_summary(
        _rpr_run(RunMetrics(retrieval_pivot_rate=0.125, retrieval_pivot_rate_ci=(0.124, 0.126)))
    )
    assert bare == "12.5%"

    # Counts that contradict themselves state nothing.
    assert (
        _retrieval_pivot_summary(_rpr_run(RunMetrics(retrieval_pivot_n=10, retrieval_pivot_k=99)))
        is None
    )


def test_both_pdf_engines_state_the_same_summary_facts() -> None:
    # `pdf_weasyprint` promises it "mirrors the reportlab renderer's sections and
    # reuses its shared content ... so both engines assert the same facts", and it
    # had silently dropped the flagship Retrieval-Pivot Rate row: two packs of the
    # same run said different things depending on an optional dependency. Compare
    # the row LABELS rather than the rendered bytes, which legitimately differ.
    from sectum_ai.evidence.pdf_weasyprint import build_audit_html

    metrics = RunMetrics(retrieval_pivot_n=48, retrieval_pivot_k=39)
    run = _rpr_run(metrics)
    html = build_audit_html(EvidencePack(run_result=run, manifest_hash=run.manifest_hash))
    for label in (
        "Run started",
        "Run finished",
        "Probes exercised",
        "Findings recorded",
        "Confirmed findings",
        "Retrieval-Pivot Rate",
    ):
        assert label in html, f"the weasyprint engine omits the {label!r} summary row"
    rpr = _retrieval_pivot_summary(run)
    assert rpr is not None and rpr in html


def test_both_pdf_engines_mark_a_finding_that_describes_a_fake() -> None:
    # SARIF floors such a finding's severity and OSCAL prefixes its observation;
    # both PDF engines rendered a fake-backed CRITICAL identically to a live one -
    # in the document an auditor actually reads. Keyed on an explicit LIVE, like
    # every sibling: a surface the record does not describe is not evidence of a
    # live backend.
    from sectum_ai.evidence.pdf import _finding_lines
    from sectum_ai.evidence.pdf_weasyprint import build_audit_html

    base = _run_result(_manifest_only(), with_finding=True)
    fake = base.model_copy(update={"surface_provenance": {"vector_db": "SYNTHETIC"}})
    live = base.model_copy(update={"surface_provenance": {"vector_db": "LIVE"}})

    assert any("[synthetic surface" in line for line in _finding_lines(fake.findings, fake))
    assert not any("[synthetic surface" in line for line in _finding_lines(live.findings, live))

    fake_html = build_audit_html(EvidencePack(run_result=fake, manifest_hash=fake.manifest_hash))
    live_html = build_audit_html(EvidencePack(run_result=live, manifest_hash=live.manifest_hash))
    assert "[synthetic surface" in fake_html
    assert "[synthetic surface" not in live_html
