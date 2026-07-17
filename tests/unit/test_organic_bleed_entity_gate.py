"""An organic-bleed probe issues no query for a shared entity absent from the corpus.

The Class 2/10 organic-bleed probes (``rag-entity-bleed``, ``rag-pipeline-bleed``,
``ikea-extraction``) query per shared entity and gate each query on
``cross_principal_observers`` of ``markers_naming_entity(substrate, entity)`` - the canaries
planted in the documents that actually name the entity. A shared entity that no corpus
document mentions carries no canary, so a query for it can surface nothing foreign; issuing
one anyway lands in the RPR / extraction-efficiency denominator without ever producing a
confirmed finding, understating the leak.

The corpus plants one pivot per marker, its entity chosen round-robin (``substrate/corpus``),
so a scenario declaring more shared entities than markers per tenant leaves the surplus
entities named nowhere. This pins that the probes route their gate through the entity-specific
``markers_naming_entity`` and not the manifest-wide marker set: the two agree on every
scenario with no surplus entity, so nothing else catches the swap. Each case asserts its own
premise - a corpus-absent entity exists, and the named entities still produce queries - so a
future change to the marker count cannot make it vacuous.
"""

from typing import Any, cast
from uuid import UUID

import pytest

from sectum_ai.probes import (
    IkeaExtractionProbe,
    Probe,
    RagEntityBleedProbe,
    RagPipelineBleedProbe,
)
from sectum_ai.probes.detection import markers_naming_entity
from sectum_ai.spec import Scenario, SharedEntity, Substrate, SyntheticTenantSpec
from sectum_ai.substrate import build_substrate

_ORGANIC_BLEED_PROBES = (RagEntityBleedProbe, RagPipelineBleedProbe, IkeaExtractionProbe)


def _surplus_entity_substrate() -> Substrate:
    """Two tenants sharing more entities than either plants markers for.

    Ten shared entities against six markers per tenant, so the last four entities are
    assigned no pivot document and are named nowhere in the corpus. Two tenants (not one) so
    that a named entity is still foreign to the other tenant and does produce queries.
    """
    entities = tuple(
        SharedEntity(kind="person", value=f"Surplus-Entity-{index:02d}") for index in range(10)
    )
    scenario = Scenario(
        scenario_id="surplus-entities",
        seed=11,
        tenants=(
            SyntheticTenantSpec(
                tenant_id=UUID(int=1), display_name="Acme", industry="robotics", corpus_size=24
            ),
            SyntheticTenantSpec(
                tenant_id=UUID(int=2), display_name="Beta", industry="finance", corpus_size=24
            ),
        ),
        shared_entities=entities,
    )
    return build_substrate(scenario)


@pytest.mark.parametrize("probe_cls", _ORGANIC_BLEED_PROBES, ids=lambda c: c.id)
def test_no_query_targets_an_entity_absent_from_the_corpus(probe_cls: type[Probe]) -> None:
    substrate = _surplus_entity_substrate()
    absent = [
        entity.value
        for entity in substrate.scenario.shared_entities
        if not markers_naming_entity(substrate, entity)
    ]
    assert absent  # premise: some shared entity is named in no document, else this is vacuous

    probe = cast(Any, probe_cls)()
    steps = probe.plan(substrate)
    assert steps  # the named entities still produce queries (not a probe that plans nothing)
    for step in steps:
        query = step.payload["query"]
        assert not any(value in query for value in absent), (
            f"{probe.id} queried a corpus-absent entity: {query!r}"
        )
