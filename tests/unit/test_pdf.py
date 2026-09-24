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
    DetectionProvenance,
    EvidencePack,
    Finding,
    FindingStatus,
    GroundTruthManifest,
    RunMetrics,
    RunResult,
    Severity,
    Surface,
    SurfaceProvenance,
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


def _erasure_pack(
    coverage: dict[str, str], provenance: dict[str, str] | None = None
) -> EvidencePack:
    manifest = GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())
    moment = datetime(2026, 5, 18, tzinfo=UTC)
    run = RunResult(
        run_id="erasure-1",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(manifest),
        started_at=moment,
        finished_at=moment,
        surface_provenance=provenance or {},
        metrics=RunMetrics(erasure_coverage=coverage),
    )
    return build_evidence_pack(run, manifest, control_mappings=control_mappings())


def test_a_live_erasure_surface_the_block_never_mentions_is_still_a_row() -> None:
    # Both siblings default a missing surface to NOT_COVERED - `oscal`, and
    # `controls._erasure_assertion`, whose comment records the same defect: "it was
    # neither verified nor unestablished - it simply vanished." This matrix is the
    # DPO-facing one, and it was the copy that still vanished it: the row
    # disappeared while the control assertion said absence could not be established
    # on that very surface.
    pack = _erasure_pack(
        {"vector_db": CoverageVerdict.ERASED.value},
        provenance={"vector_db": "LIVE", "semantic_cache": "LIVE", "mcp": "LIVE"},
    )
    rows = dict(_coverage_rows(pack.run_result))
    assert rows["semantic_cache"] == CoverageVerdict.NOT_COVERED.value, rows
    # An isolation-only live surface is not an erasure surface at all, so it gets no
    # row - the narrowing `ERASURE_SURFACES` exists for.
    assert "mcp" not in rows, rows


def test_an_impossible_pivot_count_is_stated_not_silently_omitted() -> None:
    # `score` refuses to grade a record whose counts contradict themselves; the PDF
    # omitted the row, which is byte-identical to a run that took no Class-2 step at
    # all - so the auditor's document hid a corrupt record behind the same silence
    # as an honest one.
    manifest = _manifest_only()
    moment = datetime(2026, 5, 18, tzinfo=UTC)
    run = RunResult(
        run_id="r",
        scenario_hash="scenario-hash",
        manifest_hash=canonical_hash(manifest),
        started_at=moment,
        finished_at=moment,
        metrics=RunMetrics(retrieval_pivot_k=60, retrieval_pivot_n=48),
    )
    row = _retrieval_pivot_summary(run)
    assert row is not None
    assert "60 of 48" in row and "impossible" in row, row
    # A run that simply took no Class-2 step still omits the row.
    silent = run.model_copy(update={"metrics": RunMetrics()})
    assert _retrieval_pivot_summary(silent) is None


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
    # uncheckable - so it is not dressed in one, and not printed bare either.
    # Bare, it was byte-identical to a measured rate, which is the same conflation
    # the incoherent branch below refuses.
    bare = _retrieval_pivot_summary(
        _rpr_run(RunMetrics(retrieval_pivot_rate=0.125, retrieval_pivot_rate_ci=(0.124, 0.126)))
    )
    assert bare is not None and bare.startswith("12.5%"), bare
    assert "asserted by the record" in bare, bare
    assert "0.124" not in bare and "12.4%" not in bare, bare

    # Counts that contradict themselves state the contradiction. Omitting the row
    # was byte-identical to a run that took no Class-2 step, so the auditor's
    # document hid a corrupt record behind an honest record's silence - and `score`
    # refuses to grade the same record outright. This repo has settled that trade
    # before, one module over: "Silence was the original defect ... and an
    # accusation is the wrong cure. Both outcomes name the consequence instead."
    incoherent = _retrieval_pivot_summary(
        _rpr_run(RunMetrics(retrieval_pivot_n=10, retrieval_pivot_k=99))
    )
    assert incoherent is not None
    assert "99 of 10" in incoherent and "impossible" in incoherent, incoherent
    # It must not print a rate, which is the thing that cannot be believed.
    assert "%" not in incoherent, incoherent


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


def test_an_erasure_only_pack_does_not_claim_to_attest_isolation() -> None:
    # `_SCOPE_METHODOLOGY[0]` said "this pack attests the isolation of those
    # surfaces" on EVERY pack, including an erasure attestation whose only probe
    # was `gdpr-erasure-verification`. That is verbatim the claim
    # `controls._run_supports` exists to refuse - the mapping table was fixed and
    # the prose one section above it was not, so both shipped samples carried it.
    from sectum_ai.evidence.pdf import scope_methodology

    moment = datetime(2026, 1, 1, tzinfo=UTC)
    base = {
        "run_id": "r",
        "scenario_hash": "s",
        "manifest_hash": "m" * 64,
        "started_at": moment,
        "finished_at": moment,
    }
    erasure_only = RunResult(**base, probe_versions={"gdpr-erasure-verification": "1"})
    assert "attests the isolation" not in scope_methodology(erasure_only)[0]
    assert "makes no claim about tenant isolation" in scope_methodology(erasure_only)[0]

    # An isolation run keeps the original wording, and a mixed one does too -
    # given a live surface to attest. With none, the paragraph directly above this
    # one already calls the pack a demonstration, so it says so here too.
    live = {"surface_provenance": {"vector_db": "LIVE"}}
    isolation = RunResult(**base, probe_versions={"tenant-boundary-fetch": "1"}, **live)
    assert "attests the isolation" in scope_methodology(isolation)[0]
    mixed = RunResult(
        **base,
        probe_versions={"gdpr-erasure-verification": "1", "tenant-boundary-fetch": "1"},
        **live,
    )
    assert "attests the isolation" in scope_methodology(mixed)[0]
    # The scope paragraph is shared; the DETECTOR paragraph is not, and asserting
    # it was is what let an erasure attestation promise an auditor "semantic
    # similarity, then a calibrated judge" over a workflow that invokes neither.
    assert scope_methodology(erasure_only)[2:] == scope_methodology(isolation)[2:]
    # The scope paragraph narrows on provenance here as well: an all-synthetic
    # erasure pack said "This pack ATTESTS whether those markers are still
    # retrievable" directly beneath "This pack is a demonstration, not an
    # attestation" - in both shipped samples.
    assert "attests whether" not in scope_methodology(erasure_only)[0].lower()
    live_erasure = erasure_only.model_copy(update={"surface_provenance": {"vector_db": "LIVE"}})
    assert "attests whether" in scope_methodology(live_erasure)[0].lower()
    erasure_detector = scope_methodology(erasure_only)[1]
    assert "no embedding model and no judge" in erasure_detector, erasure_detector
    for claim in ("semantic similarity", "calibrated judge"):
        assert claim not in erasure_detector, erasure_detector


def test_the_detector_paragraph_says_which_tiers_actually_ran() -> None:
    # The paragraph stated "exact canary match, then semantic similarity, then a
    # calibrated judge" unconditionally, and the record carried nothing that could
    # condition it - while both tiers past the first are OFF by default:
    # `sectum-ai init` scaffolds `embedder.kind: fake` and `judge.kind: fake`,
    # which resolve to a hashing vector its own docstring calls "not semantically
    # meaningful beyond lexical overlap" and a token-order string matcher. A
    # customer with live adapters read "a calibrated judge" in the same PDF that
    # told them every surface was a live backend.
    from sectum_ai.evidence.pdf import scope_methodology

    moment = datetime(2026, 1, 1, tzinfo=UTC)
    base = {
        "run_id": "r",
        "scenario_hash": "s",
        "manifest_hash": "m" * 64,
        "started_at": moment,
        "finished_at": moment,
        "probe_versions": {"tenant-boundary-fetch": "1"},
    }
    offline = RunResult(
        **base,
        detection=DetectionProvenance(
            embedder_kind="fake", judge_kind="fake", semantic_threshold=0.62
        ),
    )
    real = RunResult(
        **base,
        detection=DetectionProvenance(
            embedder_kind="openai",
            embedder_model="text-embedding-3-small",
            judge_kind="anthropic",
            judge_model="claude-sonnet-5",
            semantic_threshold=0.83,
        ),
    )
    offline_para, real_para = scope_methodology(offline)[1], scope_methodology(real)[1]
    # Checked as an AFFIRMATIVE claim, not as a substring: the offline paragraph
    # says "not a calibrated judge", so `"calibrated judge" not in ...` fails on
    # the sentence that fixes the defect.
    claims_a_judge = "then the configured judge"
    assert "no embedding model" in offline_para, offline_para
    assert "no judge" in offline_para, offline_para
    assert claims_a_judge not in offline_para, offline_para
    assert "lexical overlap rather than meaning" in offline_para, offline_para
    assert "semantic similarity against the configured embedding model" in real_para, real_para
    assert claims_a_judge in real_para, real_para

    # A record written before `detection` existed asserts neither: the first tier
    # always runs, the other two are unknown, and claiming either is the defect.
    unrecorded = scope_methodology(RunResult(**base))[1]
    for claim in (claims_a_judge, "semantic similarity", "OFFLINE"):
        assert claim not in unrecorded, unrecorded

    # The two MIXED corners. `offline_only` collapsed the tiers with `and`, so one
    # real provider flipped the whole paragraph to the layered claim: a run with a
    # real embedder and the default `judge.kind: fake` told an auditor "then the
    # configured judge" over a token-order string matcher. Both are configured
    # independently, and `EmbedderConfig.base_url` markets pointing the embedder at
    # a local Ollama while a judge needs a chat model - so this corner is a
    # documented setup, not a corner case.
    real_embedder_only = RunResult(
        **base,
        detection=DetectionProvenance(
            embedder_kind="openai",
            embedder_model="text-embedding-3-small",
            judge_kind="fake",
            semantic_threshold=0.83,
        ),
    )
    mixed = scope_methodology(real_embedder_only)[1]
    assert "semantic similarity against the configured embedding model" in mixed, mixed
    assert claims_a_judge not in mixed, mixed
    assert "not a calibrated judge" in mixed, mixed

    real_judge_only = RunResult(
        **base,
        detection=DetectionProvenance(
            embedder_kind="fake", judge_kind="anthropic", semantic_threshold=0.62
        ),
    )
    other = scope_methodology(real_judge_only)[1]
    assert claims_a_judge in other, other
    assert "semantic similarity against the configured embedding model" not in other, other
    assert "lexical overlap rather than meaning" in other, other


def test_the_coverage_matrix_says_which_rows_describe_a_fake() -> None:
    # The matrix was the only per-row artifact with no surface provenance, so a
    # surface that was Sectum's own in-memory fake read "verified clean - no
    # marker retrievable...". Every sibling states it per row, because a
    # run-level paragraph does not reach a reader tabulating rows.
    from sectum_ai.evidence.pdf import coverage_gloss

    moment = datetime(2026, 1, 1, tzinfo=UTC)
    run = RunResult(
        run_id="r",
        scenario_hash="s",
        manifest_hash="m" * 64,
        started_at=moment,
        finished_at=moment,
        probe_versions={"gdpr-erasure-verification": "1"},
        surface_provenance={"vector_db": "LIVE", "semantic_cache": "SYNTHETIC"},
    )
    live = coverage_gloss(run, "vector_db", "ERASED")
    assert live.startswith("verified clean"), live

    fake = coverage_gloss(run, "semantic_cache", "ERASED")
    assert fake.startswith("[synthetic surface"), fake
    assert "verified clean" in fake

    absent = coverage_gloss(run, "agent_memory", "ERASED")
    assert absent.startswith("[surface provenance not recorded"), absent

    # NOT_COVERED asserts nothing about the surface, so it needs no prefix.
    assert (
        coverage_gloss(run, "semantic_cache", "NOT_COVERED") == "not verified by this attestation"
    )


def test_an_unplaceable_finding_is_not_reported_as_one_on_a_fake() -> None:
    # "on live surfaces 0" reads as "we placed them, on a fake". A finding whose
    # backing surface the block never records was not placed at all - a different
    # claim - and the two rendered byte-identically in the PDF summary row and in
    # the CLI's, the same conflation `unaccounted_surfaces` exists to break in the
    # provenance paragraph one section above.
    from sectum_ai.cli.app import _confirmed_summary
    from sectum_ai.evidence.pdf import confirmed_by_kind
    from sectum_ai.spec import SurfaceProvenance

    manifest = GroundTruthManifest(manifest_id="m-1", scenario_hash="scenario-hash", markers=())
    leaks = _run_result(manifest, with_finding=True).findings
    assert leaks, "the fixture must carry a confirmed finding on vector_db"
    on_a_fake = {"vector_db": SurfaceProvenance.SYNTHETIC.value}
    unplaceable = {"semantic_cache": SurfaceProvenance.LIVE.value}

    fake_run = _run_result(manifest, with_finding=True).model_copy(
        update={"surface_provenance": on_a_fake}
    )
    lost_run = _run_result(manifest, with_finding=True).model_copy(
        update={"surface_provenance": unplaceable}
    )

    assert "on live surfaces 0" in confirmed_by_kind(fake_run)
    assert "does not record" not in confirmed_by_kind(fake_run)
    assert "does not record" in confirmed_by_kind(lost_run), confirmed_by_kind(lost_run)
    assert confirmed_by_kind(fake_run) != confirmed_by_kind(lost_run)

    # And its CLI sibling, which had the identical gap.
    assert "does not record" not in _confirmed_summary(list(leaks), on_a_fake)
    assert "does not record" in _confirmed_summary(list(leaks), unplaceable)


def test_the_pdf_says_whether_this_pack_has_an_independent_anchor() -> None:
    # The PDF told every reader "any edit to the attested content changes the
    # attested digest and fails verification" and never said whether THIS pack is
    # anchored. Without an external anchor the timestamp is `LocalTimestamper`'s,
    # which its own docstring calls "reproducible by anyone over any digest ... an
    # attacker who edits a pack can simply re-stamp it" - so the sentence was an
    # over-claim, and a reader following the instruction on a default pack gets
    # `[FAIL] independent-anchor` and `VERIFICATION FAILED` at exit 4 over a pack
    # nobody touched. Every sibling renderer makes the distinction - `_echo_verdict`,
    # the `independent-anchor` check, the in-toto `anchors` block, and PACK-README
    # inside the same deliverable - and the audit PDF, the one an auditor reads,
    # did not.
    from sectum_ai.evidence.pdf import anchor_statement

    moment = datetime(2026, 1, 1, tzinfo=UTC)
    run = RunResult(
        run_id="r",
        scenario_hash="s",
        manifest_hash="m" * 64,
        started_at=moment,
        finished_at=moment,
        probe_versions={"tenant-boundary-fetch": "1"},
    )
    local = EvidencePack(run_result=run, manifest_hash="m" * 64, tsa_token='{"digest": "x"}')
    unanchored = anchor_statement(local)
    assert "Independent anchor: NONE" in unanchored, unanchored
    assert "--allow-unanchored" in unanchored, unanchored

    # A real TSA returns a signed BINARY token, not JSON; Rekor adds its proof.
    anchored = local.model_copy(
        update={"tsa_token": "MIIFbinary", "rekor_proof": '{"logIndex": 42}'}
    )
    present = anchor_statement(anchored)
    assert "RFC 3161 timestamp and Rekor transparency log" in present, present
    assert "NONE" not in present, present

    # The render path passes the INTENT, because the PDF is built before the token
    # exists; both sources must agree or the bound PDF contradicts the pack that
    # binds it - which the sample-regeneration guard would catch only by luck.
    assert anchor_statement(local, anchors=(False, False)) == unanchored
    assert anchor_statement(local, anchors=(True, True)) == present


def test_a_pack_that_calls_itself_a_demonstration_does_not_then_attest() -> None:
    # `provenance_statement` ends "This pack is a demonstration, not an
    # attestation." for an all-synthetic run, and the scope paragraph is rendered
    # directly beneath it saying "this pack attests the isolation of those
    # surfaces". `scope_methodology` conditioned that paragraph on
    # erasure-vs-isolation and never on provenance, so the two shipped back to
    # back. The renderer's own doctrine cuts both ways: a reader who lands on
    # "Scope and methodology" carries away the second sentence.
    from sectum_ai.evidence.pdf import provenance_statement, scope_methodology

    moment = datetime(2026, 1, 1, tzinfo=UTC)
    base = {
        "run_id": "r",
        "scenario_hash": "s",
        "manifest_hash": "m" * 64,
        "started_at": moment,
        "finished_at": moment,
        "probe_versions": {"tenant-boundary-fetch": "1"},
    }
    synthetic = RunResult(**base, surface_provenance={"vector_db": "SYNTHETIC"})
    assert "not an attestation" in provenance_statement(synthetic)
    assert "attests the isolation" not in scope_methodology(synthetic)[0]

    # A live run keeps the attestation claim - the paragraph above it earns it.
    live = RunResult(**base, surface_provenance={"vector_db": "LIVE"})
    assert "attests the isolation" in scope_methodology(live)[0]


def test_a_pivot_rate_with_no_sample_is_not_rendered_as_a_measurement() -> None:
    # The `k > n` branch already refuses to relay an incoherent record, for the
    # stated reason that omitting the row is "byte-identical to a run that took no
    # Class-2 step at all". A rate with n=0 has the mirror problem: rendered bare
    # it is byte-identical to a measured rate, which everywhere else in this PDF
    # comes with its interval and its n.
    from sectum_ai.evidence.pdf import _retrieval_pivot_summary

    moment = datetime(2026, 1, 1, tzinfo=UTC)
    asserted = RunResult(
        run_id="r",
        scenario_hash="s",
        manifest_hash="m" * 64,
        started_at=moment,
        finished_at=moment,
        metrics=RunMetrics(retrieval_pivot_rate=0.125, retrieval_pivot_n=0, retrieval_pivot_k=0),
    )
    summary = _retrieval_pivot_summary(asserted)
    assert summary is not None
    assert "12.5%" in summary, summary
    assert "asserted by the record" in summary, summary

    # A measured rate is unchanged: it keeps its interval and its n.
    measured = asserted.model_copy(
        update={
            "metrics": RunMetrics(
                retrieval_pivot_rate=0.125, retrieval_pivot_n=48, retrieval_pivot_k=6
            )
        }
    )
    measured_summary = _retrieval_pivot_summary(measured)
    assert measured_summary is not None
    assert "95% CI" in measured_summary and "n=48" in measured_summary, measured_summary
    assert "asserted by the record" not in measured_summary, measured_summary


def test_the_anchor_statement_names_every_flag_verify_will_demand() -> None:
    # The unanchored branch named `--allow-unanchored` and stopped. On an
    # all-synthetic pack - the default for a scaffolded config, and what both
    # shipped sample erasure PDFs carry - `verify` ALSO gates on run-scope, so an
    # auditor following the bolded instruction in the document they were handed
    # got `[FAIL] run-scope` and `VERIFICATION FAILED` at exit 4 over a genuine,
    # untampered artifact. A false alarm on a real pack is the same class of harm
    # as a missed leak. The anchored branch named no flag at all and fails the
    # same way, so the note belongs to BOTH branches: liveness is a separate axis
    # from the anchor, and `verify` gates on it separately.
    from sectum_ai.evidence.pdf import anchor_statement

    moment = datetime(2026, 1, 1, tzinfo=UTC)
    synthetic = RunResult(
        run_id="r",
        scenario_hash="s",
        manifest_hash="m" * 64,
        started_at=moment,
        finished_at=moment,
        probe_versions={"tenant-boundary-fetch": "1"},
        surface_provenance={Surface.VECTOR_DB.value: SurfaceProvenance.SYNTHETIC.value},
    )
    local = EvidencePack(run_result=synthetic, manifest_hash="m" * 64, tsa_token='{"digest": "x"}')
    anchored = local.model_copy(
        update={"tsa_token": "MIIFbinary", "rekor_proof": '{"logIndex": 42}'}
    )
    for statement in (anchor_statement(local), anchor_statement(anchored)):
        assert "--allow-synthetic" in statement, statement

    # And it must NOT be appended when a surface WAS live, or the document tells
    # an auditor to pass a flag that would make `verify` accept a demo pack.
    live = synthetic.model_copy(
        update={"surface_provenance": {Surface.VECTOR_DB.value: SurfaceProvenance.LIVE.value}}
    )
    for statement in (
        anchor_statement(local.model_copy(update={"run_result": live})),
        anchor_statement(anchored.model_copy(update={"run_result": live})),
    ):
        assert "--allow-synthetic" not in statement, statement


def test_the_anchored_statement_does_not_promise_self_contained_tamper_evidence() -> None:
    # `docs/threat-model.md` is explicit that an anchor "does not stop an
    # adversary from editing a pack, recomputing the digest, and obtaining a
    # fresh anchor - that pack will also verify", and that the evidence is
    # comparative. The PDF - the artifact an auditor actually reads - asserted
    # the opposite, in the bolded closing line of its integrity section, while
    # its own sibling constant in the same block was scrupulously hedged.
    from sectum_ai.evidence.pdf import anchor_statement

    moment = datetime(2026, 1, 1, tzinfo=UTC)
    run = RunResult(
        run_id="r",
        scenario_hash="s",
        manifest_hash="m" * 64,
        started_at=moment,
        finished_at=moment,
        probe_versions={"tenant-boundary-fetch": "1"},
    )
    anchored = EvidencePack(
        run_result=run,
        manifest_hash="m" * 64,
        tsa_token="MIIFbinary",
        rekor_proof='{"logIndex": 42}',
    )
    statement = anchor_statement(anchored)
    assert "cannot be covered up" not in statement, statement
    assert "comparative" in statement, statement
    assert "will also verify" in statement, statement


def test_the_scope_note_says_which_of_the_three_things_verify_will_object_to() -> None:
    # The first version keyed on `live_surfaces()` being empty, which is true for
    # an all-synthetic run AND for a record that carries no provenance block at
    # all - so the PDF asserted "No surface in this run was live" over a pack
    # whose own run-scope gate says exactly that cannot be established. It was
    # also silent on the third case, where run-scope FAILS with a live surface
    # present because findings rest on a surface the block never recorded: the
    # auditor is sent to a tamper-style exit 4 on a genuine artifact, which is the
    # harm the note was added to prevent.
    from sectum_ai.evidence.pdf import anchor_statement

    moment = datetime(2026, 1, 1, tzinfo=UTC)

    def _pack(provenance: dict[str, str], findings: tuple[Finding, ...] = ()) -> EvidencePack:
        run = RunResult(
            run_id="r",
            scenario_hash="s",
            manifest_hash="m" * 64,
            started_at=moment,
            finished_at=moment,
            probe_versions={"tenant-boundary-fetch": "1"},
            surface_provenance=provenance,
            findings=findings,
        )
        return EvidencePack(run_result=run, manifest_hash="m" * 64, tsa_token='{"digest": "x"}')

    # 1. No provenance block: "cannot be established", never "was not live".
    unrecorded = anchor_statement(_pack({}))
    assert "--allow-synthetic" in unrecorded, unrecorded
    assert "cannot be established" in unrecorded, unrecorded
    assert "No surface in this run was live" not in unrecorded, unrecorded

    # 2. Recorded and synthetic: the original sentence, which was right here.
    synthetic = anchor_statement(
        _pack({Surface.VECTOR_DB.value: SurfaceProvenance.SYNTHETIC.value})
    )
    assert "No surface in this run was live" in synthetic, synthetic

    # 3. Every RECORDED surface live, but a finding rests on one that is not in
    #    the block. `verify` fails run-scope; the note was absent entirely.
    finding = Finding(
        finding_id="f1",
        probe_id="semantic-cache-contamination",
        severity=Severity.CRITICAL,
        confidence=1.0,
        status=FindingStatus.CONFIRMED,
        owner_tenant_id=UUID(int=0xB),
        observed_in_tenant_id=UUID(int=0xA),
        surface=Surface.SEMANTIC_CACHE,
        marker_id="mkr-1",
        evidence_span="SECTUM-CANARY-X",
        owasp_llm="LLM08:2025",
    )
    unaccounted = anchor_statement(
        _pack({Surface.VECTOR_DB.value: SurfaceProvenance.LIVE.value}, (finding,))
    )
    assert "--allow-synthetic" in unaccounted, unaccounted
    assert "never recorded" in unaccounted, unaccounted

    # 4. Fully live and fully accounted: no note at all.
    clean = anchor_statement(_pack({Surface.VECTOR_DB.value: SurfaceProvenance.LIVE.value}))
    assert "--allow-synthetic" not in clean, clean


def test_the_methodology_distinguishes_a_semantic_tier_that_was_gated_shut() -> None:
    # `DetectionProvenance.semantic_threshold` was recorded for exactly this - its
    # docstring says a pack where the semantic tier was gated shut "was
    # indistinguishable from one where it ran" - and no renderer read it, so the
    # methodology paragraph was byte-identical at 0.62 and at 1.0 while telling
    # the auditor "then semantic similarity against the configured embedding
    # model". The gate is `similarity < threshold: continue` and cosine
    # similarity is clamped to 1.0, so at 1.0 the tier admits nothing.
    from sectum_ai.evidence.pdf import scope_methodology

    moment = datetime(2026, 1, 1, tzinfo=UTC)

    def methodology(threshold: float) -> str:
        run = RunResult(
            run_id="r",
            scenario_hash="s",
            manifest_hash="m" * 64,
            started_at=moment,
            finished_at=moment,
            probe_versions={"rag-entity-bleed": "1"},
            detection=DetectionProvenance(
                embedder_kind="openai",
                embedder_model="text-embedding-3-small",
                judge_kind="anthropic",
                judge_model="claude-sonnet-5",
                semantic_threshold=threshold,
            ),
        )
        return " ".join(scope_methodology(run))

    calibrated, shut = methodology(0.62), methodology(1.0)
    assert calibrated != shut, "a gated-shut semantic tier reads like one that ran"
    assert "0.62 or above" in calibrated, calibrated
    assert "admitted nothing an exact match had not already decided" in shut, shut
    assert "admitted nothing" not in calibrated, calibrated
