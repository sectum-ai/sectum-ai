"""Tests for the Class 2 RAG-pipeline-end entity-bleed probe."""

from sectum_ai.adapters import FakeRAGPipeline
from sectum_ai.adapters.base import Capability
from sectum_ai.probes import RagPipelineBleedProbe, confirmed_findings
from sectum_ai.runner import Runner
from sectum_ai.spec import Substrate
from sectum_ai.substrate import build_substrate, default_scenario


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


def test_a_tenant_isolated_pipeline_with_users_is_not_a_cross_user_leak() -> None:
    # `RAGPipelineAdapter.ask(tenant, query)` carries no user, so a user-level step
    # ran as the tenant and was judged as the user: on a tenant-isolated pipeline
    # every sibling user's marker in the tenant's own answer confirmed as a
    # CRITICAL cross-user leak (12 of them on two tenants of two users). The probe
    # plans from tenants only (ADR-0006: user-aware adapters are the next step).
    from uuid import UUID

    from sectum_ai.spec import Scenario, SharedEntity, SyntheticTenantSpec, SyntheticUserSpec

    tenants = tuple(
        SyntheticTenantSpec(
            tenant_id=UUID(int=n),
            display_name=f"T{n}",
            industry="robotics",
            corpus_size=24,
            users=(
                SyntheticUserSpec(user_id=UUID(int=10 * n + 1), display_name="a"),
                SyntheticUserSpec(user_id=UUID(int=10 * n + 2), display_name="b"),
            ),
        )
        for n in (1, 2)
    )
    substrate = build_substrate(
        Scenario(
            scenario_id="rag-users",
            seed=3,
            tenants=tenants,
            shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
        )
    )
    steps = RagPipelineBleedProbe().plan(substrate)
    assert steps and all(step.actor_user_id is None for step in steps)
    rag = _seeded_rag(substrate, shared_index=False)
    assert confirmed_findings(Runner(substrate, rag=rag).run(RagPipelineBleedProbe())) == []
