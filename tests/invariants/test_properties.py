"""Property-based tests (Hypothesis) for marker generation and canonical hashing.

These generalize the fixed-seed invariants (the engineering spec, section 15):
for *any* seed the substrate is reproducible and its markers are unique, and the
canonical hash is deterministic and content-sensitive. A small two-tenant
scenario keeps each generated example fast.
"""

from uuid import UUID

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from sectum_ai.adapters import (
    FakeBackup,
    FakeCache,
    FakeEvalSet,
    FakeMemory,
    FakeModel,
    FakeObservability,
    FakeSearchIndex,
    FakeVectorStore,
)
from sectum_ai.probes import ERASURE_SURFACES, ErasureProbe
from sectum_ai.spec import (
    CoverageVerdict,
    MarkerType,
    Scenario,
    SharedEntity,
    Substrate,
    Surface,
    SyntheticTenantSpec,
    canonical_hash,
    to_canonical_json,
)
from sectum_ai.substrate import build_substrate

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


# --- Anti-over-claim invariant: an unscanned erasure surface is never ERASED --


def _all_surfaces_seeded_probe(substrate: Substrate) -> ErasureProbe:
    """An ErasureProbe with every surface configured + seeded with a hard-deleting
    backend, so absent a scope every surface WOULD verify as ERASED.

    That is what makes the anti-over-claim property non-trivial: the only thing
    that can keep an out-of-scope surface off the ERASED verdict is the coverage
    guarantee itself, not a missing/empty backend.
    """
    store = FakeVectorStore(soft_delete=False)
    for tenant in substrate.tenants:
        store.upsert(
            tenant.tenant_id,
            [doc for doc in substrate.documents if doc.tenant_id == tenant.tenant_id],
        )
    obs = FakeObservability(soft_delete=False)
    memory = FakeMemory(soft_delete=False)
    cache = FakeCache(soft_delete=False)
    model = FakeModel(soft_delete=False)
    search = FakeSearchIndex(soft_delete=False)
    eval_set = FakeEvalSet(soft_delete=False)
    backup = FakeBackup(soft_delete=False)
    for marker in substrate.manifest.markers:
        if marker.marker_type is not MarkerType.HARD_CANARY:
            continue
        owner = marker.owner_tenant_id
        obs.record(owner, "sectum-ai-erasure", f"trace {marker.plaintext}")
        memory.remember(owner, f"memory {marker.plaintext}")
        cache.set(owner, f"k-{marker.marker_id}", f"cached {marker.plaintext}")
        model.train_adapter(owner, [f"sample {marker.plaintext}"])
        search.index(owner, f"index {marker.plaintext}")
        eval_set.add(owner, f"eval {marker.plaintext}")
        backup.add(owner, f"backup {marker.plaintext}")
    return ErasureProbe(
        substrate,
        vector=store,
        observability=obs,
        memory=memory,
        cache=cache,
        model=model,
        search_index=search,
        eval_set=eval_set,
        backup=backup,
    )


# Non-empty subsets of the erasure surfaces - any scope an engagement could pick.
_surface_scopes = st.lists(
    st.sampled_from(ERASURE_SURFACES), min_size=1, max_size=len(ERASURE_SURFACES), unique=True
)


@settings(max_examples=60, deadline=None)
@given(scope=_surface_scopes)
def test_an_unscanned_surface_is_never_erased_for_any_scope(scope: list[Surface]) -> None:
    # The anti-over-claim guarantee, over *every* scope: a surface that is not in
    # the scope is not scanned, so it can only ever be NOT_COVERED in the coverage
    # block - never ERASED, even though its backend would have verified clean had
    # it been scanned. This is the property that makes a snapshot attestation
    # incapable of implying coverage it does not have.
    substrate = build_substrate(default_scenario_for_property())
    report = _all_surfaces_seeded_probe(substrate).run(substrate.tenants[0].tenant_id, scope=scope)
    coverage = report.coverage()
    in_scope = set(scope)
    # The only verdict an out-of-scope (unscanned) surface may hold. Asserting set
    # membership states the guarantee directly - and, because ERASED is provably
    # not in this set, an unscanned surface can never be ERASED.
    allowed_out_of_scope = {CoverageVerdict.NOT_COVERED}
    assert CoverageVerdict.ERASED not in allowed_out_of_scope
    for surface, verdict in coverage.items():
        if surface not in in_scope:
            assert verdict in allowed_out_of_scope
        else:
            # A scanned, hard-deleting surface verifies as ERASED (the property is
            # non-vacuous: the ERASED verdict really is reachable when scanned).
            assert verdict is CoverageVerdict.ERASED


def default_scenario_for_property() -> Scenario:
    """The 4-tenant default scenario at a small corpus for a fast erasure run."""
    from sectum_ai.substrate import default_scenario

    base = default_scenario(seed=2026)
    return base.model_copy(
        update={
            "tenants": tuple(t.model_copy(update={"corpus_size": 12}) for t in base.tenants),
        }
    )
