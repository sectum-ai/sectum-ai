"""Tests for the audit-pack PDF renderer."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sectum_ai.evidence import build_evidence_pack, control_mappings, render_audit_pack
from sectum_ai.evidence.pdf import (
    _SCOPE_METHODOLOGY,
    _evidence_line,
    _finding_controls,
    _finding_lines,
    _remediation_line,
)
from sectum_ai.spec import (
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
