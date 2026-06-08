"""Invariant: the substrate is a pure function of the scenario seed.

The reproducibility contract (the engineering spec, section 6.5, ADR-0003): the same seed
must yield a byte-identical corpus and an identical ground-truth manifest.
"""

from sectum_ai.spec import canonical_hash
from sectum_ai.substrate import build_substrate, default_scenario


def test_same_seed_yields_identical_substrate() -> None:
    first = build_substrate(default_scenario(seed=2026))
    second = build_substrate(default_scenario(seed=2026))
    assert first == second


def test_same_seed_yields_identical_manifest_hash() -> None:
    first = build_substrate(default_scenario(seed=7))
    second = build_substrate(default_scenario(seed=7))
    assert canonical_hash(first.manifest) == canonical_hash(second.manifest)


def test_same_seed_yields_identical_corpus() -> None:
    first = build_substrate(default_scenario(seed=7))
    second = build_substrate(default_scenario(seed=7))
    assert first.documents == second.documents


def test_manifest_hash_is_stable_across_repeated_builds() -> None:
    hashes = {canonical_hash(build_substrate(default_scenario(seed=99)).manifest) for _ in range(4)}
    assert len(hashes) == 1


def test_different_seed_yields_a_different_manifest() -> None:
    one = build_substrate(default_scenario(seed=1))
    two = build_substrate(default_scenario(seed=2))
    assert canonical_hash(one.manifest) != canonical_hash(two.manifest)


def test_default_scenario_hashes_match_the_published_golden() -> None:
    # A fixed golden value turns an *accidental* change to corpus generation,
    # marker planting, or canonicalization into a test failure - the determinism
    # tests above only catch run-to-run drift, not a shift in the output itself.
    # The reproducibility contract (spec section 6.5) makes these stable across
    # machines and Python versions. Update these literals only with a deliberate
    # substrate change.
    substrate = build_substrate(default_scenario(seed=2026))
    assert substrate.manifest.scenario_hash == (
        "de5b86972c796fb767c0d2c558773becb2f0fb59b82331115159eba63b020afb"
    )
    assert canonical_hash(substrate.manifest) == (
        "d8668caa922956db77189ce1c0a1386620bfcc25eda767ae5f9188a1853fa514"
    )
