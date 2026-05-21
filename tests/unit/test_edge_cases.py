"""Edge-case coverage: a too-small corpus and the empty-marker judge verdict."""

from uuid import UUID

import pytest

from sectum.probes import FakeJudge
from sectum.spec import (
    ConfigError,
    Marker,
    MarkerType,
    Scenario,
    SharedEntity,
    SyntheticTenantSpec,
)
from sectum.substrate import build_substrate


def test_corpus_smaller_than_the_marker_count_raises() -> None:
    # corpus_size 3 < markers-per-tenant (6): every marker needs its own pivot doc.
    scenario = Scenario(
        scenario_id="tiny",
        seed=1,
        tenants=(
            SyntheticTenantSpec(
                tenant_id=UUID(int=1), display_name="Acme", industry="robotics", corpus_size=3
            ),
        ),
        shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
    )
    with pytest.raises(ConfigError):
        build_substrate(scenario)


def test_corpus_without_shared_entities_plants_no_pivots() -> None:
    # No shared entities means no pivot documents, so no marker is planted in a body.
    scenario = Scenario(
        scenario_id="no-shared",
        seed=1,
        tenants=(
            SyntheticTenantSpec(
                tenant_id=UUID(int=1), display_name="Acme", industry="robotics", corpus_size=24
            ),
        ),
        shared_entities=(),
    )
    substrate = build_substrate(scenario)
    assert all(not document.marker_ids for document in substrate.documents)


def test_fake_judge_rejects_an_empty_marker() -> None:
    marker = Marker(
        marker_id="m-1",
        marker_type=MarkerType.ENTITY_CANARY,
        owner_tenant_id=UUID(int=1),
        plaintext="",
    )
    verdict = FakeJudge().judge("any observed text", marker)
    assert verdict.leak is False
