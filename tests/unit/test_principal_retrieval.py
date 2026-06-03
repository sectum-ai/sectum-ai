"""User-level (principal) isolation for the retrieval-surface probes (ADR-0006/0008).

With the vector adapter user-aware, the retrieval probes (Classes 2, 3, 6, 10)
verify isolation at the user granularity too. Against a store scoped by tenant
alone, one user's benign query - or planted poison - surfaces a sibling user's
content; a user-scoped store denies it. Each probe runs end to end through the
runner, which threads the actor's user into every vector call.
"""

from uuid import UUID

import pytest
from sectum_ai.adapters import FakeVectorStore
from sectum_ai.probes import (
    EmbeddingInversionProbe,
    IkeaExtractionProbe,
    Probe,
    RagEntityBleedProbe,
    RagPoisoningProbe,
    confirmed_findings,
)
from sectum_ai.runner import Runner, retrieval_pivot_rate
from sectum_ai.spec import (
    Finding,
    Scenario,
    SharedEntity,
    Substrate,
    SyntheticTenantSpec,
    SyntheticUserSpec,
)
from sectum_ai.substrate import build_substrate

_TENANT = UUID(int=1)
_USER_A = UUID(int=0xA)
_USER_B = UUID(int=0xB)

# The retrieval probes that confirm a foreign canary via a vector.query (Class 3
# plants a poison first). Probes are stateless, so reusing one instance across
# the parametrized cases is safe.
_QUERY_PROBES: tuple[Probe, ...] = (
    RagPoisoningProbe(),
    EmbeddingInversionProbe(),
    IkeaExtractionProbe(),
)


def _users_substrate() -> Substrate:
    scenario = Scenario(
        scenario_id="retrieval-users",
        seed=7,
        tenants=(
            SyntheticTenantSpec(
                tenant_id=_TENANT,
                display_name="Acme",
                industry="robotics",
                corpus_size=24,
                users=(
                    SyntheticUserSpec(user_id=_USER_A, display_name="Alice"),
                    SyntheticUserSpec(user_id=_USER_B, display_name="Bob"),
                ),
            ),
        ),
        shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
    )
    return build_substrate(scenario)


def _seeded(substrate: Substrate, *, user_scoped: bool) -> FakeVectorStore:
    store = FakeVectorStore(user_scoped=user_scoped)
    for tenant in substrate.tenants:
        documents = [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id]
        store.upsert(tenant.tenant_id, documents)
    return store


def _all_cross_user(findings: list[Finding]) -> bool:
    return all(
        finding.owner_user_id is not None and finding.owner_user_id != finding.observed_in_user_id
        for finding in findings
    )


def test_flagship_entity_bleed_leaks_across_users_on_a_tenant_only_store() -> None:
    # Class 2 (flagship): a tenant-scoped store serves one user another user's
    # pivot document, so a benign shared-entity query pivots across the user
    # boundary - a non-zero Retrieval-Pivot Rate.
    substrate = _users_substrate()
    store = _seeded(substrate, user_scoped=False)
    results = Runner(substrate, vector=store).run_per_step(RagEntityBleedProbe())
    assert retrieval_pivot_rate(results) > 0.0
    confirmed = [finding for _, findings in results for finding in confirmed_findings(findings)]
    assert confirmed
    assert _all_cross_user(confirmed)


def test_flagship_entity_bleed_is_contained_by_a_user_scoped_store() -> None:
    substrate = _users_substrate()
    store = _seeded(substrate, user_scoped=True)
    results = Runner(substrate, vector=store).run_per_step(RagEntityBleedProbe())
    assert retrieval_pivot_rate(results) == 0.0


@pytest.mark.parametrize("probe", _QUERY_PROBES, ids=lambda probe: probe.id)
def test_retrieval_probe_leaks_across_users_on_a_tenant_only_store(probe: Probe) -> None:
    substrate = _users_substrate()
    store = _seeded(substrate, user_scoped=False)
    findings = confirmed_findings(Runner(substrate, vector=store).run(probe))
    assert findings
    assert _all_cross_user(findings)


@pytest.mark.parametrize("probe", _QUERY_PROBES, ids=lambda probe: probe.id)
def test_retrieval_probe_is_contained_by_a_user_scoped_store(probe: Probe) -> None:
    substrate = _users_substrate()
    store = _seeded(substrate, user_scoped=True)
    assert confirmed_findings(Runner(substrate, vector=store).run(probe)) == []
