"""Property-based tests (Hypothesis) for marker generation and canonical hashing.

These generalize the fixed-seed invariants (the engineering spec, section 15):
for *any* seed the substrate is reproducible and its markers are unique, and the
canonical hash is deterministic and content-sensitive. A small two-tenant
scenario keeps each generated example fast.
"""

from uuid import UUID

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from sectum.spec import (
    Scenario,
    SharedEntity,
    SyntheticTenantSpec,
    canonical_hash,
    to_canonical_json,
)
from sectum.substrate import build_substrate

_seeds = st.integers(min_value=0, max_value=2**31 - 1)


def _scenario(seed: int) -> Scenario:
    return Scenario(
        scenario_id="property",
        seed=seed,
        tenants=(
            SyntheticTenantSpec(
                tenant_id=UUID(int=1), display_name="Acme", industry="robotics", corpus_size=24
            ),
            SyntheticTenantSpec(
                tenant_id=UUID(int=2), display_name="Globex", industry="finance", corpus_size=24
            ),
        ),
        shared_entities=(SharedEntity(kind="person", value="Maria Chen"),),
    )


@settings(max_examples=40, deadline=None)
@given(seed=_seeds)
def test_substrate_is_reproducible_for_any_seed(seed: int) -> None:
    first = build_substrate(_scenario(seed))
    second = build_substrate(_scenario(seed))
    assert canonical_hash(first.manifest) == canonical_hash(second.manifest)


@settings(max_examples=40, deadline=None)
@given(seed=_seeds)
def test_markers_are_unique_for_any_seed(seed: int) -> None:
    markers = build_substrate(_scenario(seed)).manifest.markers
    ids = [marker.marker_id for marker in markers]
    plaintexts = [marker.plaintext for marker in markers]
    assert len(set(ids)) == len(ids)
    assert len(set(plaintexts)) == len(plaintexts)


@settings(max_examples=50, deadline=None)
@given(left=_seeds, right=_seeds)
def test_distinct_seeds_yield_distinct_scenario_hashes(left: int, right: int) -> None:
    assume(left != right)
    assert canonical_hash(_scenario(left)) != canonical_hash(_scenario(right))


@settings(max_examples=50, deadline=None)
@given(seed=_seeds)
def test_canonical_json_is_stable(seed: int) -> None:
    scenario = _scenario(seed)
    assert to_canonical_json(scenario) == to_canonical_json(scenario)
