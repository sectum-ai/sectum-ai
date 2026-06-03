"""Tests for canonical serialization and hashing (the spec §6.5 / §8.2; ADR-0007, ADR-0021).

These pin the canonical-form contract the whole evidence chain rests on: sorted
keys, deterministic finite-float serialization (no lossy rounding), and refusal
of values that have no valid, injective JSON form (non-finite floats, non-JSON
types).
"""

import math

import pytest
from sectum_ai.spec import canonical_hash, sha256_hex, to_canonical_json


def test_key_order_does_not_change_the_hash() -> None:
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_a_finite_float_is_deterministic_across_constructions() -> None:
    # CPython's shortest-round-trip float repr (what json.dumps emits) is
    # deterministic, so a float reached by different arithmetic but equal in value
    # canonicalizes identically - no rounding is needed (ADR-0021). 0.1 + 0.2 is
    # exactly 0.30000000000000004 in IEEE-754 double.
    assert (0.1 + 0.2) == 0.30000000000000004
    assert canonical_hash({"x": 0.1 + 0.2}) == canonical_hash({"x": 0.30000000000000004})


def test_distinct_floats_stay_distinct() -> None:
    # The canonical form is not lossily rounded, so a genuine metric change is
    # never masked by hash collision - the opposite failure mode to rounding.
    assert canonical_hash({"x": 0.62}) != canonical_hash({"x": 0.6200001})


def test_an_integer_valued_float_serializes_as_a_float() -> None:
    # 1.0 -> "1.0" (a float), distinct from int 1 -> "1". Model field types are
    # fixed, so a field never flips between the two; pin the encoding regardless.
    assert to_canonical_json({"x": 1.0}) == b'{"x":1.0}'
    assert to_canonical_json({"x": 1}) == b'{"x":1}'


def test_nan_is_refused() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        to_canonical_json({"x": math.nan})


def test_positive_and_negative_infinity_are_refused() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        to_canonical_json({"x": math.inf})
    with pytest.raises(ValueError, match="non-finite"):
        to_canonical_json({"x": -math.inf})


def test_a_non_json_native_value_is_a_typed_error() -> None:
    with pytest.raises(TypeError, match="non-JSON-native"):
        to_canonical_json({"x": {1, 2, 3}})  # a set has no JSON form


def test_sha256_hex_is_the_digest_of_the_canonical_bytes() -> None:
    obj = {"b": 2, "a": 1}
    assert canonical_hash(obj) == sha256_hex(to_canonical_json(obj))
