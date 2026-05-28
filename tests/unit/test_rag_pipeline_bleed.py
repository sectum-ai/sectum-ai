"""Tests for the Class 2 RAG-pipeline-end entity-bleed probe."""

from sectum.adapters import FakeRAGPipeline
from sectum.adapters.base import Capability
from sectum.probes import RagPipelineBleedProbe, confirmed_findings
from sectum.runner import Runner
from sectum.spec import Substrate
from sectum.substrate import build_substrate, default_scenario


def _seeded_rag(substrate: Substrate, *, shared_index: bool) -> FakeRAGPipeline:
    rag = FakeRAGPipeline(shared_index=shared_index)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        rag.index(tenant.tenant_id, documents)
    return rag


def test_shared_index_rag_pipeline_leaks_across_tenants() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    rag = _seeded_rag(substrate, shared_index=True)
    findings = confirmed_findings(Runner(substrate, rag=rag).run(RagPipelineBleedProbe()))
    assert findings
    assert all(f.owner_tenant_id != f.observed_in_tenant_id for f in findings)


def test_isolated_rag_pipeline_has_no_entity_bleed() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    rag = _seeded_rag(substrate, shared_index=False)
    findings = Runner(substrate, rag=rag).run(RagPipelineBleedProbe())
    assert confirmed_findings(findings) == []


def test_probe_plans_one_rag_ask_per_principal_per_shared_entity() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    steps = RagPipelineBleedProbe().plan(substrate)
    assert steps
    assert all(step.action == "rag.ask" for step in steps)
    expected = len(substrate.scenario.shared_entities) * len(substrate.principals())
    assert len(steps) == expected


def test_probe_findings_carry_the_rag_pipeline_surface() -> None:
    substrate = build_substrate(default_scenario(seed=2026))
    rag = _seeded_rag(substrate, shared_index=True)
    findings = confirmed_findings(Runner(substrate, rag=rag).run(RagPipelineBleedProbe()))
    assert findings
    assert all(finding.surface.value == "rag_pipeline" for finding in findings)


def test_fake_rag_pipeline_default_reports_per_tenant_namespace() -> None:
    rag = FakeRAGPipeline()
    assert rag.supports(Capability.PER_TENANT_NAMESPACE)
    assert not rag.supports(Capability.SHARED_INDEX)


def test_fake_rag_pipeline_shared_index_reports_the_leak_capability() -> None:
    rag = FakeRAGPipeline(shared_index=True)
    assert rag.supports(Capability.SHARED_INDEX)
    assert not rag.supports(Capability.PER_TENANT_NAMESPACE)
