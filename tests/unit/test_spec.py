"""Unit tests for the sectum.spec models, hashing, and schema export."""

import json
from uuid import UUID

import pytest

from sectum.spec import (
    SCHEMA_VERSION,
    GroundTruthManifest,
    Marker,
    MarkerType,
    canonical_hash,
    json_schemas,
    to_canonical_json,
)
from sectum.substrate import build_substrate, default_scenario


def test_canonical_hash_is_deterministic() -> None:
    scenario = default_scenario(seed=10)
    assert canonical_hash(scenario) == canonical_hash(scenario)


def test_canonical_hash_changes_with_content() -> None:
    assert canonical_hash(default_scenario(seed=1)) != canonical_hash(default_scenario(seed=2))


def test_canonical_hash_serializes_every_field_including_none() -> None:
    """ADR-0007: canonical hashing is total - an optional field left None is
    serialized as null and covered by the digest, never omitted. Adopting
    exclude_none would change every digest and break verification of every
    previously issued evidence pack.
    """
    marker = Marker(
        marker_id="mkr-00001",
        marker_type=MarkerType.HARD_CANARY,
        owner_tenant_id=UUID(int=1),
        plaintext="canary",
    )
    assert b'"owner_user_id":null' in to_canonical_json(marker)
    populated = marker.model_copy(update={"owner_user_id": UUID(int=2)})
    assert canonical_hash(marker) != canonical_hash(populated)


def test_json_schemas_cover_the_core_models() -> None:
    schemas = json_schemas()
    for name in ("Scenario", "Marker", "GroundTruthManifest", "Finding", "EvidencePack"):
        assert schemas[name]["type"] == "object"


def test_aggregate_models_carry_the_schema_version() -> None:
    manifest = build_substrate(default_scenario(seed=3)).manifest
    assert manifest.schema_version == SCHEMA_VERSION


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_canonicalizing_a_non_finite_float_is_refused(non_finite: float) -> None:
    """A NaN/Infinity has no valid JSON literal (RFC 8259) and every NaN
    collapses to the same token, so canonicalization must refuse it rather than
    emit a digest a strict third-party verifier could not reproduce. Guards the
    ``allow_nan=False`` contract in ``to_canonical_json`` (and via it
    ``canonical_hash``), which the evidence chain relies on.
    """
    with pytest.raises(ValueError, match="non-finite float"):
        to_canonical_json({"gap_ms": non_finite})
    with pytest.raises(ValueError, match="non-finite float"):
        canonical_hash({"gap_ms": non_finite})


def test_canonicalizing_a_non_json_native_value_is_refused() -> None:
    """A raw dict/list (not a BaseModel, which json-normalizes first via
    model_dump) can carry a value json cannot serialize - a UUID or bytes.
    to_canonical_json must surface a clear, typed canonicalization failure, not
    leak json's bare TypeError.
    """
    with pytest.raises(TypeError, match="non-JSON-native value"):
        to_canonical_json({"owner": UUID(int=0xA)})
    with pytest.raises(TypeError, match="non-JSON-native value"):
        canonical_hash([b"raw-bytes"])


def test_marker_rejects_an_unknown_field_on_json_load() -> None:
    # SectumModel sets extra="forbid": loading JSON that carries a smuggled unknown
    # field must fail, so a tampered evidence artifact is rejected at the load path
    # (the CLI loads EvidencePack / GroundTruthManifest via model_validate_json),
    # not silently accepted. Pins the guard against a future extra="allow"/"ignore"
    # regression. (pydantic's ValidationError is a ValueError.)
    data = json.loads(
        Marker(
            marker_id="m-1",
            marker_type=MarkerType.HARD_CANARY,
            owner_tenant_id=UUID(int=1),
            plaintext="canary",
        ).model_dump_json()
    )
    Marker.model_validate_json(json.dumps(data))  # the clean payload round-trips
    with pytest.raises(ValueError, match="smuggled"):
        Marker.model_validate_json(json.dumps({**data, "smuggled": "x"}))


def test_ground_truth_manifest_rejects_an_unknown_field_on_json_load() -> None:
    # The evidence chain loads the manifest via model_validate_json in verify_pack;
    # the same shared extra="forbid" base guard (which EvidencePack inherits too)
    # rejects a smuggled field.
    data = json.loads(
        GroundTruthManifest(manifest_id="m", scenario_hash="h", markers=()).model_dump_json()
    )
    GroundTruthManifest.model_validate_json(json.dumps(data))
    with pytest.raises(ValueError, match="smuggled"):
        GroundTruthManifest.model_validate_json(json.dumps({**data, "smuggled": "x"}))
