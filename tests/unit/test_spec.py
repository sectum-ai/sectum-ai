"""Unit tests for the sectum_ai.spec models, hashing, and schema export."""

import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from sectum_ai.spec import (
    SCHEMA_VERSION,
    Finding,
    FindingStatus,
    GroundTruthManifest,
    Marker,
    MarkerType,
    RunMetrics,
    Severity,
    Surface,
    canonical_hash,
    json_schemas,
    to_canonical_json,
)
from sectum_ai.substrate import build_substrate, default_scenario


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


def test_built_models_are_frozen() -> None:
    # ConfigDict(frozen=True): once built, a model cannot be mutated, so a run or
    # manifest hashed into the evidence chain cannot be altered in place.
    marker = Marker(
        marker_id="mkr-1",
        marker_type=MarkerType.HARD_CANARY,
        owner_tenant_id=UUID(int=1),
        plaintext="SECTUM-CANARY-X",
    )
    with pytest.raises(ValidationError):
        marker.plaintext = "tampered"  # type: ignore[misc]  # the point: frozen rejects it


def test_marker_rejects_an_empty_plaintext() -> None:
    # plaintext has min_length=1: an empty canary would substring-match every
    # observation and confirm a spurious critical leak, so it is refused.
    with pytest.raises(ValidationError):
        Marker(
            marker_id="mkr-1",
            marker_type=MarkerType.HARD_CANARY,
            owner_tenant_id=UUID(int=1),
            plaintext="",
        )


def _finding_with_confidence(confidence: float) -> Finding:
    return Finding(
        finding_id="f-1",
        probe_id="rag-entity-bleed",
        severity=Severity.CRITICAL,
        confidence=confidence,
        status=FindingStatus.CONFIRMED,
        owner_tenant_id=UUID(int=0xB),
        observed_in_tenant_id=UUID(int=0xA),
        surface=Surface.VECTOR_DB,
    )


def test_finding_confidence_must_be_a_probability() -> None:
    # confidence is Field(ge=0.0, le=1.0): a value outside [0, 1] is rejected, so
    # a miscalibrated detector cannot emit an out-of-range probability into a
    # signed artifact.
    assert _finding_with_confidence(1.0).confidence == 1.0
    with pytest.raises(ValidationError):
        _finding_with_confidence(1.5)
    with pytest.raises(ValidationError):
        _finding_with_confidence(-0.1)


def test_canonicalizing_a_model_with_a_non_finite_float_is_refused() -> None:
    # The non-finite refusal must hold on the *model* path, not just a raw dict:
    # retrieval_pivot_rate is an unconstrained float, so an inf/NaN constructs but
    # must not yield a digest a strict third-party verifier could not reproduce.
    metrics = RunMetrics(retrieval_pivot_rate=float("inf"))
    with pytest.raises(ValueError, match="non-finite float"):
        canonical_hash(metrics)


def test_run_metrics_records_the_rpr_counts_and_interval() -> None:
    # The Retrieval-Pivot Rate carries its binomial counts and Wilson interval so
    # the interval is reproducible from the signed evidence, not just the rounded
    # rate. The interval is a 2-tuple that round-trips through the canonical form.
    metrics = RunMetrics(
        retrieval_pivot_rate=334 / 350,
        retrieval_pivot_n=350,
        retrieval_pivot_k=334,
        retrieval_pivot_rate_ci=(0.927, 0.9717),
    )
    assert metrics.retrieval_pivot_rate_ci == (0.927, 0.9717)
    dumped = metrics.model_dump(mode="json")
    # A tuple serializes to a JSON array; the counts make k / n recover the rate.
    assert dumped["retrieval_pivot_rate_ci"] == [0.927, 0.9717]
    assert dumped["retrieval_pivot_k"] / dumped["retrieval_pivot_n"] == metrics.retrieval_pivot_rate


def test_run_metrics_rpr_interval_is_part_of_the_canonical_form() -> None:
    # Changing only the confidence interval changes the digest, so the interval is
    # bound into the tamper-evident canonical hash (not silently dropped).
    base = RunMetrics(retrieval_pivot_rate=0.5, retrieval_pivot_n=4, retrieval_pivot_k=2)
    with_ci = base.model_copy(update={"retrieval_pivot_rate_ci": (0.15, 0.85)})
    assert canonical_hash(base) != canonical_hash(with_ci)
    assert canonical_hash(with_ci) == canonical_hash(with_ci)


def test_run_metrics_rejects_negative_rpr_counts() -> None:
    # The counts are Field(ge=0): a negative numerator or denominator cannot be
    # constructed into a signed artifact.
    with pytest.raises(ValidationError):
        RunMetrics(retrieval_pivot_n=-1)
    with pytest.raises(ValidationError):
        RunMetrics(retrieval_pivot_k=-1)
