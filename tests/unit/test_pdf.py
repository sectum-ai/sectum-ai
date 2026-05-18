"""Tests for the audit-pack PDF renderer."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sectum.evidence import build_evidence_pack, control_mappings, render_audit_pack
from sectum.spec import (
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
