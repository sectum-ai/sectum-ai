"""Unit tests for the sectum.spec models, hashing, and schema export."""

from sectum.spec import SCHEMA_VERSION, canonical_hash, json_schemas
from sectum.substrate import build_substrate, default_scenario


def test_canonical_hash_is_deterministic() -> None:
    scenario = default_scenario(seed=10)
    assert canonical_hash(scenario) == canonical_hash(scenario)


def test_canonical_hash_changes_with_content() -> None:
    assert canonical_hash(default_scenario(seed=1)) != canonical_hash(default_scenario(seed=2))


def test_json_schemas_cover_the_core_models() -> None:
    schemas = json_schemas()
    for name in ("Scenario", "Marker", "GroundTruthManifest", "Finding", "EvidencePack"):
        assert schemas[name]["type"] == "object"


def test_aggregate_models_carry_the_schema_version() -> None:
    manifest = build_substrate(default_scenario(seed=3)).manifest
    assert manifest.schema_version == SCHEMA_VERSION
