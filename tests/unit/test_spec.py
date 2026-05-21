"""Unit tests for the sectum.spec models, hashing, and schema export."""

from uuid import UUID

from sectum.spec import (
    SCHEMA_VERSION,
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
