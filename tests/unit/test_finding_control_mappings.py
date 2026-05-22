"""Findings carry their probe's control classification (the engineering spec, sections 9 and 18).

Each probe declares ``owasp_llm``/``atlas_techniques``/``nist_rmf``; every finding
it produces is stamped with them so the evidence pack renders per-finding control
IDs. Covers the three finding-construction sites: the detection pipeline (the nine
plan/detect probes), the erasure probe, and a manual pipeline call (backward
compatibility - the defaults leave a manual call unchanged).
"""

from uuid import UUID

from sectum.adapters import FakeVectorStore
from sectum.probes import (
    AgentToolHijackProbe,
    ErasureProbe,
    LoraCrossTenantProbe,
    RagPoisoningProbe,
    TenantBoundaryProbe,
    confirmed_findings,
)
from sectum.probes.detection import DetectionPipeline
from sectum.runner import Runner
from sectum.spec import MarkerType, Substrate, Surface
from sectum.substrate import build_substrate, default_scenario


def _seeded_store(
    substrate: Substrate, *, shared_index: bool = False, soft_delete: bool = False
) -> FakeVectorStore:
    store = FakeVectorStore(shared_index=shared_index, soft_delete=soft_delete)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        store.upsert(tenant.tenant_id, documents)
    return store


def test_pipeline_findings_carry_the_probes_atlas_and_nist() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    probe = TenantBoundaryProbe()
    findings = confirmed_findings(
        Runner(substrate, vector=_seeded_store(substrate, shared_index=True)).run(probe)
    )
    assert findings
    # the probe declares non-empty mappings, and every finding carries them
    assert probe.atlas_techniques and probe.nist_rmf
    for finding in findings:
        assert finding.owasp_llm == probe.owasp_llm
        assert finding.atlas == probe.atlas_techniques
        assert finding.nist == probe.nist_rmf


def test_erasure_findings_carry_the_nist_mapping() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    store = _seeded_store(substrate, soft_delete=True)  # soft-delete leaves residue
    report = ErasureProbe(substrate, vector=store).run(substrate.tenants[0].tenant_id)
    assert report.findings
    for finding in report.findings:
        assert finding.owasp_llm == "LLM08:2025"
        assert finding.atlas == ()  # erasure verification is a control check, not an attack
        assert finding.nist == ("MEASURE 2.7",)


def test_atlas_assignments_match_the_domain_review() -> None:
    # The per-probe ATLAS techniques were validated against the current MITRE
    # ATLAS catalog; pin the deliberate, non-obvious assignments so they cannot
    # silently regress (these IDs land in auditor evidence). rag-poisoning is a
    # poisoning technique (T0020), agent-tool-hijack a plugin compromise (T0053),
    # and lora-cross-tenant carries the membership-inference angle (T0024.000).
    assert RagPoisoningProbe.atlas_techniques == ("AML.T0020", "AML.T0024")
    assert AgentToolHijackProbe.atlas_techniques == ("AML.T0024", "AML.T0053")
    assert LoraCrossTenantProbe.atlas_techniques == ("AML.T0024", "AML.T0024.000", "AML.T0057")


def test_manual_detect_leaves_classification_at_defaults() -> None:
    # A manual pipeline.detect() (no probe classification) is byte-identical to
    # before: the multi-tenant OWASP class, no ATLAS/NIST.
    substrate = build_substrate(default_scenario(seed=2026))
    pipeline = DetectionPipeline(substrate)
    marker = next(m for m in substrate.manifest.markers if m.marker_type is MarkerType.HARD_CANARY)
    findings = pipeline.detect(
        UUID(int=999), f"a response mentioning {marker.plaintext}", Surface.VECTOR_DB
    )
    assert findings
    for finding in findings:
        assert finding.owasp_llm == "LLM08:2025"
        assert finding.atlas == ()
        assert finding.nist == ()
