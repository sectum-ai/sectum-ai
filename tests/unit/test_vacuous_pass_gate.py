"""A probe plans nothing when the substrate offers it no cross-principal target.

Recording a probe that emitted steps but could never surface a cross-principal leak grades
its class a vacuous PASS (``docs/scorecard.md`` rule 1: a grade must never imply a check
the stack was never asked to perform). Round 8 gated three planting probes ad hoc and
missed the rest; the fix is a shared predicate (``detection.cross_principal_observers``),
so this pins the whole family at the plan level rather than one integration test.

Every one of these probes plants or queries per marker or shared entity and iterates
principals. On a substrate where no marker is foreign to any principal, none of them has a
target, so each must plan zero steps - and its class then reads ``NOT_COVERED`` rather than
``PASS``. The complement (a real cross-principal target still produces steps) is pinned by
each probe's own ``test_probe_plans_...`` against the stock scenario.
"""

from typing import Any, cast
from uuid import UUID

import pytest

import sectum_ai.probes as probes
from sectum_ai.probes import Probe
from sectum_ai.spec import Substrate, SyntheticUserSpec
from sectum_ai.substrate import build_substrate, default_scenario


def _plannable_probes() -> list[Probe]:
    """Every probe in the registry that plans steps - enumerated so a future one is covered.

    Hardcoding the list is what let round 8 gate three probes and miss the rest, so this
    guard is over the registry itself: a probe added without the cross-principal gate fails
    here rather than shipping a vacuous PASS for its class.
    """
    found: list[Probe] = []
    for name in probes.__all__:
        obj = getattr(probes, name)
        if isinstance(obj, type) and getattr(obj, "id", None) and hasattr(obj, "plan"):
            try:
                found.append(cast(Any, obj)())
            except TypeError:
                continue  # a probe needing constructor args is covered by its own suite
    return found


def _starved_substrate() -> Substrate:
    """A substrate with real principals but nothing foreign to any of them.

    One tenant with two users - three principals, so this is not the trivial
    single-principal case - and every marker demoted to tenant level, which is foreign to
    no user within the tenant (ADR-0006). The corpus documents are untouched, so the
    probes still find markers to reason about; they are simply owned by nobody foreign.
    """
    scenario = default_scenario(seed=2026)
    users = (
        SyntheticUserSpec(user_id=UUID(int=0x101), display_name="A"),
        SyntheticUserSpec(user_id=UUID(int=0x102), display_name="B"),
    )
    substrate = build_substrate(
        scenario.model_copy(
            update={"tenants": (scenario.tenants[0].model_copy(update={"users": users}),)}
        )
    )
    tenant_level = tuple(
        marker.model_copy(update={"owner_user_id": None}) for marker in substrate.manifest.markers
    )
    return substrate.model_copy(
        update={"manifest": substrate.manifest.model_copy(update={"markers": tenant_level})}
    )


@pytest.mark.parametrize("probe", _plannable_probes(), ids=lambda p: p.id)
def test_a_probe_with_no_cross_principal_target_plans_nothing(probe: Probe) -> None:
    assert probe.plan(_starved_substrate()) == []
