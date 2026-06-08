"""Tests for `sectum-ai calibrate`, the calibration harness, and per-model presets.

All tests run offline: the calibration harness is driven by the deterministic
:class:`FakeEmbeddingProvider` (and a tiny synthetic embedder), never a real
provider, so no network is needed. A live `st:`/`openai:` calibration is exercised
separately behind the install/credential gates those providers already enforce.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sectum_ai.cli.app import app
from sectum_ai.config import (
    DetectionConfig,
    EmbedderConfig,
    SectumConfig,
    build_detection_providers,
    embedder_model_name,
    resolve_semantic_threshold_config,
)
from sectum_ai.probes import (
    DEFAULT_SEMANTIC_THRESHOLD,
    MODEL_THRESHOLDS,
    CalibrationResult,
    DetectionPipeline,
    FakeEmbeddingProvider,
    calibrate_threshold,
    resolve_semantic_threshold,
)
from sectum_ai.probes.calibrate import build_calibration_set
from sectum_ai.spec import MarkerType, Substrate
from sectum_ai.substrate import build_substrate, default_scenario

_runner = CliRunner()


def _substrate(seed: int = 7) -> Substrate:
    return build_substrate(default_scenario(seed=seed))


# --- the calibration harness ------------------------------------------------


def test_labeled_set_has_positives_and_negatives() -> None:
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate, FakeEmbeddingProvider())
    examples = build_calibration_set(substrate, pipeline)
    positives = [example for example in examples if example.is_positive]
    negatives = [example for example in examples if not example.is_positive]
    assert positives, "must build at least one genuine cross-tenant leak positive"
    assert negatives, "must build same-tenant / unrelated negatives"
    # Every score is a valid cosine in [0, 1] (the gate value).
    for example in examples:
        assert 0.0 <= example.similarity <= 1.0


def test_same_tenant_examples_are_negatives_below_the_recommendation() -> None:
    # The entity in its OWNER's own session is not a cross-tenant leak of THAT
    # entity, so it is a negative. It still scores non-zero against the other
    # tenants' "Project ..." entities (the prefix overlap) - exactly the near-miss
    # pressure the gate must resist - so the real invariant is that it stays a
    # negative and is never admitted by the recommendation, not that it is 0.0.
    substrate = _substrate()
    result = calibrate_threshold(substrate, model_name="fake", embedder=FakeEmbeddingProvider())
    same_tenant = [
        example for example in result.examples if example.label.startswith("same-tenant")
    ]
    assert same_tenant
    assert all(not example.is_positive for example in same_tenant)
    assert all(example.similarity < result.recommended_threshold for example in same_tenant)


def test_recommendation_admits_no_negative() -> None:
    # The zero-false-positive property is non-negotiable: the recommended
    # threshold must classify every negative below it.
    substrate = _substrate()
    result = calibrate_threshold(substrate, model_name="fake", embedder=FakeEmbeddingProvider())
    threshold = result.recommended_threshold
    for example in result.examples:
        if not example.is_positive:
            assert example.similarity < threshold, (
                f"negative {example.label!r} ({example.similarity}) would be admitted "
                f"by the recommended threshold {threshold}"
            )


def test_recommended_score_is_zero_fp_and_max_f1() -> None:
    substrate = _substrate()
    result = calibrate_threshold(substrate, model_name="fake", embedder=FakeEmbeddingProvider())
    assert result.recommended_score is not None
    assert result.recommended_score.false_positives == 0
    # No other zero-FP, positive-admitting threshold beats the recommended F1.
    eligible = [
        score for score in result.scores if score.zero_false_positive and score.true_positives > 0
    ]
    assert result.recommended_score.f1 == max(score.f1 for score in eligible)


def test_calibration_is_deterministic_from_seed() -> None:
    first = calibrate_threshold(_substrate(11), model_name="fake", embedder=FakeEmbeddingProvider())
    second = calibrate_threshold(
        _substrate(11), model_name="fake", embedder=FakeEmbeddingProvider()
    )
    assert first.recommended_threshold == second.recommended_threshold
    assert [e.similarity for e in first.examples] == [e.similarity for e in second.examples]


def test_recommendation_separates_the_classes_on_the_fake_embedder() -> None:
    # The synthetic positives (the full entity in a window) score above the
    # negatives (same-tenant 0.0; unrelated codename-only overlap), so the fake
    # embedder yields a clean zero-FP recommendation rather than the fallback.
    result = calibrate_threshold(_substrate(), model_name="fake", embedder=FakeEmbeddingProvider())
    assert result.recommended_score is not None
    assert result.recommended_score.recall == 1.0
    assert result.recommended_threshold > DEFAULT_SEMANTIC_THRESHOLD


class _ConstantEmbedder:
    """A degenerate embedder that maps every text to the same vector.

    Every observation then has cosine 1.0 to every marker, so no threshold can
    separate positives from negatives - it forces the zero-FP fallback path.
    """

    def embed(self, text: str) -> tuple[float, ...]:
        return (1.0, 0.0)


def test_unseparable_classes_fall_back_to_the_default_never_admitting_a_negative() -> None:
    result = calibrate_threshold(
        _substrate(), model_name="degenerate", embedder=_ConstantEmbedder()
    )
    # No clean separation exists, so no zero-FP positive-admitting threshold:
    assert result.recommended_score is None
    assert result.recommended_threshold == DEFAULT_SEMANTIC_THRESHOLD


def test_single_tenant_substrate_yields_an_empty_set() -> None:
    # Cross-tenant needs a distinct foreign observer; a one-tenant scenario has
    # none, so the harness emits nothing rather than a bogus same-tenant positive.
    scenario = default_scenario(seed=3)
    one = scenario.tenants[:1]
    solo = build_substrate(scenario.model_copy(update={"tenants": one}))
    pipeline = DetectionPipeline(solo, FakeEmbeddingProvider())
    assert build_calibration_set(solo, pipeline) == []
    # And calibration on it degrades gracefully to the default, never a crash.
    result = calibrate_threshold(solo, model_name="solo", embedder=FakeEmbeddingProvider())
    assert result.recommended_threshold == DEFAULT_SEMANTIC_THRESHOLD
    assert result.recommended_score is None


# --- best_foreign_similarity matches the gate -------------------------------


def test_best_foreign_similarity_is_the_value_the_gate_admits_on() -> None:
    # The harness scores on best_foreign_similarity; a foreign entity surfaced to
    # Y must score high enough that the detection gate, set to a threshold just
    # below that score, would admit it (and the value is clamped to [0, 1]).
    substrate = _substrate()
    pipeline = DetectionPipeline(substrate, FakeEmbeddingProvider())
    owner = substrate.tenants[0].tenant_id
    observer = substrate.tenants[1].tenant_id
    entity = next(
        marker
        for marker in substrate.manifest.markers
        if marker.owner_tenant_id == owner and marker.marker_type is MarkerType.ENTITY_CANARY
    )
    text = f"retrieved context mentioning {entity.plaintext} in passing"
    cross_tenant = pipeline.best_foreign_similarity(observer, text)
    assert 0.0 < cross_tenant <= 1.0
    # The cross-tenant observation (entity foreign to the observer) scores higher
    # than the owner's own view of the same text, where THIS entity is not foreign
    # and only the other tenants' shared-prefix entities contribute.
    own_view = pipeline.best_foreign_similarity(owner, text)
    assert cross_tenant > own_view


# --- per-model presets ------------------------------------------------------


def test_known_model_resolves_to_its_preset() -> None:
    for name, expected in MODEL_THRESHOLDS.items():
        assert resolve_semantic_threshold(name) == expected


def test_unknown_model_falls_back_to_default() -> None:
    assert resolve_semantic_threshold("openai:does-not-exist") == DEFAULT_SEMANTIC_THRESHOLD


def test_none_model_resolves_to_default() -> None:
    assert resolve_semantic_threshold(None) == DEFAULT_SEMANTIC_THRESHOLD


# --- the `auto` config form -------------------------------------------------


def test_numeric_threshold_is_used_verbatim() -> None:
    config = DetectionConfig(semantic_threshold=0.71)
    assert resolve_semantic_threshold_config(config) == 0.71
    assert build_detection_providers(config).semantic_threshold == 0.71


def test_auto_with_fake_embedder_resolves_to_default() -> None:
    config = DetectionConfig(semantic_threshold="auto", embedder=EmbedderConfig(kind="fake"))
    assert resolve_semantic_threshold_config(config) == DEFAULT_SEMANTIC_THRESHOLD


def test_auto_with_known_openai_model_resolves_to_preset() -> None:
    config = DetectionConfig(
        semantic_threshold="auto",
        embedder=EmbedderConfig(kind="openai", model="text-embedding-3-small"),
    )
    assert (
        resolve_semantic_threshold_config(config)
        == (MODEL_THRESHOLDS["openai:text-embedding-3-small"])
    )


def test_auto_with_unknown_openai_model_falls_back_to_default() -> None:
    config = DetectionConfig(
        semantic_threshold="auto",
        embedder=EmbedderConfig(kind="openai", model="text-embedding-9-imaginary"),
    )
    assert resolve_semantic_threshold_config(config) == DEFAULT_SEMANTIC_THRESHOLD


def test_embedder_model_name_canonical_forms() -> None:
    assert embedder_model_name(EmbedderConfig(kind="fake")) is None
    assert (
        embedder_model_name(EmbedderConfig(kind="openai", model="text-embedding-3-large"))
        == "openai:text-embedding-3-large"
    )
    # A bare openai embedder defaults the model so `auto` still finds a preset.
    assert embedder_model_name(EmbedderConfig(kind="openai")) == "openai:text-embedding-3-small"


def test_config_round_trips_auto_through_validation() -> None:
    # The literal "auto" must survive Pydantic validation (back-compat: a float too).
    assert (
        SectumConfig.model_validate(
            {"detection": {"semantic_threshold": "auto"}}
        ).detection.semantic_threshold
        == "auto"
    )
    assert (
        SectumConfig.model_validate(
            {"detection": {"semantic_threshold": 0.9}}
        ).detection.semantic_threshold
        == 0.9
    )


def test_config_rejects_a_non_auto_string() -> None:
    with pytest.raises(ValueError):
        SectumConfig.model_validate({"detection": {"semantic_threshold": "high"}})


# --- the CLI command --------------------------------------------------------


def test_cli_calibrate_text_output_recommends_a_threshold() -> None:
    result = _runner.invoke(app, ["calibrate", "--embedder", "fake", "--seed", "7"])
    assert result.exit_code == 0, result.output
    assert "recommended semantic_threshold:" in result.output
    assert "ZERO-FP" in result.output
    assert "detection:" in result.output  # prints the snippet to paste


def test_cli_calibrate_json_output_is_parseable() -> None:
    import json

    result = _runner.invoke(
        app, ["calibrate", "--embedder", "hash-256", "--seed", "7", "--output", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["model_name"] == "hash-256"
    assert payload["zero_false_positive"] is True
    assert payload["positives"] > 0
    assert payload["negatives"] > 0
    assert 0.0 <= payload["recommended_threshold"] <= 1.0
    # The score AT the recommended threshold admits no negative (the hard
    # constraint). Sub-recommended thresholds may admit negatives - that is why
    # they are not recommended - so only the recommended point must be zero-FP.
    recommended = payload["recommended_threshold"]
    at_recommended = [s for s in payload["scores"] if s["threshold"] == recommended]
    assert at_recommended, "the recommended threshold must appear in the scores table"
    assert all(s["zero_false_positive"] for s in at_recommended)
    assert all(s["false_positives"] == 0 for s in at_recommended)


def test_cli_calibrate_is_deterministic() -> None:
    args = ["calibrate", "--embedder", "fake", "--seed", "99", "--output", "json"]
    first = _runner.invoke(app, args)
    second = _runner.invoke(app, args)
    assert first.exit_code == 0
    assert first.output == second.output


def test_cli_calibrate_defaults_embedder_from_config(tmp_path: Path) -> None:
    config = tmp_path / "sectum-ai.yaml"
    config.write_text("detection:\n  embedder:\n    kind: fake\nscenario:\n  seed: 5\n")
    result = _runner.invoke(app, ["calibrate", "--config", str(config)])
    assert result.exit_code == 0, result.output
    assert "embedder: fake" in result.output


def test_cli_calibrate_rejects_an_unknown_embedder_spec() -> None:
    result = _runner.invoke(app, ["calibrate", "--embedder", "bogus-embedder"])
    assert result.exit_code == 3
    assert "does not name a real embedding model" in result.output


def test_cli_calibrate_rejects_sarif_output() -> None:
    result = _runner.invoke(app, ["calibrate", "--embedder", "fake", "--output", "sarif"])
    assert result.exit_code == 3
    assert "text or json" in result.output


def test_calibration_result_counts() -> None:
    result: CalibrationResult = calibrate_threshold(
        _substrate(), model_name="fake", embedder=FakeEmbeddingProvider()
    )
    assert result.positives + result.negatives == len(result.examples)
    assert result.positives > 0
    assert result.negatives > 0
