"""Tests for the weasyprint audit-pack renderer (the optional HTML/CSS engine).

The HTML builder is pure and runs everywhere; the actual PDF render needs the
``weasyprint`` extra and its system libraries, so those tests importorskip.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from sectum_ai.evidence import PdfEngine, render_audit_pack
from sectum_ai.evidence.pdf_weasyprint import build_audit_html, render_weasyprint
from sectum_ai.spec import (
    ControlMapping,
    EvidenceError,
    EvidencePack,
    Finding,
    FindingStatus,
    RunResult,
    Severity,
    Surface,
)


def _finding(**overrides: object) -> Finding:
    base: dict[str, object] = {
        "finding_id": "f1",
        "probe_id": "rag-entity-bleed",
        "severity": Severity.HIGH,
        "confidence": 1.0,
        "status": FindingStatus.CONFIRMED,
        "owner_tenant_id": UUID(int=1),
        "observed_in_tenant_id": UUID(int=2),
        "surface": Surface.VECTOR_DB,
        "marker_id": "SECTUM-CANARY-AAA",
        "evidence_span": 'leaked "SECTUM-CANARY-AAA" <here>',
        "owasp_llm": "LLM08:2025",
        "atlas": ("AML.T0024",),
        "nist": ("MEASURE 2.7",),
        "remediation_pointer": "Scope retrieval by tenant.",
    }
    base.update(overrides)
    return Finding(**base)


def _pack(*findings: Finding) -> EvidencePack:
    run = RunResult(
        run_id="run-pdf",
        scenario_hash="s",
        manifest_hash="m-hash",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        findings=findings if findings else (_finding(),),
    )
    return EvidencePack(
        run_result=run,
        manifest_hash="m-hash",
        control_mappings=(
            ControlMapping(
                framework="SOC 2",
                control_ids=("CC6.1", "CC6.6"),
                assertion="Tenant isolation verified by probing.",
            ),
        ),
    )


# --- build_audit_html: pure, runs without weasyprint --------------------------


def test_html_has_the_expected_sections() -> None:
    html = build_audit_html(_pack())
    for heading in (
        "Verification summary",
        "Scope and methodology",
        "Findings",
        "Compliance control coverage",
        "Integrity and independent verification",
    ):
        assert heading in html


def test_html_renders_the_finding_with_controls_and_proof() -> None:
    html = build_audit_html(_pack())
    assert "rag-entity-bleed" in html
    assert "OWASP LLM08:2025; ATLAS AML.T0024; NIST MEASURE 2.7" in html
    assert "Remediation: Scope retrieval by tenant." in html


def test_html_escapes_finding_text() -> None:
    # The evidence span contains <here> and quotes: it must be HTML-escaped, not
    # injected as raw markup.
    html = build_audit_html(_pack())
    assert "&lt;here&gt;" in html
    assert "<here>" not in html


def test_html_includes_the_coverage_disclaimer_and_integrity_digests() -> None:
    html = build_audit_html(_pack())
    assert "coverage" in html.lower()
    assert "m-hash" in html  # the manifest hash appears in the integrity table


def test_verification_instruction_points_at_the_attested_digest_not_the_run_digest() -> None:
    # After ADR-0016 the timestamp token attests the whole-pack attested digest,
    # not the run digest. The auditor-facing instruction must NOT tell the reader
    # to recompute the run digest and check it against the token (doing so always
    # mismatches and reads as tampering). The run digest is shown only as a run
    # identifier. Guards the prose against regressing to the pre-ADR-0016 wording.
    html = build_audit_html(_pack())
    assert "sectum-ai verify" in html
    assert "attested digest" in html.lower()
    assert "run identifier" in html.lower()  # the displayed run digest is labelled as such
    # The stale instruction (recompute the RUN digest, check it against the token)
    # must be gone.
    assert "recomputing the run digest" not in html
    assert "recompute the run digest" not in html


def test_html_handles_a_run_with_no_findings() -> None:
    run = RunResult(
        run_id="empty",
        scenario_hash="s",
        manifest_hash="m",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        findings=(),
    )
    html = build_audit_html(EvidencePack(run_result=run, manifest_hash="m"))
    assert "No findings were recorded for this run." in html


def test_html_severity_badge_uses_a_known_colour() -> None:
    critical = build_audit_html(_pack(_finding(severity=Severity.CRITICAL)))
    assert "#8b1a1a" in critical  # the critical accent colour


# --- render dispatch + the missing-extra error path ---------------------------


def test_weasyprint_engine_without_the_extra_raises_evidence_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force `import weasyprint` to fail (None in sys.modules raises ImportError),
    # so the missing-extra branch runs deterministically even when the extra is
    # installed. The error must name the extra so the user knows the fix.
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    with pytest.raises(EvidenceError, match=r"sectum-ai\[weasyprint\]"):
        render_weasyprint(_pack())


def test_render_audit_pack_weasyprint_writes_a_pdf(tmp_path: Path) -> None:
    pytest.importorskip("weasyprint")
    out = tmp_path / "wp.pdf"
    render_audit_pack(_pack(), out, engine=PdfEngine.WEASYPRINT)
    assert out.read_bytes()[:5] == b"%PDF-"
    assert out.stat().st_size > 1000


def test_default_engine_is_reportlab(tmp_path: Path) -> None:
    # The default path must not require weasyprint: rendering with no engine
    # argument produces a PDF via reportlab (always installed).
    out = tmp_path / "default.pdf"
    render_audit_pack(_pack(), out)
    assert out.read_bytes()[:5] == b"%PDF-"


def test_weasyprint_extra_chain_terminates_in_the_package() -> None:
    # Guard the install chain: sectum-ai[weasyprint] -> sectum-ai-evidence
    # [weasyprint] -> weasyprint. A pure-import test cannot catch an empty extra
    # (weasyprint may be present in the dev env regardless), so the documented
    # `pip install "sectum-ai[weasyprint]"` could install nothing and the feature
    # be unreachable. This parses the manifests and asserts the chain resolves.
    import tomllib

    root = Path(__file__).resolve().parents[2]
    core = tomllib.loads((root / "packages/core/pyproject.toml").read_text())
    evidence = tomllib.loads((root / "packages/evidence/pyproject.toml").read_text())

    core_extra = core["project"]["optional-dependencies"]["weasyprint"]
    assert any("sectum-ai-evidence[weasyprint]" in dep for dep in core_extra)

    evidence_extra = evidence["project"]["optional-dependencies"]["weasyprint"]
    assert any(dep.split(">=")[0].split("[")[0].strip() == "weasyprint" for dep in evidence_extra)
