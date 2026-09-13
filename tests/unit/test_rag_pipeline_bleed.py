"""Tests for the Class 2 RAG-pipeline-end entity-bleed probe."""

from uuid import UUID

from sectum_ai.adapters import FakeRAGPipeline
from sectum_ai.adapters.base import Capability, RagAnswer
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
    # CRITICAL cross-user leak (12 of them on two tenants of two users). The runner
    # drops those steps and counts them (ADR-0006/0008): a pass that says the user
    # boundary was not tested, never that it held.
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
    # Planned, then DROPPED by the runner - not silently unplanned. Unplanned, the
    # runner's drop path never fired, so `user_steps_dropped` stayed empty and the
    # pass said nothing about the boundary it could not test.
    assert any(step.actor_user_id is not None for step in steps), steps

    probe = RagPipelineBleedProbe()
    runner = Runner(substrate, rag=_seeded_rag(substrate, shared_index=False))
    results = runner.run_per_step(probe)
    assert results and all(step.actor_user_id is None for step, _ in results)
    assert confirmed_findings([f for _, findings in results for f in findings]) == []
    assert runner.dropped_user_steps.get(probe.id, 0) > 0


def test_a_leak_in_the_retrieved_context_is_a_leak_however_the_model_words_it() -> None:
    # `_rag_ask` scanned `answer` alone and discarded `RagAnswer.retrieved`, while
    # its sibling `_vector_query` has always scanned every hit. That made the
    # Class 2 verdict a property of the MODEL'S WORDING: a shared-index retriever
    # that hands another tenant's documents to the model - the exact pivot this
    # probe exists to detect - graded PASS at 0.0% RPR whenever the model
    # paraphrased instead of quoting the canary, stamped `rag_pipeline: LIVE`.
    #
    # It hid because `FakeRAGPipeline.ask` returns the retrieved chunks AS the
    # answer, so every test and the demo exercise the one shape where the two
    # agree. A real pipeline (`LangChainRAGPipeline`) puts the LLM's prose in
    # `answer` and the documents in `retrieved`; they are distinct fields.
    substrate = build_substrate(default_scenario(seed=2026))

    class _Paraphrases(FakeRAGPipeline):
        """Retrieves exactly as its base does; never quotes what it retrieved."""

        def ask(self, tenant: UUID, query: str) -> RagAnswer:
            retrieved = super().ask(tenant, query).retrieved
            return RagAnswer(answer="Here is a summary of your account.", retrieved=retrieved)

    def _confirmed(*, shared_index: bool) -> int:
        rag = _Paraphrases(shared_index=shared_index)
        for tenant in substrate.tenants:
            rag.index(
                tenant.tenant_id,
                [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id],
            )
        return len(confirmed_findings(Runner(substrate, rag=rag).run(RagPipelineBleedProbe())))

    # A foreign document reaching the model's context IS the retrieval-boundary
    # failure; whether the model repeats it is the model's disposition, and
    # resting a signed verdict on that makes the measurement non-deterministic.
    assert _confirmed(shared_index=True) > 0
    # ...and the direction that matters more: a tenant-scoped retriever whose
    # model also paraphrases must still be clean, or the fix trades a false pass
    # for a false alarm on the flagship class.
    assert _confirmed(shared_index=False) == 0
